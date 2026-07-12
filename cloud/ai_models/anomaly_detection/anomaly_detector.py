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
        max_area=None,
        max_area_ratio=0.08,
        static_frames_threshold=15,
        match_distance=50,
        max_missed_frames=3,
        vehicle_mask_padding=16,
        vehicle_mask_padding_ratio=0.10,
        road_roi=None,
        road_scope_erode=6,
        warmup_frames=30,
        learning_rate=0,
        background_learning_rate=-1,
        startup_static_check=True,
        startup_static_kernel=35,
        startup_static_dilate=3,
        road_surface_outlier_check=False,
        outlier_min_area=250,
        outlier_color_distance=28,
        outlier_max_area=30000,
        min_road_overlap=0.65,
        min_component_extent=0.16,
        component_merge_kernel=11,
        max_candidates=3,
        max_foreground_ratio=0.16,
        filter_lane_markings=True,
        use_default_road_scope=False,
        max_background_vehicle_ratio=0.18,
        **_legacy_kwargs,
    ):
        """
        Args:
            history: Number of frames used by the MOG2 background model.
            var_threshold: MOG2 variance threshold; higher is less sensitive.
            detect_shadows: Whether MOG2 keeps shadow labels.
            min_area: Minimum connected component area to keep.
            max_area: Maximum connected component area to keep; None uses ratio.
            max_area_ratio: Max component area as a fraction of frame area.
            static_frames_threshold: Frames required before warning.
            match_distance: Cross-frame center matching distance.
            max_missed_frames: Frames a tracked anomaly can disappear before reset.
            vehicle_mask_padding: Padding around YOLO vehicle boxes.
            vehicle_mask_padding_ratio: Additional padding relative to vehicle size.
            road_roi: Optional polygon limiting the active road area.
            road_scope_erode: Pixels removed from the road-scope boundary.
            warmup_frames: Initial frames used to build background if not fed manually.
            learning_rate: Detection-time background update rate. Use 0 to freeze.
            background_learning_rate: MOG2 rate used during explicit calibration.
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
            min_road_overlap: Minimum component-mask overlap with road scope.
            min_component_extent: Minimum contour-to-bounding-box fill ratio.
            component_merge_kernel: Closing kernel used to join object fragments.
            max_candidates: Maximum simultaneous candidates kept per frame.
            max_foreground_ratio: Treat frames with broad road changes as noisy and
                keep only the strongest candidate.
            filter_lane_markings: Remove bright lane-marking-like components.
            use_default_road_scope: Use a sandbox fallback ROI when no mask/ROI is supplied.
            max_background_vehicle_ratio: Skip background learning when vehicle masks
                cover too much active road area.
        """
        self.history = history
        self.var_threshold = var_threshold
        self.detect_shadows = detect_shadows
        self.min_area = min_area
        self.max_area = max_area
        self.max_area_ratio = max_area_ratio
        self.static_frames_threshold = static_frames_threshold
        self.match_distance = match_distance
        self.max_missed_frames = max_missed_frames
        self.vehicle_mask_padding = vehicle_mask_padding
        self.vehicle_mask_padding_ratio = max(0.0, float(vehicle_mask_padding_ratio))
        self.road_roi = road_roi
        self.road_scope_erode = max(0, int(road_scope_erode))
        self.warmup_frames = warmup_frames
        self.learning_rate = learning_rate
        self.background_learning_rate = float(background_learning_rate)
        self.startup_static_check = startup_static_check
        self.startup_static_kernel = startup_static_kernel if startup_static_kernel % 2 else startup_static_kernel + 1
        self.startup_static_dilate = max(0, int(startup_static_dilate))
        self.road_surface_outlier_check = road_surface_outlier_check
        self.outlier_min_area = outlier_min_area
        self.outlier_color_distance = outlier_color_distance
        self.outlier_max_area = outlier_max_area
        self.min_road_overlap = min_road_overlap
        self.min_component_extent = max(0.0, float(min_component_extent))
        self.component_merge_kernel = max(0, int(component_merge_kernel))
        self.max_candidates = max(0, int(max_candidates))
        self.max_foreground_ratio = max(0.0, float(max_foreground_ratio))
        self.filter_lane_markings = filter_lane_markings
        self.use_default_road_scope = use_default_road_scope
        self.max_background_vehicle_ratio = max_background_vehicle_ratio

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

    def update_background(self, frame=None, road_mask=None, vehicle_bboxes=None):
        """Feed a clean static-camera frame into the MOG2 background model."""
        if frame is None or frame.size == 0:
            return False
        scope = self._build_road_scope(frame.shape[:2], road_mask)
        frame = self._apply_road_mask_to_frame(frame, road_mask)
        if vehicle_bboxes:
            vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
            if self._vehicle_mask_too_large(vehicle_mask, scope):
                return False
            frame = frame.copy()
            fill_color = self._estimate_road_fill_color(frame, scope, vehicle_mask)
            frame[vehicle_mask > 0] = fill_color
        self.bg_subtractor.apply(frame, learningRate=self.background_learning_rate)
        self.background_frames += 1
        return True

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
            road_scope = self._build_road_scope(frame.shape[:2], road_mask)
            if startup_mask is not None:
                startup_mask = self._remove_lane_markings(startup_mask, frame)
            return self._track_components(startup_mask, frame=frame, road_scope=road_scope)

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

        fg_mask = self._remove_lane_markings(fg_mask, frame)
        if road_scope is not None:
            fg_mask = cv2.bitwise_and(fg_mask, road_scope)

        noisy_frame = self._foreground_too_large(fg_mask, road_scope)
        fg_mask = self._merge_component_fragments(fg_mask)

        return self._track_components(
            fg_mask,
            frame=frame,
            road_scope=road_scope,
            candidate_limit=1 if noisy_frame else None,
        )

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

    def _vehicle_mask_too_large(self, vehicle_mask, scope):
        if self.max_background_vehicle_ratio <= 0:
            return False

        if scope is not None and cv2.countNonZero(scope) > 0:
            active_pixels = cv2.countNonZero(scope)
            masked_pixels = cv2.countNonZero(cv2.bitwise_and(vehicle_mask, scope))
        else:
            active_pixels = vehicle_mask.shape[0] * vehicle_mask.shape[1]
            masked_pixels = cv2.countNonZero(vehicle_mask)

        return active_pixels > 0 and (masked_pixels / float(active_pixels)) > self.max_background_vehicle_ratio

    def _estimate_road_fill_color(self, frame, scope, vehicle_mask):
        sample_mask = cv2.bitwise_not(vehicle_mask)
        if scope is not None:
            sample_mask = cv2.bitwise_and(sample_mask, scope)

        if cv2.countNonZero(sample_mask) < 100:
            return np.array([0, 0, 0], dtype=np.uint8)

        pixels = frame[sample_mask > 0]
        return np.median(pixels, axis=0).astype(np.uint8)

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

        if scope is None and self.use_default_road_scope:
            scope = self._build_default_sandbox_road_scope(shape)

        if scope is not None and self.road_scope_erode > 0:
            size = self.road_scope_erode * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
            eroded = cv2.erode(scope, kernel, iterations=1)
            if cv2.countNonZero(eroded) > 0:
                scope = eroded

        return scope

    def _track_components(self, mask, frame=None, road_scope=None, candidate_limit=None):
        if mask is None:
            return self._age_unmatched_tracks(set())

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        current_anomalies = []
        matched_ids = set()
        candidates = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue
            if area > self._max_component_area(mask.shape):
                continue

            x, y, w, h = cv2.boundingRect(contour)
            extent = area / float(max(1, w * h))
            if extent < self.min_component_extent:
                continue
            if self._is_low_road_overlap(contour, mask.shape, road_scope):
                continue
            if frame is not None and self._is_lane_marking_like(frame, contour, (x, y, w, h)):
                continue

            bbox = [x, y, x + w, y + h]
            center = [x + w // 2, y + h // 2]
            candidates.append((area, center, bbox))

        candidates.sort(key=lambda item: item[0], reverse=True)
        limit = self.max_candidates if candidate_limit is None else max(0, int(candidate_limit))
        if limit > 0:
            candidates = candidates[:limit]

        for area, center, bbox in candidates:
            current_anomalies.append(
                self._match_or_create_anomaly(center, bbox, int(area), matched_ids)
            )

        current_ids = {a["anomaly_id"] for a in current_anomalies}
        self._age_unmatched_tracks(current_ids)

        return current_anomalies

    def _remove_lane_markings(self, mask, frame):
        if not self.filter_lane_markings or mask is None:
            return mask

        lane_mask = self._build_lane_marking_mask(frame)
        if cv2.countNonZero(lane_mask) == 0:
            return mask

        lane_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        lane_mask = cv2.dilate(lane_mask, lane_kernel, iterations=1)
        return cv2.bitwise_and(mask, cv2.bitwise_not(lane_mask))

    def _build_lane_marking_mask(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        white_markings = (v > 150) & (s < 95)
        yellow_markings = (h >= 12) & (h <= 42) & (s > 70) & (v > 115)
        return (white_markings | yellow_markings).astype(np.uint8) * 255

    def _is_low_road_overlap(self, contour, shape, road_scope):
        if road_scope is None or self.min_road_overlap <= 0:
            return False

        component_mask = np.zeros(shape, dtype=np.uint8)
        cv2.drawContours(component_mask, [contour], -1, 255, -1)
        component_area = cv2.countNonZero(component_mask)
        if component_area == 0:
            return True

        road_hits = cv2.countNonZero(cv2.bitwise_and(component_mask, road_scope))
        return (road_hits / float(component_area)) < self.min_road_overlap

    def _is_lane_marking_like(self, frame, contour, rect):
        if not self.filter_lane_markings:
            return False

        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return True

        aspect_ratio = max(w / h, h / w)
        area = cv2.contourArea(contour)
        extent = area / max(1, w * h)
        if aspect_ratio < 2.6 or extent < 0.08:
            return False

        component_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.drawContours(component_mask, [contour], -1, 255, -1)
        lane_mask = self._build_lane_marking_mask(frame)
        component_area = cv2.countNonZero(component_mask)
        if component_area == 0:
            return True

        lane_hits = cv2.countNonZero(cv2.bitwise_and(component_mask, lane_mask))
        return (lane_hits / float(component_area)) >= 0.45

    def _age_unmatched_tracks(self, current_ids):
        for anomaly_id in list(self.tracked_anomalies.keys()):
            if anomaly_id not in current_ids:
                anomaly_info = self.tracked_anomalies[anomaly_id]
                anomaly_info["missed_frames"] = anomaly_info.get("missed_frames", 0) + 1
                if anomaly_info["missed_frames"] > self.max_missed_frames:
                    del self.tracked_anomalies[anomaly_id]
        return []

    def _max_component_area(self, shape):
        if self.max_area is not None:
            return self.max_area
        return max(self.min_area, int(shape[0] * shape[1] * self.max_area_ratio))

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
            adaptive_padding = int(round(max(x2 - x1, y2 - y1) * self.vehicle_mask_padding_ratio))
            padding = max(self.vehicle_mask_padding, adaptive_padding)
            x1 = max(0, x1 - padding)
            y1 = max(0, y1 - padding)
            x2 = min(frame_shape[1], x2 + padding)
            y2 = min(frame_shape[0], y2 + padding)
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
        return mask

    def _foreground_too_large(self, mask, road_scope):
        if mask is None or self.max_foreground_ratio <= 0:
            return False

        active_mask = road_scope
        if active_mask is None or cv2.countNonZero(active_mask) == 0:
            active_pixels = mask.shape[0] * mask.shape[1]
            foreground_pixels = cv2.countNonZero(mask)
        else:
            active_pixels = cv2.countNonZero(active_mask)
            foreground_pixels = cv2.countNonZero(cv2.bitwise_and(mask, active_mask))

        return active_pixels > 0 and foreground_pixels / float(active_pixels) > self.max_foreground_ratio

    def _merge_component_fragments(self, mask):
        if mask is None or self.component_merge_kernel <= 1:
            return mask

        size = self.component_merge_kernel
        if size % 2 == 0:
            size += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

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
