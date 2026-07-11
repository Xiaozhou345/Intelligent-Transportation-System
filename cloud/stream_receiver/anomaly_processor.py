"""
Road anomaly processor for cloud model scheduling.

The scheduler owns the video stream and passes frames into this module. The
detector assumes a fixed camera during detection and uses MOG2 background
subtraction, YOLO vehicle masks, optional road-area masks, and temporal
confirmation.
"""
import os
import sys
from collections import deque
from datetime import datetime


AI_MODELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_models")
if AI_MODELS_PATH not in sys.path:
    sys.path.append(AI_MODELS_PATH)

from anomaly_detection.anomaly_detector import AnomalyDetector
from anomaly_detection.drivable_segmenter import DrivableAreaSegmenter


class RoadAnomalyProcessor:
    """Formats MOG2 road anomaly detections as cloud/front-end events."""

    def __init__(
        self,
        detector=None,
        lane_regions=None,
        max_results=50,
        emit_normal=False,
        warning_only=True,
        event_cooldown_frames=30,
        drivable_model_path=None,
        drivable_confidence=0.15,
    ):
        """
        Args:
            detector: Optional AnomalyDetector instance.
            lane_regions: Mapping like {"lane_1": [[x1,y1], ...]} for lane hit tests.
            max_results: Number of latest warning events to keep.
            emit_normal: Whether to return non-warning anomaly candidates.
            warning_only: Whether process_frame returns only warning events.
            event_cooldown_frames: Re-emit same warning after this many stable frames.
            drivable_model_path: Optional YOLO-seg model for road-area masking.
            drivable_confidence: Confidence threshold for drivable segmentation.
        """
        self.detector = detector or AnomalyDetector()
        self.lane_regions = lane_regions or {}
        self.latest_results = deque(maxlen=max_results)
        self.emit_normal = emit_normal
        self.warning_only = warning_only
        self.event_cooldown_frames = max(1, int(event_cooldown_frames))
        self.last_emitted_frames = {}
        self.processed_frames = 0
        self.recent_warning_regions = deque(maxlen=max_results)
        self.drivable_segmenter = None

        if drivable_model_path:
            self.drivable_segmenter = DrivableAreaSegmenter(
                drivable_model_path,
                confidence=drivable_confidence,
            )

        print("道路异常处理器初始化完成")

    def update_background(self, frame, road_mask=None, vehicle_bboxes=None):
        """Feed clean static-camera frames into the background model."""
        if road_mask is None and self.drivable_segmenter:
            road_mask = self.drivable_segmenter.predict_mask(frame)
        return self.detector.update_background(
            frame=frame,
            road_mask=road_mask,
            vehicle_bboxes=vehicle_bboxes,
        )

    def process_frame(self, device_id, frame, vehicle_bboxes=None, timestamp=None, road_mask=None):
        """
        Analyze one decoded frame and return formatted road_anomaly events.

        Args:
            device_id: Source device id, e.g. mobile_001.
            frame: BGR image frame.
            vehicle_bboxes: Normal vehicle boxes from YOLO, excluded from anomaly mask.
            timestamp: Optional ISO timestamp.
            road_mask: Optional current drivable-area mask from scheduler/tests.

        Returns:
            list[dict]: Events compatible with the cloud WebSocket schema.
        """
        timestamp = timestamp or datetime.now().isoformat()
        self.processed_frames += 1
        if road_mask is None and self.drivable_segmenter:
            road_mask = self.drivable_segmenter.predict_mask(frame)

        anomalies = self.detector.detect(
            frame,
            vehicle_bboxes=vehicle_bboxes,
            road_mask=road_mask,
        )
        events = []

        for anomaly in anomalies:
            if self.warning_only and anomaly["status"] != "warning":
                continue
            if not self.emit_normal and anomaly["status"] == "normal":
                continue
            if anomaly["status"] == "warning" and not self._should_emit_warning(anomaly):
                continue

            event = self._build_event(device_id, timestamp, anomaly)
            events.append(event)

            if event["status"] == "warning":
                self.latest_results.append(event)

        return events

    def predict_road_mask(self, frame):
        """Return current drivable mask when a segmenter is available."""
        if not self.drivable_segmenter:
            return None
        return self.drivable_segmenter.predict_mask(frame)

    @property
    def background_frames(self):
        """Expose the detector's background-learning progress to the scheduler/API."""
        return int(getattr(self.detector, "background_frames", 0))

    def reset(self):
        """Reset background model and cached results."""
        self.detector.reset()
        self.latest_results.clear()
        self.last_emitted_frames.clear()
        self.processed_frames = 0
        self.recent_warning_regions.clear()

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

    def _should_emit_warning(self, anomaly):
        anomaly_id = anomaly["anomaly_id"]
        static_frames = anomaly["static_frames"]
        last_static_frames = self.last_emitted_frames.get(anomaly_id)

        if self._recent_region_seen(anomaly):
            return False

        if last_static_frames is None:
            self.last_emitted_frames[anomaly_id] = static_frames
            self._remember_warning_region(anomaly)
            return True

        if static_frames - last_static_frames >= self.event_cooldown_frames:
            self.last_emitted_frames[anomaly_id] = static_frames
            self._remember_warning_region(anomaly)
            return True

        return False

    def _recent_region_seen(self, anomaly):
        bbox = anomaly["bbox"]
        center = anomaly["center"]
        for region in self.recent_warning_regions:
            if self.processed_frames - region["frame"] > self.event_cooldown_frames:
                continue
            if self._bbox_iou(bbox, region["bbox"]) >= 0.2:
                return True
            if self._center_distance(center, region["center"]) <= region["radius"]:
                return True
        return False

    def _remember_warning_region(self, anomaly):
        x1, y1, x2, y2 = anomaly["bbox"]
        radius = max(60, (x2 - x1 + y2 - y1) // 2)
        self.recent_warning_regions.append({
            "frame": self.processed_frames,
            "bbox": anomaly["bbox"],
            "center": anomaly["center"],
            "radius": radius,
        })

    def _bbox_iou(self, a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(area_a + area_b - inter)

    def _center_distance(self, a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

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
