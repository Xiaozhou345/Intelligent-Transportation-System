"""Fixed-camera road anomaly detector using DINOv2 reference features."""

from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
import time
from typing import Callable

import cv2
import numpy as np
import torch
from torch.nn import functional as torch_functional

from .anomaly_detector import AnomalyDetector


class DinoReferenceDetector(AnomalyDetector):
    """Detect objects that differ from a calibrated fixed-camera road view."""

    def __init__(
        self,
        model_name="dinov2_vits14_reg",
        image_size=518,
        local_radius=1,
        heat_threshold=0.14,
        pixel_threshold=0.14,
        threshold_quantile=0.99,
        threshold_margin=1.25,
        top_fraction=0.005,
        camera_change_ratio=0.30,
        camera_change_frames=3,
        allow_background_vehicles=True,
        min_background_valid_ratio=0.10,
        min_thin_side=18,
        max_thin_aspect=4.0,
        feature_extractor: Callable | None = None,
        model=None,
        device=None,
        **kwargs,
    ):
        kwargs.setdefault("filter_lane_markings", False)
        kwargs.setdefault("announce", False)
        kwargs.setdefault("max_candidates", 1)
        super().__init__(**kwargs)

        self.model_name = model_name
        self.image_size = max(14, int(image_size))
        if self.image_size % 14:
            self.image_size -= self.image_size % 14
        self.local_radius = max(0, min(3, int(local_radius)))
        self.base_heat_threshold = float(heat_threshold)
        self.base_pixel_threshold = float(pixel_threshold)
        self.heat_threshold = self.base_heat_threshold
        self.pixel_threshold = self.base_pixel_threshold
        self.threshold_quantile = min(0.999, max(0.5, float(threshold_quantile)))
        self.threshold_margin = max(1.0, float(threshold_margin))
        self.top_fraction = min(0.25, max(0.0001, float(top_fraction)))
        self.camera_change_ratio = min(0.95, max(0.05, float(camera_change_ratio)))
        self.camera_change_frames = max(1, int(camera_change_frames))
        # Kept for compatibility with older callers. DINOv2 calibration now
        # always masks vehicle patches instead of rejecting the whole frame.
        self.allow_background_vehicles = bool(allow_background_vehicles)
        self.min_background_valid_ratio = min(
            0.95,
            max(0.01, float(min_background_valid_ratio)),
        )
        self.min_thin_side = max(0, int(min_thin_side))
        self.max_thin_aspect = max(1.0, float(max_thin_aspect))

        self.feature_extractor = feature_extractor
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model = model
        self.reference_sum = None
        self.reference_count = None
        self.normal_heat_scores = []
        self.normal_pixel_scores = []
        self.camera_change_streak = 0
        self.needs_recalibration = False
        self.last_heat_score = 0.0
        self.last_foreground_ratio = 0.0
        self.last_background_vehicle_ratio = 0.0
        self.last_background_valid_ratio = 0.0
        self.last_background_skip_reason = None
        self.last_detection_reason = "not_calibrated"
        self.last_candidate_count = 0
        self.last_warning_count = 0
        self.last_vehicle_mask_ratio = 0.0
        self.model_warmed_up = self.feature_extractor is not None
        self.model_warmup_ms = 0.0

        if self.feature_extractor is None and self.model is None:
            self.model = self._load_model()
        if self.model is not None:
            self.model.eval().to(self.device)
            if os.getenv("ITS_WARMUP_MODELS", "true").lower() == "true":
                self.warmup()

        print(
            "道路异常检测器初始化完成：DINOv2正常模板 + YOLO车辆掩膜 "
            "+ 道路区域约束 + 时序判定"
        )

    def _load_model(self):
        repo_root = Path(__file__).resolve().parents[3]
        default_cache = repo_root / ".tools" / "model-cache" / "torch"
        os.environ.setdefault(
            "TORCH_HOME",
            os.getenv("ITS_TORCH_HOME", str(default_cache)),
        )
        return torch.hub.load(
            "facebookresearch/dinov2",
            self.model_name,
            trust_repo=True,
            force_reload=False,
        )

    def warmup(self):
        """Run first-use kernels before interactive background calibration."""
        started_at = time.perf_counter()
        warmup_width = max(32, int(os.getenv("ITS_WARMUP_WIDTH", "1280")))
        warmup_height = max(32, int(os.getenv("ITS_WARMUP_HEIGHT", "720")))
        dummy = np.zeros((warmup_height, warmup_width, 3), dtype=np.uint8)
        try:
            features = self._extract_features(dummy)
            self._local_cosine_distance(features, features)
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            self.model_warmup_ms = (time.perf_counter() - started_at) * 1000
            self.model_warmed_up = True
            print(
                f"DINOv2异常检测预热完成: {self.model_warmup_ms:.1f}ms "
                f"(设备: {self.device.type}, 输入: {self.image_size}x{self.image_size})"
            )
            return self.model_warmup_ms
        except Exception as exc:
            self.model_warmed_up = False
            self.model_warmup_ms = 0.0
            print(f"DINOv2异常检测预热失败，将在首帧重试: {exc}")
            return None

    def _extract_features(self, frame):
        if self.feature_extractor is not None:
            features = self.feature_extractor(frame)
            if isinstance(features, np.ndarray):
                features = torch.from_numpy(features)
            if features.ndim == 3:
                features = features.unsqueeze(0)
            return torch_functional.normalize(
                features.float().to(self.device),
                dim=1,
            )

        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
        tensor = tensor.to(self.device, dtype=torch.float32).div_(255.0)
        tensor = torch_functional.interpolate(
            tensor,
            size=(self.image_size, self.image_size),
            mode="bilinear",
            align_corners=False,
        )
        mean = tensor.new_tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
        std = tensor.new_tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
        tensor = (tensor - mean) / std

        autocast_context = (
            torch.autocast(device_type="cuda", dtype=torch.float16)
            if self.device.type == "cuda"
            else nullcontext()
        )
        with torch.inference_mode(), autocast_context:
            features = self.model.get_intermediate_layers(
                tensor,
                n=1,
                reshape=True,
                norm=True,
            )[0]
        return torch_functional.normalize(features.float(), dim=1)

    def _feature_masks(self, frame_shape, feature_shape, road_mask, vehicle_bboxes):
        road_scope = self._build_road_scope(frame_shape[:2], road_mask)
        if road_scope is None:
            road_scope = np.full(frame_shape[:2], 255, dtype=np.uint8)
        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame_shape)
        valid = cv2.bitwise_and(road_scope, cv2.bitwise_not(vehicle_mask))
        feature_height, feature_width = feature_shape

        def resize_mask(mask):
            resized = cv2.resize(
                mask,
                (feature_width, feature_height),
                interpolation=cv2.INTER_AREA,
            )
            resized = (resized >= 192).astype(np.float32)
            return torch.from_numpy(resized).to(self.device).view(
                1,
                1,
                feature_height,
                feature_width,
            )

        return resize_mask(valid), resize_mask(road_scope)

    def _reference_features(self):
        if self.reference_sum is None or self.reference_count is None:
            return None
        reference = self.reference_sum / self.reference_count.clamp_min(1.0)
        return torch_functional.normalize(reference, dim=1)

    def _local_cosine_distance(self, reference, candidate):
        batch, channels, height, width = reference.shape
        kernel_size = self.local_radius * 2 + 1
        neighbors = torch_functional.unfold(
            reference,
            kernel_size=kernel_size,
            padding=self.local_radius,
        )
        neighbors = neighbors.reshape(
            batch,
            channels,
            kernel_size * kernel_size,
            height * width,
        )
        candidate = candidate.reshape(batch, channels, height * width).unsqueeze(2)
        similarity = (neighbors * candidate).sum(dim=1)
        return (1.0 - similarity.max(dim=1).values).clamp(min=0.0).reshape(
            batch,
            1,
            height,
            width,
        )

    def _active_distance_values(self, distance, validity):
        values = distance[validity > 0.5]
        return values.detach().float().cpu().numpy()

    def _distance_scores(self, values):
        if values.size == 0:
            return 0.0, 0.0
        top_count = max(1, int(round(values.size * self.top_fraction)))
        hottest = np.partition(values, values.size - top_count)[-top_count:]
        heat_score = float(np.mean(hottest))
        pixel_score = float(np.quantile(values, 0.995))
        return heat_score, pixel_score

    def _refresh_thresholds(self):
        if self.normal_heat_scores:
            calibrated = np.quantile(
                self.normal_heat_scores,
                self.threshold_quantile,
            )
            self.heat_threshold = max(
                self.base_heat_threshold,
                float(calibrated) * self.threshold_margin,
            )
        if self.normal_pixel_scores:
            calibrated = np.quantile(
                self.normal_pixel_scores,
                self.threshold_quantile,
            )
            self.pixel_threshold = max(
                self.base_pixel_threshold,
                float(calibrated) * self.threshold_margin,
            )

    def update_background(self, frame=None, road_mask=None, vehicle_bboxes=None):
        self.last_background_skip_reason = None
        self.last_background_vehicle_ratio = 0.0
        self.last_background_valid_ratio = 0.0
        if frame is None or frame.size == 0:
            self.last_background_skip_reason = "empty_frame"
            return False

        road_scope = self._build_road_scope(frame.shape[:2], road_mask)
        if road_scope is None:
            road_scope = np.full(frame.shape[:2], 255, dtype=np.uint8)
        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
        self.last_background_vehicle_ratio = self._vehicle_mask_ratio(
            vehicle_mask,
            road_scope,
        )
        features = self._extract_features(frame)
        validity, road_validity = self._feature_masks(
            frame.shape,
            features.shape[-2:],
            road_mask,
            vehicle_bboxes,
        )
        road_patch_count = float(road_validity.sum().item())
        visible_patch_count = float(validity.sum().item())
        self.last_background_valid_ratio = (
            visible_patch_count / road_patch_count
            if road_patch_count > 0
            else 0.0
        )
        if (
            road_patch_count < 4
            or self.last_background_valid_ratio < self.min_background_valid_ratio
        ):
            self.last_background_skip_reason = "insufficient_visible_road"
            return False

        reference = self._reference_features()
        if reference is not None:
            distance = self._local_cosine_distance(reference, features)
            heat_score, pixel_score = self._distance_scores(
                self._active_distance_values(distance, validity)
            )
            self.normal_heat_scores.append(heat_score)
            self.normal_pixel_scores.append(pixel_score)
            self.normal_heat_scores = self.normal_heat_scores[-100:]
            self.normal_pixel_scores = self.normal_pixel_scores[-100:]

        if self.reference_sum is None:
            self.reference_sum = torch.zeros_like(features)
            self.reference_count = torch.zeros_like(validity)
        self.reference_sum += features * validity
        self.reference_count += validity
        self.background_frames += 1
        self._refresh_thresholds()
        return True

    def detect(self, frame, vehicle_bboxes=None, road_mask=None):
        if frame is None or frame.size == 0:
            self.last_detection_reason = "empty_frame"
            self.last_candidate_count = 0
            self.last_warning_count = 0
            return []
        reference = self._reference_features()
        if reference is None:
            self.last_detection_reason = "not_calibrated"
            self.last_candidate_count = 0
            self.last_warning_count = 0
            return []

        features = self._extract_features(frame)
        distance = self._local_cosine_distance(reference, features)
        distance = torch_functional.interpolate(
            distance,
            size=frame.shape[:2],
            mode="bilinear",
            align_corners=False,
        )[0, 0]
        distance_np = distance.detach().float().cpu().numpy()

        road_scope = self._build_road_scope(frame.shape[:2], road_mask)
        if road_scope is None:
            road_scope = np.full(frame.shape[:2], 255, dtype=np.uint8)
        reference_valid = (self.reference_count > 0.5).float()
        reference_valid = torch_functional.interpolate(
            reference_valid,
            size=frame.shape[:2],
            mode="nearest",
        )[0, 0].detach().cpu().numpy()
        road_scope = cv2.bitwise_and(
            road_scope,
            np.where(reference_valid > 0.5, 255, 0).astype(np.uint8),
        )
        vehicle_mask = self._build_vehicle_mask(vehicle_bboxes, frame.shape)
        self.last_vehicle_mask_ratio = self._vehicle_mask_ratio(
            vehicle_mask,
            road_scope,
        )
        active_scope = cv2.bitwise_and(road_scope, cv2.bitwise_not(vehicle_mask))
        active_values = distance_np[active_scope > 0]
        self.last_heat_score, _ = self._distance_scores(active_values)

        foreground = np.zeros(frame.shape[:2], dtype=np.uint8)
        foreground[(distance_np >= self.pixel_threshold) & (active_scope > 0)] = 255
        foreground = self._cleanup_mask(foreground)
        foreground = self._merge_component_fragments(foreground)
        foreground = self._remove_thin_artifacts(foreground)

        active_pixels = max(1, cv2.countNonZero(active_scope))
        foreground_pixels = cv2.countNonZero(foreground)
        self.last_foreground_ratio = foreground_pixels / float(active_pixels)
        if self.last_foreground_ratio >= self.camera_change_ratio:
            self.camera_change_streak += 1
            if self.camera_change_streak >= self.camera_change_frames:
                self.needs_recalibration = True
            self.last_detection_reason = "camera_change"
            self.last_candidate_count = 0
            self.last_warning_count = 0
            return self._age_unmatched_tracks(set())

        self.camera_change_streak = 0
        if self.last_heat_score < self.heat_threshold:
            self.last_detection_reason = "below_heat_threshold"
            self.last_candidate_count = 0
            self.last_warning_count = 0
            return self._age_unmatched_tracks(set())

        noisy_frame = self._foreground_too_large(foreground, active_scope)
        results = self._track_components(
            foreground,
            frame=None,
            road_scope=active_scope,
            candidate_limit=1 if noisy_frame else None,
        )
        self.last_candidate_count = len(results)
        self.last_warning_count = sum(
            result.get("status") == "warning" for result in results
        )
        if self.last_warning_count:
            self.last_detection_reason = "warning"
        elif self.last_candidate_count:
            self.last_detection_reason = "candidate_tracking"
        else:
            self.last_detection_reason = "no_component"
        return results

    def _remove_thin_artifacts(self, mask):
        if self.min_thin_side <= 0:
            return mask
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filtered = np.zeros_like(mask)
        for contour in contours:
            _, _, width, height = cv2.boundingRect(contour)
            short_side = max(1, min(width, height))
            aspect = max(width, height) / float(short_side)
            if short_side < self.min_thin_side and aspect >= self.max_thin_aspect:
                continue
            cv2.drawContours(filtered, [contour], -1, 255, -1)
        return filtered

    def reset(self):
        super().reset()
        self.reference_sum = None
        self.reference_count = None
        self.normal_heat_scores = []
        self.normal_pixel_scores = []
        self.heat_threshold = self.base_heat_threshold
        self.pixel_threshold = self.base_pixel_threshold
        self.camera_change_streak = 0
        self.needs_recalibration = False
        self.last_heat_score = 0.0
        self.last_foreground_ratio = 0.0
        self.last_background_vehicle_ratio = 0.0
        self.last_background_valid_ratio = 0.0
        self.last_background_skip_reason = None
        self.last_detection_reason = "not_calibrated"
        self.last_candidate_count = 0
        self.last_warning_count = 0
        self.last_vehicle_mask_ratio = 0.0
