import base64


FALLBACK_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class CameraDevice:
    """Common RGB camera adapter based on OpenCV."""

    def __init__(self, index=0, enabled=True):
        self.index = index
        self.enabled = enabled
        self.cv2 = None

    def open(self):
        if not self.enabled:
            return False
        try:
            import cv2

            self.cv2 = cv2
            return True
        except Exception as exc:
            print("camera opencv unavailable:", exc)
            return False

    def is_online(self):
        if not self.enabled:
            return False
        if self.cv2 is None:
            self.open()
        if self.cv2 is None:
            return False
        cap = self.cv2.VideoCapture(self.index)
        ok = cap.isOpened()
        cap.release()
        return bool(ok)

    def capture_data_url(self):
        if self.cv2 is None:
            self.open()
        if self.cv2 is None:
            return FALLBACK_IMAGE

        cap = self.cv2.VideoCapture(self.index)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return FALLBACK_IMAGE

        ok, buf = self.cv2.imencode(".jpg", frame)
        if not ok:
            return FALLBACK_IMAGE
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
