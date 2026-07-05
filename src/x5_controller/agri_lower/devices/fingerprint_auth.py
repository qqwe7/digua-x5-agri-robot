class FingerprintAuth:
    """Reserved fingerprint-authentication adapter for local login."""

    def __init__(self, port="/dev/ttyUSB1", enabled=False):
        self.port = port
        self.enabled = enabled
        self.online = False

    def open(self):
        self.online = False
        return self.online

    def is_online(self):
        return self.online

    def verify(self):
        return {"success": False, "user_id": None, "message": "fingerprint auth placeholder"}

    def register(self, user_id):
        return {"success": False, "user_id": user_id, "message": "fingerprint register placeholder"}
