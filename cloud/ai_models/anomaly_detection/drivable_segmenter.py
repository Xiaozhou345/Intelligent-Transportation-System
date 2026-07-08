"""
Drivable-area segmentation wrapper for road anomaly detection.

The anomaly detector can also receive masks directly from an external scheduler,
but this wrapper lets it run the sandbox drivable YOLO-seg model itself.
"""
import os
from pathlib import Path

import cv2
import numpy as np


class DrivableAreaSegmenter:
    """Runs a YOLO segmentation model and returns a binary drivable-road mask."""

    def __init__(self, model_path, confidence=0.15, image_size=640):
        self.model_path = model_path
        self.confidence = confidence
        self.image_size = image_size
        self._ensure_ultralytics_config_dir()

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics is required for drivable-area segmentation. "
                "Install cloud/requirements.txt first."
            ) from exc

        self.model = YOLO(model_path)

    def _ensure_ultralytics_config_dir(self):
        if os.getenv("YOLO_CONFIG_DIR"):
            return
        repo_root = Path(__file__).resolve().parents[3]
        config_dir = repo_root / ".ultralytics_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        os.environ["YOLO_CONFIG_DIR"] = str(config_dir)

    def predict_mask(self, frame):
        """Return a uint8 mask where 255 means drivable area."""
        if frame is None or frame.size == 0:
            return None

        result = self.model.predict(
            source=frame,
            conf=self.confidence,
            imgsz=self.image_size,
            verbose=False,
        )[0]

        if result.masks is None:
            return np.zeros(frame.shape[:2], dtype=np.uint8)

        combined = np.zeros(frame.shape[:2], dtype=np.uint8)
        masks = result.masks.data.cpu().numpy()
        for mask in masks:
            mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
            combined = np.maximum(combined, (mask > 0.5).astype(np.uint8) * 255)

        return combined
