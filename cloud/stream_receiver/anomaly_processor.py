"""
Road anomaly processor for cloud model scheduling.

The scheduler owns the video stream and passes frames into this module. This
keeps anomaly detection independent from plate recognition while reusing the
same decoded frame when the cloud dispatcher switches scenes or models.
"""
import os
import sys
from collections import deque
from datetime import datetime


AI_MODELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_models")
if AI_MODELS_PATH not in sys.path:
    sys.path.append(AI_MODELS_PATH)

from anomaly_detection.anomaly_detector import AnomalyDetector


class RoadAnomalyProcessor:
    """Wraps MOG2 anomaly detection and formats cloud/front-end events."""

    def __init__(
        self,
        detector=None,
        lane_regions=None,
        max_results=50,
        emit_normal=False,
        warning_only=True,
    ):
        """
        Args:
            detector: Optional AnomalyDetector instance.
            lane_regions: Mapping like {"lane_1": [[x1,y1], ...]} for lane hit tests.
            max_results: Number of latest warning events to keep.
            emit_normal: Whether to return non-warning anomaly candidates.
            warning_only: Whether process_frame returns only warning events.
        """
        self.detector = detector or AnomalyDetector()
        self.lane_regions = lane_regions or {}
        self.latest_results = deque(maxlen=max_results)
        self.emit_normal = emit_normal
        self.warning_only = warning_only

        print("道路异常处理器初始化完成")

    def update_background(self, frame):
        """Allow the scheduler to feed clean road frames before detection starts."""
        self.detector.update_background(frame)

    def process_frame(self, device_id, frame, vehicle_bboxes=None, timestamp=None):
        """
        Analyze one decoded frame and return formatted road_anomaly events.

        Args:
            device_id: Source device id, e.g. mobile_001.
            frame: BGR image frame.
            vehicle_bboxes: Normal vehicle boxes from YOLO, excluded from MOG2 foreground.
            timestamp: Optional ISO timestamp.

        Returns:
            list[dict]: Events compatible with the cloud WebSocket schema.
        """
        timestamp = timestamp or datetime.now().isoformat()
        anomalies = self.detector.detect(frame, vehicle_bboxes=vehicle_bboxes)
        events = []

        for anomaly in anomalies:
            if self.warning_only and anomaly["status"] != "warning":
                continue
            if not self.emit_normal and anomaly["status"] == "normal":
                continue

            event = self._build_event(device_id, timestamp, anomaly)
            events.append(event)

            if event["status"] == "warning":
                self.latest_results.append(event)

        return events

    def reset(self):
        """Reset background model and cached results."""
        self.detector.reset()
        self.latest_results.clear()

    def get_latest_results(self, max_count=10):
        """Return the latest warning events without consuming them."""
        if max_count <= 0:
            return []
        return list(self.latest_results)[-max_count:]

    def _build_event(self, device_id, timestamp, anomaly):
        bbox = anomaly["bbox"]
        affected_lane = self._match_lane(anomaly["center"])

        # Keep both top-level fields from the system design and a nested data
        # object used by the current front-end mock format.
        return {
            "event_type": "road_anomaly",
            "timestamp": timestamp,
            "device_id": device_id,
            "anomaly_type": "unknown_object",
            "status": anomaly["status"],
            "affected_lane": affected_lane,
            "bbox": bbox,
            "duration_frames": anomaly["static_frames"],
            "data": {
                "anomaly_id": anomaly["anomaly_id"],
                "anomaly_type": "unknown_object",
                "affected_lane": affected_lane,
                "duration_frames": anomaly["static_frames"],
                "area": anomaly["area"],
                "center": anomaly["center"],
            },
        }

    def _match_lane(self, center):
        if not self.lane_regions:
            return "unknown"

        x, y = center
        for lane_id, polygon in self.lane_regions.items():
            if self._point_in_polygon(x, y, polygon):
                return lane_id
        return "unknown"

    def _point_in_polygon(self, x, y, polygon):
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-6) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside


if __name__ == "__main__":
    print("RoadAnomalyProcessor is ready for scheduler integration.")
