class FaceAuth:
    """Reserved face-authentication adapter for local login."""

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.online = False

    def open(self):
        self.online = False
        return self.online

    def is_online(self):
        return self.online

    def verify(self, frame=None):
        return {"success": False, "user_id": None, "message": "face auth placeholder"}

    def register(self, user_id, frame=None):
        return {"success": False, "user_id": user_id, "message": "face register placeholder"}
