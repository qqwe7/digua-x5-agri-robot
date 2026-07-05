#!/usr/bin/env python3
import argparse
import struct
import sys
import time
from pathlib import Path

try:
    import serial
except ImportError as exc:
    raise SystemExit("python3-serial is required: sudo apt install python3-serial") from exc


FRAME_HEADER = b"\xAA\x55"
PROTO_VERSION = 0x01
MSG_STATUS = 0x01
MSG_CONTROL = 0x02
DEFAULT_CH340_BY_ID = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
DEFAULT_TTYUSB = "/dev/ttyUSB0"
STATUS_LEN = 20


def crc16_ibm(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def clamp_i16(value: int) -> int:
    return max(-32768, min(32767, int(value)))


def resolve_port(configured_port: str) -> str:
    if configured_port:
        return configured_port
    if Path(DEFAULT_CH340_BY_ID).exists():
        return DEFAULT_CH340_BY_ID
    return DEFAULT_TTYUSB


def pack_frame(msg_id: int, seq: int, payload: bytes) -> bytes:
    body = bytes([PROTO_VERSION, msg_id, seq & 0xFF, len(payload)]) + payload
    return FRAME_HEADER + body + struct.pack("<H", crc16_ibm(body))


def parse_status_frames(rx_buffer: bytearray):
    frames = []
    while True:
        header_index = rx_buffer.find(FRAME_HEADER)
        if header_index < 0:
            rx_buffer.clear()
            return frames

        if header_index > 0:
            del rx_buffer[:header_index]

        if len(rx_buffer) < 8:
            return frames

        version = rx_buffer[2]
        msg_id = rx_buffer[3]
        payload_len = rx_buffer[5]
        frame_len = 6 + payload_len + 2
        if len(rx_buffer) < frame_len:
            return frames

        frame = bytes(rx_buffer[:frame_len])
        del rx_buffer[:frame_len]

        if version != PROTO_VERSION:
            continue

        body = frame[2:-2]
        rx_crc = struct.unpack_from("<H", frame, frame_len - 2)[0]
        if crc16_ibm(body) != rx_crc:
            print("drop bad crc frame:", frame.hex(" "))
            continue

        if msg_id != MSG_STATUS or payload_len != STATUS_LEN:
            continue

        frames.append(struct.unpack("<IhhhhhhBBBB", frame[6:-2]))


def format_status(status) -> str:
    (
        tick_ms,
        yaw_raw_cdeg,
        yaw_zero_cdeg,
        yaw_rel_cdeg,
        gyro_z_cdegps,
        left_speed_mmps,
        right_speed_mmps,
        imu_online,
        motor_online,
        chassis_mode,
        fault_code,
    ) = status
    return (
        f"tick={tick_ms} yaw_raw={yaw_raw_cdeg / 100.0:.2f} "
        f"yaw_zero={yaw_zero_cdeg / 100.0:.2f} yaw_rel={yaw_rel_cdeg / 100.0:.2f} "
        f"gyro_z={gyro_z_cdegps / 100.0:.2f} left={left_speed_mmps}mm/s "
        f"right={right_speed_mmps}mm/s imu={imu_online} motor={motor_online} "
        f"mode={chassis_mode} fault=0x{fault_code:02X}"
    )


def make_control_payload(linear_mmps: int, angular_cdegps: int, control_mode: int) -> bytes:
    return struct.pack(
        "<hhhBBH",
        clamp_i16(linear_mmps),
        clamp_i16(angular_cdegps),
        0,
        control_mode & 0xFF,
        0,
        0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="STM32 UART6 protocol smoke test.")
    parser.add_argument("--port", default="", help="Serial port. Empty means CH340 by-id, then /dev/ttyUSB0.")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--period", type=float, default=0.05)
    parser.add_argument("--control-to-status-delay", type=float, default=0.05)
    parser.add_argument("--timeout", type=float, default=0.10)
    parser.add_argument("--linear-mmps", type=int, default=0)
    parser.add_argument("--angular-cdegps", type=int, default=0)
    parser.add_argument("--enable-motion", action="store_true")
    args = parser.parse_args()

    has_motion = args.linear_mmps != 0 or args.angular_cdegps != 0
    if has_motion and not args.enable_motion:
        print("Refusing nonzero motion command without --enable-motion.", file=sys.stderr)
        return 2

    port = resolve_port(args.port)
    rx_buffer = bytearray()
    seq = 0
    ok = 0
    miss = 0

    ser = serial.Serial(port, args.baudrate, timeout=0.01, write_timeout=0.2)
    ser.dtr = False
    ser.rts = False
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    print(f"opened {port} @ {args.baudrate}")

    try:
        for i in range(args.count):
            payload = make_control_payload(args.linear_mmps, args.angular_cdegps, 0)
            packet = pack_frame(MSG_CONTROL, seq, payload)
            seq = (seq + 1) & 0xFF
            if i == 0:
                print("send control:", packet.hex(" "))
            ser.write(packet)
            ser.flush()

            time.sleep(args.control_to_status_delay)
            ser.write(b"\x01")
            ser.flush()
            deadline = time.monotonic() + args.timeout
            status = None
            while time.monotonic() < deadline:
                data = ser.read(512)
                if data:
                    rx_buffer.extend(data)
                    frames = parse_status_frames(rx_buffer)
                    if frames:
                        status = frames[-1]
                        break

            if status is None:
                miss += 1
                print(f"{i:03d} MISS")
            else:
                ok += 1
                print(f"{i:03d} {format_status(status)}")

            time.sleep(args.period)
    finally:
        stop_payload = make_control_payload(0, 0, 3)
        for _ in range(3):
            ser.write(pack_frame(MSG_CONTROL, seq, stop_payload))
            seq = (seq + 1) & 0xFF
            time.sleep(0.03)
        ser.close()

    print(f"result ok={ok} miss={miss}")
    return 0 if ok > 0 and miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
