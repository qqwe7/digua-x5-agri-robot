import json


class Stm32Bridge:
    """Serial bridge to STM32. Commands are currently accepted as placeholders when disabled."""

    def __init__(self, port="/dev/ttyS1", baudrate=115200, enabled=False):
        self.port = port
        self.baudrate = baudrate
        self.enabled = enabled
        self.serial = None

    def open(self):
        if not self.enabled:
            return False
        try:
            import serial

            self.serial = serial.Serial(self.port, self.baudrate, timeout=0.2)
            return True
        except Exception as exc:
            print("stm32 serial unavailable:", exc)
            return False

    def is_online(self):
        return bool(self.serial and self.serial.is_open)

    def send(self, payload):
        if not self.is_online():
            print("stm32 placeholder send:", payload)
            return {"ok": True, "placeholder": True, "message": "stm32 not connected"}
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self.serial.write(line.encode("utf-8"))
        return {"ok": True, "message": "sent to stm32"}
