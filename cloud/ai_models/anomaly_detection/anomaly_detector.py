"""
Road anomaly detection based on MOG2 background subtraction, YOLO vehicle masks,
road-area masks, and temporal confirmation.

This version assumes the camera is fixed during detection. It is suitable for
sandbox demos where the edge device is placed first, then the road scene is
monitored from a static viewpoint.
"""
import cv2
import numpy as np


class AnomalyDetector:
    """Detects persistent non-vehicle foreground objects on the road."""

    def __init__(
        self,
        history=500,
        var_threshold=24,
        detect_shadows=False,
        min_area=500,
        static_frames_threshold=15,
        match_distance=50,
        max_missed_frames=3,
        vehicle_mask_padding=6,
        road_roi=None,
        warmup_frames=30,
        learning_rate=0,
        startup_static_check=True,
        startup_static_kernel=35,
        startup_static_dilate=3,
        road_surface_outlier_check=True,
        outlier_min_area=250,
        outlier_color_distance=28,
        outlier_max_area=30000,
        **_legacy_kwargs,
    ):
        """
        Args:
            history: Number of frames used by the MOG2 background model.
            var_threshold: MOG2 variance threshold; higher is less sensitive.
            detect_shadows: Whether MOG2 keeps shadow labels.
            min_area: Minimum connected component area to keep.
            static_frames_threshold: Frames required before warning.
            match_distance: Cross-frame center matching distance.
            max_missed_frames: Frames a tracked anomaly can disappear before reset.
            vehicle_mask_padding: Padding around YOLO vehicle boxes.
            road_roi: Optional polygon limiting the active road area.
            warmup_frames: Initial frames used to build background if not fed manually.
            learning_rate: Detection-time background update rate. Use 0 to freeze.
            startup_static_check: Detect road-mask holes that may be objects present
                from the first frame.
            startup_static_kernel: Closing kernel size used to recover the expected
                road surface for startup static-object detection.
            startup_static_dilate: Dilation kernel size for startup static holes.
            road_surface_outlier_check: Detect compact non-road-surface blobs in
                the road area, useful when an object exists from the first frame.
            outlier_min_area: Minimum compact candidate area for surface outliers.
            outlier_color_distance: LAB distance from estimated road surface.
            outlier_max_area: Maximum compact candidate area for surface outliers.
        """
        self.history = history
        self.var_threshold = var_threshold
        self.detect_shadows = detect_shadows
        self.min_area = min_area
        self.static_frames_threshold = static_frames_threshold
        self.match_distance = match_distance
        self.max_missed_frames = max_missed_frames
        self.vehicle_mask_padding = vehicle_mask_padding
        self.road_roi = road_roi
        self.warmup_frames = warmup_frames
        self.learning_rate = learning_rate
        self.startup_static_check = startup_static_check
        self.startup_static_kernel = startup_static_kernel if startup_static_kernel % 2 else startup_static_kernel + 1
        self.startup_static_dilate = max(0, int(startup_static_dilate))
        self.road_surface_outlier_check = road_surface_outlier_check
        self.outlier_min_area = outlier_min_area
        self.outlier_color_distance = outlier_color_distance
        self.outlier_max_area = outlier_max_area

        self.bg_subtractor = self._create_subtractor()
        self.background_frames = 0
        self.anomaly_id_counter = 0
        self.tracked_anomalies = {}

        print("道路异常检测器初始化完成：MOG2 + YOLO车辆掩膜 + 道路区域约束 + 时序判定")

    def _create_subtractor(self):
        return cv2.createBackgroundSubtractorMOG2(
            history=self.history,
            varThreshold=self.var_threshold,
            detectShadows=self.detect_shadows,
        )

    def update_background(self, frame=None, road_mask=None):
        """Feed a clean static-camera frame into the MOG2 background model."""
        if frame is None or frame.size == 0:
            return
        frame = self._apply_road_mask_to_frame(frame, road_mask)
        self.bg_subtractor.apply(frame, learningRate=1)
        self.background_frames += 1

    def detect(self, frame, vehicle_bboxes=None, road_mask=None):
        """
        Detect road anomalies.

        Args:
            frame: BGR frame from a fixed camera.
            vehicle_bboxes: YOLO vehicle boxes [[x1, y1, x2, y2], ...].
            road_mask: Optional drivable-area mask limiting detection scope.
        """
        if frame is None or frame.size == 0:
            return []

        if self.background_frames < self.warmup_frames:
            self.update_background(frame, road_mask=road_mask)
            startup_mask = self._detect_startup_static_mask(frame, vehicle_bboxes, road_mask)
            return self._track_components(startup_mask)

        if self.background_frames == 0 and self.warmup_frames <= 0:
            self.update_background(frame, road_mask=road_mask)
            fg_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        else:
            fg_mask = self.bg_subtractor.apply(frame, learningRate=self.learning_rate)
            fg_mask = self._normalize_mask(fg_mask, frame.shape[:2])

        road_scope = self._build_road_scope(frame.shape[:2], road_mask)
        if road_scope is not None:
            fg_mask = cv2.bitwise_and(fg_mask, road_scope)

        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
        fg_mask = cv2.bitwise_and(fg_mask, cv2.bitwise_not(vehicle_mask))
        fg_mask = self._cleanup_mask(fg_mask)

        startup_mask = self._detect_startup_static_mask(frame, vehicle_bboxes, road_mask)
        if startup_mask is not None:
            fg_mask = cv2.bitwise_or(fg_mask, startup_mask)

        outlier_mask = self._detect_road_surface_outlier_mask(frame, vehicle_bboxes, road_mask)
        if outlier_mask is not None:
            fg_mask = cv2.bitwise_or(fg_mask, outlier_mask)

        return self._track_components(fg_mask)

    def _detect_startup_static_mask(self, frame, vehicle_bboxes=None, road_mask=None):
        """Find likely objects that already existed before MOG2 background warmup.

        This is a heuristic fallback: it expands/fills the current drivable mask
        and treats large missing holes inside the road surface as static unknown
        objects. A clean baseline or labeled anomaly model is still more reliable.
        """
        if not self.startup_static_check or road_mask is None:
            return None

        road_mask = self._normalize_mask(road_mask, frame.shape[:2])
        if cv2.countNonZero(road_mask) == 0:
            return None

        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (self.startup_static_kernel, self.startup_static_kernel),
        )
        recovered_road = cv2.morphologyEx(road_mask, cv2.MORPH_CLOSE, kernel)
        closed_holes = cv2.subtract(recovered_road, road_mask)
        enclosed_holes = self._find_enclosed_holes(road_mask)
        hole_mask = cv2.bitwise_or(closed_holes, enclosed_holes)
        if self.startup_static_dilate > 1:
            dilate_kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (self.startup_static_dilate, self.startup_static_dilate),
            )
            hole_mask = cv2.dilate(hole_mask, dilate_kernel, iterations=1)

        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
        hole_mask = cv2.bitwise_and(hole_mask, cv2.bitwise_not(vehicle_mask))

        if self.road_roi:
            roi_mask = self._build_road_scope(frame.shape[:2], None)
            if roi_mask is not None:
                hole_mask = cv2.bitwise_and(hole_mask, roi_mask)

        return self._cleanup_mask(hole_mask)

    def _detect_road_surface_outlier_mask(self, frame, vehicle_bboxes=None, road_mask=None):
        """Detect compact objects that do not look like the surrounding road.

        This is not class-specific. It estimates the dominant dark road surface
        from the current frame and keeps compact blobs whose LAB color is far
        from that surface while filtering lane markings and large scenery.
        """
        if not self.road_surface_outlier_check:
            return None

        scope = self._build_road_scope(frame.shape[:2], road_mask)
        if scope is None or cv2.countNonZero(scope) == 0:
            scope = self._build_default_sandbox_road_scope(frame.shape[:2])

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        h, s, v = cv2.split(hsv)

        # Estimate road from broad dark/gray asphalt-like pixels in the active area.
        road_seed = (
            (scope > 0)
            & (v >= 35)
            & (v <= 150)
            & (s <= 110)
        )
        if int(np.count_nonzero(road_seed)) < 500:
            return None

        road_lab = lab[road_seed]
        road_median = np.median(road_lab, axis=0)
        color_dist = np.linalg.norm(lab.astype(np.float32) - road_median.astype(np.float32), axis=2)

        # Remove common lane/road markings: very bright whites and saturated yellows.
        lane_like = ((v > 165) & (s < 80)) | ((h >= 12) & (h <= 40) & (s > 80) & (v > 110))
        candidate = (
            (scope > 0)
            & (color_dist >= self.outlier_color_distance)
            & (v >= 35)
            & (v <= 190)
            & (~lane_like)
        ).astype(np.uint8) * 255

        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
        candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(vehicle_mask))
        candidate = self._cleanup_mask(candidate)
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, close_kernel)

        output = np.zeros_like(candidate)
        contours, _ = cv2.findContours(candidate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < max(self.min_area, self.outlier_min_area) or area > self.outlier_max_area:
                continue

            x, y, w, hgt = cv2.boundingRect(contour)
            aspect_ratio = w / max(1, hgt)
            extent = area / max(1, w * hgt)
            if not (0.25 <= aspect_ratio <= 4.5):
                continue
            if extent < 0.18:
                continue

            cv2.drawContours(output, [contour], -1, 255, -1)

        return self._cleanup_mask(output)

    def _build_default_sandbox_road_scope(self, shape):
        height, width = shape
        scope = np.zeros(shape, dtype=np.uint8)
        polygon = np.array(
            [
                [int(width * 0.08), int(height * 0.46)],
                [int(width * 0.92), int(height * 0.46)],
                [int(width * 0.98), int(height * 0.84)],
                [int(width * 0.02), int(height * 0.84)],
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(scope, [polygon], 255)
        return scope

    def _find_enclosed_holes(self, mask):
        flood = mask.copy()
        height, width = mask.shape[:2]
        flood_mask = np.zeros((height + 2, width + 2), dtype=np.uint8)

        for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            if flood[y, x] == 0:
                cv2.floodFill(flood, flood_mask, (x, y), 255)

        return cv2.bitwise_not(flood)

    def _apply_road_mask_to_frame(self, frame, road_mask):
        if road_mask is None and not self.road_roi:
            return frame

        scope = self._build_road_scope(frame.shape[:2], road_mask)
        if scope is None:
            return frame

        scoped = frame.copy()
        scoped[scope == 0] = 0
        return scoped

    def _build_road_scope(self, shape, road_mask=None):
        scope = None
        if road_mask is not None:
            scope = self._normalize_mask(road_mask, shape)

        if self.road_roi:
            roi_mask = np.zeros(shape, dtype=np.uint8)
            cv2.fillPoly(roi_mask, [np.array(self.road_roi, dtype=np.int32)], 255)
            scope = roi_mask if scope is None else cv2.bitwise_and(scope, roi_mask)

        return scope

    def _track_components(self, mask):
        if mask is None:
            return self._age_unmatched_tracks(set())

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        current_anomalies = []
        matched_ids = set()

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            bbox = [x, y, x + w, y + h]
            center = [x + w // 2, y + h // 2]
            current_anomalies.append(
                self._match_or_create_anomaly(center, bbox, int(area), matched_ids)
            )

        current_ids = {a["anomaly_id"] for a in current_anomalies}
        self._age_unmatched_tracks(current_ids)

        return current_anomalies

    def _age_unmatched_tracks(self, current_ids):
        for anomaly_id in list(self.tracked_anomalies.keys()):
            if anomaly_id not in current_ids:
                anomaly_info = self.tracked_anomalies[anomaly_id]
                anomaly_info["missed_frames"] = anomaly_info.get("missed_frames", 0) + 1
                if anomaly_info["missed_frames"] > self.max_missed_frames:
                    del self.tracked_anomalies[anomaly_id]
        return []

    def _match_or_create_anomaly(self, center, bbox, area, matched_ids=None):
        if matched_ids is None:
            matched_ids = set()
        best_id = None
        best_dist = None

        for anomaly_id, anomaly_info in self.tracked_anomalies.items():
            if anomaly_id in matched_ids:
                continue
            prev_center = anomaly_info["center"]
            dist = np.sqrt((center[0] - prev_center[0]) ** 2 + (center[1] - prev_center[1]) ** 2)
            if dist < self.match_distance and (best_dist is None or dist < best_dist):
                best_id = anomaly_id
                best_dist = dist

        if best_id is not None:
            anomaly_info = self.tracked_anomalies[best_id]
            anomaly_info["static_frames"] += 1
            anomaly_info["missed_frames"] = 0
            anomaly_info["center"] = center
            anomaly_info["bbox"] = bbox
            anomaly_info["area"] = area
            anomaly_info["status"] = (
                "warning"
                if anomaly_info["static_frames"] >= self.static_frames_threshold
                else "normal"
            )
            matched_ids.add(best_id)
            return self._format_anomaly(best_id, anomaly_info)

        anomaly_id = self.anomaly_id_counter
        self.anomaly_id_counter += 1
        self.tracked_anomalies[anomaly_id] = {
            "center": center,
            "bbox": bbox,
            "area": area,
            "static_frames": 1,
            "missed_frames": 0,
            "status": "normal",
        }
        matched_ids.add(anomaly_id)
        return self._format_anomaly(anomaly_id, self.tracked_anomalies[anomaly_id])

    def _format_anomaly(self, anomaly_id, anomaly_info):
        return {
            "anomaly_id": anomaly_id,
            "bbox": anomaly_info["bbox"],
            "center": anomaly_info["center"],
            "area": anomaly_info["area"],
            "static_frames": anomaly_info["static_frames"],
            "missed_frames": anomaly_info.get("missed_frames", 0),
            "status": anomaly_info["status"],
        }

    def _build_vehicle_mask(self, vehicle_bboxes, frame_shape):
        mask = np.zeros(frame_shape[:2], dtype=np.uint8)
        for bbox in vehicle_bboxes or []:
            x1, y1, x2, y2 = self._clip_bbox(bbox, frame_shape)
            x1 = max(0, x1 - self.vehicle_mask_padding)
            y1 = max(0, y1 - self.vehicle_mask_padding)
            x2 = min(frame_shape[1], x2 + self.vehicle_mask_padding)
            y2 = min(frame_shape[0], y2 + self.vehicle_mask_padding)
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
        return mask

    def _cleanup_mask(self, mask):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    def _clip_bbox(self, bbox, frame_shape):
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = map(int, bbox)
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(0, min(width, x2))
        y2 = max(0, min(height, y2))
        return x1, y1, x2, y2

    def _normalize_mask(self, mask, shape=None):
        if shape and mask.shape[:2] != shape:
            mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        return np.where(mask > 0, 255, 0).astype(np.uint8)

    def reset(self):
        """Reset background model and temporal tracks."""
        self.bg_subtractor = self._create_subtractor()
        self.background_frames = 0
        self.tracked_anomalies = {}
        self.anomaly_id_counter = 0


if __name__ == "__main__":
    detector = AnomalyDetector(warmup_frames=3, static_frames_threshold=3, min_area=300)
    bg = np.ones((480, 640, 3), dtype=np.uint8) * 100
    road_mask = np.zeros((480, 640), dtype=np.uint8)
    cv2.rectangle(road_mask, (80, 120), (560, 420), 255, -1)

    for _ in range(3):
        assert detector.detect(bg, road_mask=road_mask) == []

    frame = bg.copy()
    cv2.rectangle(frame, (220, 220), (280, 280), (30, 30, 30), -1)
    events = []
    for _ in range(4):
        events = detector.detect(frame, road_mask=road_mask, vehicle_bboxes=[])

    assert events and events[0]["status"] == "warning"
    first_id = events[0]["anomaly_id"]
    assert detector.detect(bg, road_mask=road_mask, vehicle_bboxes=[]) == []
    recovered_events = detector.detect(frame, road_mask=road_mask, vehicle_bboxes=[])
    assert recovered_events and recovered_events[0]["anomaly_id"] == first_id

    startup_detector = AnomalyDetector(warmup_frames=30, static_frames_threshold=3, min_area=300)
    startup_road_mask = road_mask.copy()
    cv2.rectangle(startup_road_mask, (220, 220), (280, 280), 0, -1)
    startup_events = []
    for _ in range(4):
        startup_events = startup_detector.detect(bg, road_mask=startup_road_mask, vehicle_bboxes=[])

    assert startup_events and startup_events[0]["status"] == "warning"
    print("MOG2 road anomaly detector smoke test passed")
