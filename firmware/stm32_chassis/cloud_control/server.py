#!/usr/bin/env python3
import argparse
import json
import os
import posixpath
import socket
import socketserver
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse


STATIC_DIR = Path(__file__).resolve().parent / "static"


class CarConnection:
    def __init__(self, sock: socket.socket, address):
        self.sock = sock
        self.address = f"{address[0]}:{address[1]}"
        self.connected_at = time.time()
        self.last_seen = self.connected_at
        self.last_reply = ""
        self.reply_count = 0
        self.closed = False
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)

    def send_command(self, command: str, timeout: float = 2.0):
        payload = (command.strip() + "\n").encode("utf-8", errors="ignore")
        with self.lock:
            if self.closed:
                raise ConnectionError("car is offline")

            start_count = self.reply_count
            self.sock.sendall(payload)
            deadline = time.time() + timeout

            while self.reply_count == start_count and not self.closed:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)

            return self.last_reply if self.reply_count != start_count else ""

    def on_line(self, line: str):
        with self.lock:
            self.last_seen = time.time()
            self.last_reply = line
            self.reply_count += 1
            self.cond.notify_all()

    def close(self):
        with self.lock:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass
            self.cond.notify_all()


class ControlState:
    def __init__(self, token: str):
        self.token = token
        self.lock = threading.RLock()
        self.car: Optional[CarConnection] = None
        self.last_command = ""
        self.last_command_at = 0.0

    def attach_car(self, car: CarConnection):
        with self.lock:
            old_car = self.car
            self.car = car

        if old_car is not None and old_car is not car:
            old_car.close()

    def detach_car(self, car: CarConnection):
        with self.lock:
            if self.car is car:
                self.car = None

    def get_car(self) -> Optional[CarConnection]:
        with self.lock:
            return self.car

    def car_online(self, car: Optional[CarConnection] = None) -> bool:
        with self.lock:
            current = self.car if car is None else car

        if current is None or current.closed:
            return False

        if getattr(current, "connected", True):
            return True

        last_seen = float(getattr(current, "last_seen", 0.0) or 0.0)
        reply_count = int(getattr(current, "reply_count", 0) or 0)
        if reply_count <= 0 or last_seen <= 0.0:
            return False

        return (time.time() - last_seen) <= 3.0

    def set_last_command(self, command: str):
        with self.lock:
            self.last_command = command
            self.last_command_at = time.time()

    def snapshot(self):
        with self.lock:
            car = self.car
            is_connected = self.car_online(car)
            data = {
                "connected": is_connected,
                "car_address": car.address if car is not None else "",
                "connected_at": car.connected_at if car is not None else 0.0,
                "last_seen": car.last_seen if car is not None else 0.0,
                "last_reply": car.last_reply if car is not None else "",
                "reply_count": car.reply_count if car is not None else 0,
                "last_command": self.last_command,
                "last_command_at": self.last_command_at,
                "server_time": time.time(),
            }
        return data


class CarTcpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        car = CarConnection(self.request, self.client_address)
        self.server.state.attach_car(car)
        print(f"[TCP] car connected: {car.address}")
        self.request.settimeout(1.0)
        buffer = b""
        disconnect_reason = "peer closed"

        try:
            while True:
                try:
                    chunk = self.request.recv(1024)
                except socket.timeout:
                    continue
                except OSError as exc:
                    disconnect_reason = f"socket error: {exc}"
                    break

                if not chunk:
                    break

                buffer += chunk
                car.last_seen = time.time()
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if line:
                        car.on_line(line)
                        print(f"[TCP] {car.address} -> {line}")
        finally:
            car.close()
            self.server.state.detach_car(car)
            print(f"[TCP] car disconnected: {car.address} ({disconnect_reason})")


class ThreadingTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_cls, state: ControlState):
        self.state = state
        super().__init__(server_address, handler_cls)


class ControlHttpHandler(BaseHTTPRequestHandler):
    server_version = "CarCloudControl/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
          self.handle_api_state()
        else:
          self.handle_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/command":
            self.handle_api_command()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")

    def handle_api_state(self):
        if not self.authorized():
            return
        self.send_json(self.server.state.snapshot())

    def handle_api_command(self):
        if not self.authorized():
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return

        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Body must be JSON")
            return

        command = str(payload.get("command", "")).strip()
        if not command:
            self.send_json({"ok": False, "error": "command is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        car = self.server.state.get_car()
        if car is None or car.closed:
            self.send_json({"ok": False, "error": "car is offline"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return

        self.server.state.set_last_command(command)

        try:
            reply = car.send_command(command)
        except ConnectionError as exc:
            self.send_json({"ok": False, "error": str(exc) or "car is offline"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        except OSError as exc:
            self.send_json({"ok": False, "error": f"send failed: {exc}"}, status=HTTPStatus.BAD_GATEWAY)
            return

        self.send_json({
            "ok": True,
            "command": command,
            "reply": reply,
            "state": self.server.state.snapshot(),
        })

    def handle_static(self, raw_path: str):
        path = raw_path if raw_path not in ("", "/") else "/index.html"
        safe_path = posixpath.normpath(path).lstrip("/")
        if not safe_path:
            safe_path = "index.html"

        file_path = (STATIC_DIR / safe_path).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content_type = "text/plain; charset=utf-8"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not self.server.state.token:
            return True

        parsed = urlparse(self.path)
        token = self.headers.get("X-Token", "")
        if not token:
            token = parse_qs(parsed.query).get("token", [""])[0]

        if token != self.server.state.token:
            self.send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return False

        return True

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} - {fmt % args}")


class ThreadingControlHttpServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, state: ControlState):
        self.state = state
        super().__init__(server_address, handler_cls)


def main():
    parser = argparse.ArgumentParser(description="Cloud bridge for 4G car control")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address for HTTP and TCP servers")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP port for the control website")
    parser.add_argument("--tcp-port", type=int, default=9000, help="TCP port for the car 4G module")
    parser.add_argument("--token", default=os.environ.get("CAR_CONTROL_TOKEN", "car123"), help="Simple shared token for the web API")
    args = parser.parse_args()

    state = ControlState(args.token)
    tcp_server = ThreadingTcpServer((args.bind, args.tcp_port), CarTcpHandler, state)
    http_server = ThreadingControlHttpServer((args.bind, args.http_port), ControlHttpHandler, state)

    tcp_thread = threading.Thread(target=tcp_server.serve_forever, name="car-tcp", daemon=True)
    tcp_thread.start()

    print(f"[BOOT] HTTP control page: http://{args.bind}:{args.http_port}")
    print(f"[BOOT] TCP bridge for car: {args.bind}:{args.tcp_port}")
    print(f"[BOOT] token: {args.token}")
    print("[BOOT] Open the HTTP page on your phone, and configure M100P transparent TCP to the TCP bridge port.")

    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\n[BOOT] shutting down...")
    finally:
        http_server.shutdown()
        tcp_server.shutdown()
        http_server.server_close()
        tcp_server.server_close()


if __name__ == "__main__":
    main()
