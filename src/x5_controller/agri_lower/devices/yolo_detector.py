class YoloDetector:
    """YOLO detector with optional annotation and distance fusion hooks."""

    def __init__(self, model_path="", enabled=False, target_class="blueberry"):
        self.model_path = model_path
        self.enabled = enabled
        self.target_class = target_class
        self.online = False
        self.model = None
        self.cv2 = None

    def load(self):
        if not self.enabled:
            self.online = False
            return False
        try:
            from ultralytics import YOLO
            import cv2

            self.model = YOLO(self.model_path)
            self.cv2 = cv2
            self.online = True
            return True
        except Exception:
            self.model = None
            self.cv2 = None
            self.online = False
            return False

    def is_online(self):
        return self.online

    def _estimate_distance(self, depth_frame, xyxy):
        if depth_frame is None:
            return None
        try:
            x1, y1, x2, y2 = [int(v) for v in xyxy]
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            y_min = max(cy - 2, 0)
            y_max = min(cy + 3, depth_frame.shape[0])
            x_min = max(cx - 2, 0)
            x_max = min(cx + 3, depth_frame.shape[1])
            roi = depth_frame[y_min:y_max, x_min:x_max]
            valid = roi[roi > 0]
            if valid.size == 0:
                return None
            return float(valid.mean()) / 1000.0
        except Exception:
            return None

    def _annotate(self, image, boxes):
        if self.cv2 is None or image is None:
            return image
        annotated = image.copy()
        for box in boxes:
            x1, y1, x2, y2 = [int(v) for v in box["xyxy"]]
            label = f'{box["class_name"]} {box["confidence"]:.2f}'
            if box.get("distance_m") is not None:
                label += f' {box["distance_m"]:.2f}m'
            self.cv2.rectangle(annotated, (x1, y1), (x2, y2), (40, 220, 80), 2)
            self.cv2.putText(annotated, label, (x1, max(20, y1 - 8)), self.cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 220, 80), 2)
        return annotated

    def detect(self, image, depth_frame=None):
        if not self.online or self.model is None:
            return {
                "available": False,
                "target_class": None,
                "confidence": 0.0,
                "distance_m": None,
                "boxes": [],
                "annotated_image": None,
                "message": "yolo detector offline",
            }

        try:
            results = self.model(image, verbose=False)
            if not results:
                raise RuntimeError("no results")

            result = results[0]
            names = getattr(result, "names", {})
            boxes = []
            top_class = None
            top_conf = 0.0
            top_distance = None

            for box in getattr(result, "boxes", []):
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                xyxy = [float(v) for v in box.xyxy[0].tolist()]
                class_name = names.get(cls_id, str(cls_id))
                distance_m = self._estimate_distance(depth_frame, xyxy)
                item = {
                    "class_id": cls_id,
                    "class_name": class_name,
                    "confidence": conf,
                    "xyxy": xyxy,
                    "distance_m": distance_m,
                }
                boxes.append(item)
                if conf > top_conf:
                    top_conf = conf
                    top_class = class_name
                    top_distance = distance_m

            annotated = self._annotate(image, boxes)
            return {
                "available": True,
                "target_class": top_class,
                "confidence": top_conf,
                "distance_m": top_distance,
                "boxes": boxes,
                "annotated_image": annotated,
                "message": "ok",
            }
        except Exception as exc:
            return {
                "available": False,
                "target_class": None,
                "confidence": 0.0,
                "distance_m": None,
                "boxes": [],
                "annotated_image": None,
                "message": "detect failed: " + str(exc),
            }

