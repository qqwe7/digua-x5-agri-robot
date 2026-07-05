#!/usr/bin/env python3
import json
import threading
import time
import webbrowser
from pathlib import Path

import serial

from server import ControlHttpHandler, ControlState, ThreadingControlHttpServer


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "local_test_config.json"


class LocalSerialCar:
    def __init__(self, serial_port: str, serial_baud: int):
        self.serial_port = serial_port
        self.serial_baud = serial_baud
        self.address = serial_port
        self.connected_at = 0.0
        self.last_seen = 0.0
        self.last_reply = ""
        self.reply_count = 0
        self.closed = False
        self.connected = False

        self._serial = None
        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._open_lock = threading.Lock()
        self._cond = threading.Condition(self._state_lock)
        self._stop_event = threading.Event()
        self._retry_hint_ts = 0.0
        self._last_open_ts = 0.0
        self._mode_ready = False
        self._last_log_line = ""
        self._last_log_ts = 0.0
        self._suppressed_line = ""
        self._suppressed_count = 0
        self._suppressed_since = 0.0

    def start(self):
        while not self._stop_event.is_set():
            if self._serial is None:
                self._try_open_serial()
                if self._serial is None:
                    time.sleep(0.6)
                    continue

            try:
                raw = self._serial.readline()
                if not raw:
                    time.sleep(0.02)
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    with self._state_lock:
                        self.last_seen = time.time()
                        self.last_reply = line
                        self.reply_count += 1
                        self._cond.notify_all()
                    self._log_serial_line(line)
            except (serial.SerialException, OSError) as exc:
                print(f"[SERIAL] read reconnect: {exc}")
                self._close_serial()
                time.sleep(0.4)

    def send_command(self, command: str, timeout: float = 0.8):
        normalized = command.strip()
        if not normalized:
            return ""

        last_exc = None
        for attempt in range(2):
            try:
                return self._send_command_once(normalized, timeout)
            except ConnectionError as exc:
                last_exc = exc
                self._close_serial()
                if attempt == 0 and self._ensure_connected(2.5):
                    continue
                raise last_exc

        raise last_exc or ConnectionError("serial offline")

    def close(self):
        with self._state_lock:
            if self.closed:
                return
            self.closed = True
            self._stop_event.set()
            self._cond.notify_all()

        self._close_serial()

    def _try_open_serial(self):
        with self._open_lock:
            if self._serial is not None and self.connected:
                return

            try:
                conn = serial.Serial(
                    self.serial_port,
                    self.serial_baud,
                    timeout=0.1,
                    write_timeout=0.8,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
                conn.dtr = False
                conn.rts = False
                conn.reset_input_buffer()
                conn.reset_output_buffer()

                now = time.time()
                with self._state_lock:
                    self._serial = conn
                    self.connected = True
                    self.connected_at = now
                    self.last_seen = now
                    self._last_open_ts = now
                    self._mode_ready = False
                    self._cond.notify_all()
                print(f"[SERIAL] opened: {self.serial_port} @ {self.serial_baud}")
            except serial.SerialException as exc:
                print(f"[SERIAL] waiting {self.serial_port}: {exc}")
                if (time.time() - self._retry_hint_ts) >= 3.0:
                    self._retry_hint_ts = time.time()
                    print("[SERIAL] hint: close VOFA, serial assistant, or Keil serial window if they are using this COM port")

    def _close_serial(self):
        with self._open_lock:
            conn = None
            with self._state_lock:
                self._flush_suppressed_logs(force=True)
                conn = self._serial
                self._serial = None
                self.connected = False
                self._mode_ready = False
                self._cond.notify_all()

            if conn is not None:
                try:
                    conn.close()
                except serial.SerialException:
                    pass

    def _ensure_connected(self, timeout: float):
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stop_event.is_set():
            if self.connected and self._serial is not None:
                return True

            self._try_open_serial()
            if self.connected and self._serial is not None:
                return True

            time.sleep(0.25)

        return self.connected and self._serial is not None

    def _needs_speed_mode(self, command: str):
        prefixes = ("carfwd", "carback", "carleft", "carright", "canrpm", "can4")
        return command.startswith(prefixes)

    def _should_suppress_line(self, line: str, now_ts: float) -> bool:
        if "len=1: 01" in line:
            return True
        if line == self._last_log_line and (now_ts - self._last_log_ts) < 0.35:
            return True
        return False

    def _flush_suppressed_logs(self, force: bool = False):
        if not self._suppressed_count or not self._suppressed_line:
            return

        now_ts = time.time()
        if not force and (now_ts - self._suppressed_since) < 2.0:
            return

        age = max(0.0, now_ts - self._suppressed_since)
        print(
            f"[SERIAL] {self.serial_port} -> {self._suppressed_line} "
            f"(same reply x{self._suppressed_count} suppressed over {age:.1f}s)"
        )
        self._last_log_line = self._suppressed_line
        self._last_log_ts = now_ts
        self._suppressed_line = ""
        self._suppressed_count = 0
        self._suppressed_since = 0.0

    def _log_serial_line(self, line: str):
        now_ts = time.time()
        if self._should_suppress_line(line, now_ts):
            if line == self._suppressed_line:
                self._suppressed_count += 1
            else:
                self._flush_suppressed_logs(force=True)
                self._suppressed_line = line
                self._suppressed_count = 1
                self._suppressed_since = now_ts
            self._flush_suppressed_logs(force=False)
            return

        self._flush_suppressed_logs(force=True)
        self._last_log_line = line
        self._last_log_ts = now_ts
        print(f"[SERIAL] {self.serial_port} -> {line}")

    def _write_and_wait_locked(self, command: str, timeout: float):
        if self._serial is None:
            raise ConnectionError("serial offline")

        payload = (command + "\r\n").encode("utf-8", errors="ignore")
        with self._state_lock:
            start_count = self.reply_count

        self._serial.write(payload)
        self._serial.flush()

        deadline = time.time() + timeout
        with self._state_lock:
            while self.reply_count == start_count and self.connected and not self.closed:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)

            return self.last_reply if self.reply_count != start_count else ""

    def _send_command_once(self, command: str, timeout: float):
        if not self._ensure_connected(2.5):
            raise ConnectionError("serial offline")

        with self._io_lock:
            if not self.connected or self._serial is None:
                raise ConnectionError("serial offline")

            try:
                # Give the MCU a brief moment to finish rebooting after power cycling.
                if (time.time() - self._last_open_ts) < 1.0:
                    time.sleep(1.0 - (time.time() - self._last_open_ts))

                if self._needs_speed_mode(command) and not self._mode_ready:
                    mode_reply = self._write_and_wait_locked("canmode", 0.8)
                    if mode_reply:
                        print(f"[SERIAL] auto canmode -> {mode_reply}")
                    self._mode_ready = True
                    time.sleep(0.08)

                reply = self._write_and_wait_locked(command, timeout)
                if command == "canmode":
                    self._mode_ready = True
                elif command in ("carstop", "canstopall"):
                    pass
                return reply
            except (serial.SerialException, OSError) as exc:
                raise ConnectionError(f"serial write failed: {exc}") from exc


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def main():
    config = load_config()
    bind = config.get("bind", "127.0.0.1")
    http_port = int(config.get("http_port", 8080))
    token = str(config.get("token", "localcar"))
    serial_port = str(config.get("serial_port", "COM11"))
    serial_baud = int(config.get("serial_baud", 115200))

    state = ControlState(token)
    car = LocalSerialCar(serial_port, serial_baud)
    state.attach_car(car)

    http_server = ThreadingControlHttpServer((bind, http_port), ControlHttpHandler, state)
    http_thread = threading.Thread(target=http_server.serve_forever, name="http-ui", daemon=True)
    serial_thread = threading.Thread(target=car.start, name="local-serial", daemon=True)
    http_thread.start()
    serial_thread.start()

    browser_url = config.get("browser_url") or f"http://{bind}:{http_port}/?token={token}"
    if config.get("open_browser", True):
        time.sleep(1.0)
        webbrowser.open(browser_url)

    print("[BOOT] local web control ready")
    print(f"[BOOT] browser: {browser_url}")
    print(f"[BOOT] stm32 serial: {serial_port} @ {serial_baud}")
    print("[BOOT] close this window to stop")

    try:
        while not car.closed:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        car.close()
        http_server.shutdown()
        http_server.server_close()


if __name__ == "__main__":
    main()
