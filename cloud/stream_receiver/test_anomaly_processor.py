"""
Smoke tests for the road anomaly processor.
"""
import os
import sys
import unittest

import cv2
import numpy as np


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

AI_MODELS_DIR = os.path.join(CURRENT_DIR, "..", "ai_models")
if AI_MODELS_DIR not in sys.path:
    sys.path.append(AI_MODELS_DIR)

from anomaly_processor import RoadAnomalyProcessor
from anomaly_detection.anomaly_detector import AnomalyDetector
from anomaly_detection.dino_reference_detector import DinoReferenceDetector
from video_processor import VideoProcessor


class _BackgroundCounter:
    def __init__(self, background_frames):
        self.background_frames = background_frames


class VideoProcessorAnomalyModeTest(unittest.TestCase):
    def build_processor(self, detector_frames, state_frames):
        processor = VideoProcessor.__new__(VideoProcessor)
        processor.anomaly_processor = _BackgroundCounter(detector_frames)
        processor.runtime_defaults = {
            "active_scene": "road_anomaly",
            "anomaly_mode": "background_learning",
            "anomaly_min_background_frames": 6,
        }
        processor.runtime_state = {
            "mobile_001": {
                "active_scene": "road_anomaly",
                "anomaly_mode": "background_learning",
                "anomaly_background_frames": state_frames,
            }
        }
        return processor

    def test_detection_start_uses_detector_background_count(self):
        processor = self.build_processor(detector_frames=6, state_frames=0)

        result = processor.start_anomaly_detection(device_id="mobile_001")

        self.assertEqual("success", result["status"])
        self.assertEqual("detecting", result["mode"])
        self.assertEqual(
            6,
            processor.runtime_state["mobile_001"]["anomaly_background_frames"],
        )

    def test_detection_start_rejects_stale_high_ui_count(self):
        processor = self.build_processor(detector_frames=2, state_frames=20)

        result = processor.start_anomaly_detection(device_id="mobile_001")

        self.assertEqual("error", result["status"])
        self.assertEqual("background_learning", result["mode"])
        self.assertEqual(
            2,
            processor.runtime_state["mobile_001"]["anomaly_background_frames"],
        )


class RoadAnomalyProcessorTest(unittest.TestCase):
    def setUp(self):
        self.background = np.ones((480, 640, 3), dtype=np.uint8) * 100
        self.clean_road = np.zeros((480, 640), dtype=np.uint8)
        cv2.rectangle(self.clean_road, (40, 80), (600, 430), 255, -1)

    def build_processor(self, **detector_kwargs):
        detector = AnomalyDetector(
            warmup_frames=0,
            static_frames_threshold=3,
            min_area=300,
            use_default_road_scope=False,
            **detector_kwargs,
        )
        processor = RoadAnomalyProcessor(
            detector=detector,
            lane_regions={
                "lane_1": [[0, 0], [320, 0], [320, 480], [0, 480]],
                "lane_2": [[320, 0], [640, 0], [640, 480], [320, 480]],
            },
        )
        for _ in range(8):
            self.assertTrue(processor.update_background(self.background, road_mask=self.clean_road))
        return processor

    def test_stable_road_object_emits_once(self):
        processor = self.build_processor()

        frame = self.background.copy()
        cv2.rectangle(frame, (120, 220), (180, 280), (30, 30, 30), -1)

        emitted_events = []
        for _ in range(8):
            emitted_events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=frame,
                vehicle_bboxes=[],
                road_mask=self.clean_road,
            ))

        self.assertEqual(1, len(emitted_events))
        event = emitted_events[-1]
        self.assertEqual("road_anomaly", event["event_type"])
        self.assertEqual("warning", event["status"])
        self.assertEqual("lane_1", event["affected_lane"])
        self.assertGreaterEqual(event["duration_frames"], 3)
        self.assertEqual(1, len(processor.get_current_results()))

    def test_vehicle_mask_does_not_become_anomaly(self):
        processor = self.build_processor()

        vehicle_frame = self.background.copy()
        cv2.rectangle(vehicle_frame, (360, 200), (430, 300), (30, 30, 30), -1)
        events = []
        for _ in range(6):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=vehicle_frame,
                vehicle_bboxes=[[360, 200, 430, 300]],
                road_mask=self.clean_road,
            ))

        self.assertEqual([], events)

    def test_adaptive_vehicle_padding_removes_edge_fragments(self):
        processor = self.build_processor()

        vehicle_frame = self.background.copy()
        cv2.rectangle(vehicle_frame, (260, 180), (400, 300), (30, 30, 30), -1)
        # A narrow shadow/body edge falls outside the raw detector box. Fixed
        # six-pixel padding used to expose it as a separate road anomaly.
        cv2.rectangle(vehicle_frame, (244, 304), (416, 318), (65, 65, 65), -1)

        events = []
        for _ in range(8):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=vehicle_frame,
                vehicle_bboxes=[[260, 180, 400, 300]],
                road_mask=self.clean_road,
            ))

        self.assertEqual([], events)
        self.assertEqual([], processor.get_current_results())

    def test_calibrated_road_texture_is_not_a_single_frame_outlier(self):
        textured_road = self.background.copy()
        cv2.rectangle(textured_road, (120, 220), (190, 290), (50, 50, 50), -1)
        detector = AnomalyDetector(
            warmup_frames=0,
            static_frames_threshold=3,
            min_area=300,
            use_default_road_scope=False,
        )
        processor = RoadAnomalyProcessor(detector=detector)
        for _ in range(8):
            self.assertTrue(processor.update_background(textured_road, road_mask=self.clean_road))

        events = []
        for _ in range(6):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=textured_road,
                vehicle_bboxes=[],
                road_mask=self.clean_road,
            ))

        self.assertEqual([], events)
        self.assertEqual([], processor.get_current_results())

    def test_large_global_scene_change_is_suppressed(self):
        processor = self.build_processor(max_foreground_ratio=0.12)
        shifted_frame = self.background.copy()
        shifted_frame[self.clean_road > 0] = 35

        events = []
        for _ in range(6):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=shifted_frame,
                vehicle_bboxes=[],
                road_mask=self.clean_road,
            ))

        self.assertEqual([], events)
        self.assertEqual([], processor.get_current_results())

    def test_fragmented_foreground_is_merged_and_capped(self):
        processor = self.build_processor(component_merge_kernel=13, max_candidates=3)
        frame = self.background.copy()
        cv2.rectangle(frame, (100, 160), (128, 210), (30, 30, 30), -1)
        cv2.rectangle(frame, (136, 160), (164, 210), (30, 30, 30), -1)
        for x in (230, 320, 410, 500):
            cv2.rectangle(frame, (x, 250), (x + 30, 285), (30, 30, 30), -1)

        for _ in range(6):
            processor.process_frame(
                device_id="mobile_001",
                frame=frame,
                vehicle_bboxes=[],
                road_mask=self.clean_road,
            )

        current = processor.get_current_results()
        self.assertLessEqual(len(current), 3)
        merged = [event for event in current if event["bbox"][0] < 200]
        self.assertEqual(1, len(merged))

    def test_roi_and_lane_marking_filters(self):
        processor = self.build_processor(
            road_roi=[[40, 80], [520, 80], [520, 430], [40, 430]],
        )

        frame = self.background.copy()
        cv2.rectangle(frame, (560, 180), (610, 250), (30, 30, 30), -1)
        cv2.rectangle(frame, (250, 120), (260, 230), (240, 240, 240), -1)

        events = []
        for _ in range(6):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=frame,
                vehicle_bboxes=[],
                road_mask=None,
            ))

        self.assertEqual([], events)

    def test_background_learning_skips_heavily_occluded_frame(self):
        detector = AnomalyDetector(
            warmup_frames=0,
            min_area=300,
            road_roi=[[40, 80], [600, 80], [600, 430], [40, 430]],
            max_background_vehicle_ratio=0.02,
            use_default_road_scope=False,
        )

        learned = detector.update_background(
            self.background,
            road_mask=None,
            vehicle_bboxes=[[40, 80, 600, 430]],
        )

        self.assertFalse(learned)
        self.assertEqual(0, detector.background_frames)

    def test_background_progress_is_exposed_and_reset(self):
        detector = AnomalyDetector(
            warmup_frames=0,
            min_area=300,
            use_default_road_scope=False,
        )
        processor = RoadAnomalyProcessor(detector=detector)

        self.assertEqual(0, processor.background_frames)
        self.assertTrue(processor.update_background(self.background, road_mask=self.clean_road))
        self.assertEqual(1, processor.background_frames)

        processor.reset()
        self.assertEqual(0, processor.background_frames)


class DinoReferenceDetectorTest(unittest.TestCase):
    def setUp(self):
        self.background = np.ones((240, 320, 3), dtype=np.uint8) * 100
        self.road_mask = np.zeros((240, 320), dtype=np.uint8)
        cv2.rectangle(self.road_mask, (20, 30), (300, 220), 255, -1)

    @staticmethod
    def fake_features(frame):
        intensity = cv2.resize(
            frame[:, :, 0].astype(np.float32) / 255.0,
            (16, 12),
            interpolation=cv2.INTER_AREA,
        )
        x_grid = np.tile(np.linspace(0.0, 1.0, 16, dtype=np.float32), (12, 1))
        y_grid = np.tile(np.linspace(0.0, 1.0, 12, dtype=np.float32)[:, None], (1, 16))
        return np.stack((intensity, 1.0 - intensity, x_grid, y_grid), axis=0)

    def build_processor(self, **kwargs):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            local_radius=1,
            heat_threshold=0.01,
            pixel_threshold=0.01,
            static_frames_threshold=3,
            min_area=150,
            min_component_extent=0.05,
            component_merge_kernel=5,
            use_default_road_scope=False,
            **kwargs,
        )
        processor = RoadAnomalyProcessor(detector=detector)
        for _ in range(4):
            self.assertTrue(
                processor.update_background(self.background, road_mask=self.road_mask)
            )
        return processor

    def test_reference_object_is_confirmed(self):
        processor = self.build_processor()
        frame = self.background.copy()
        cv2.rectangle(frame, (110, 100), (175, 165), (20, 20, 20), -1)

        events = []
        for _ in range(6):
            events.extend(
                processor.process_frame(
                    device_id="mobile_001",
                    frame=frame,
                    road_mask=self.road_mask,
                    vehicle_bboxes=[],
                )
            )

        self.assertEqual(1, len(events))
        self.assertEqual("warning", events[0]["status"])
        self.assertEqual("warning", processor.detector.last_detection_reason)
        self.assertEqual(1, processor.detector.last_warning_count)

    def test_reference_vehicle_mask_suppresses_change(self):
        processor = self.build_processor()
        frame = self.background.copy()
        bbox = [110, 100, 175, 165]
        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (20, 20, 20), -1)

        events = []
        for _ in range(6):
            events.extend(
                processor.process_frame(
                    device_id="mobile_001",
                    frame=frame,
                    road_mask=self.road_mask,
                    vehicle_bboxes=[bbox],
                )
            )

        self.assertEqual([], events)
        self.assertEqual([], processor.get_current_results())

    def test_reference_global_change_requests_recalibration(self):
        processor = self.build_processor(
            camera_change_ratio=0.20,
            camera_change_frames=2,
        )
        changed = np.ones_like(self.background) * 25

        for _ in range(2):
            processor.process_frame(
                device_id="mobile_001",
                frame=changed,
                road_mask=self.road_mask,
                vehicle_bboxes=[],
            )

        self.assertTrue(processor.detector.needs_recalibration)
        self.assertEqual("camera_change", processor.detector.last_detection_reason)
        self.assertEqual([], processor.get_current_results())

    def test_high_resolution_appearance_finds_small_object(self):
        def constant_features(_frame):
            return np.ones((4, 12, 16), dtype=np.float32)

        detector = DinoReferenceDetector(
            feature_extractor=constant_features,
            device="cpu",
            heat_threshold=0.99,
            pixel_threshold=0.99,
            appearance_threshold=18,
            static_frames_threshold=3,
            min_area=150,
            min_component_extent=0.05,
            component_merge_kernel=5,
            use_default_road_scope=False,
        )
        processor = RoadAnomalyProcessor(detector=detector)
        for _ in range(4):
            self.assertTrue(
                processor.update_background(self.background, road_mask=self.road_mask)
            )

        frame = self.background.copy()
        cv2.circle(frame, (150, 140), 14, (235, 235, 235), -1)
        events = []
        for _ in range(5):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=frame,
                road_mask=self.road_mask,
                vehicle_bboxes=[],
            ))

        self.assertEqual(1, len(events))
        self.assertEqual("warning", events[0]["status"])
        self.assertGreater(detector.last_appearance_score, detector.appearance_threshold)

    def test_appearance_compensates_global_brightness_change(self):
        def constant_features(_frame):
            return np.ones((4, 12, 16), dtype=np.float32)

        detector = DinoReferenceDetector(
            feature_extractor=constant_features,
            device="cpu",
            heat_threshold=0.99,
            pixel_threshold=0.99,
            appearance_threshold=18,
            static_frames_threshold=3,
            min_area=150,
            min_component_extent=0.05,
            component_merge_kernel=5,
            use_default_road_scope=False,
        )
        processor = RoadAnomalyProcessor(detector=detector)
        for _ in range(4):
            self.assertTrue(
                processor.update_background(self.background, road_mask=self.road_mask)
            )
        brighter = cv2.convertScaleAbs(self.background, alpha=1.0, beta=20)

        events = []
        for _ in range(6):
            events.extend(processor.process_frame(
                device_id="mobile_001",
                frame=brighter,
                road_mask=self.road_mask,
                vehicle_bboxes=[],
            ))

        self.assertEqual([], events)
        self.assertEqual([], processor.get_current_results())

    def test_reference_calibration_masks_moderate_vehicle(self):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            use_default_road_scope=False,
        )

        learned = detector.update_background(
            self.background,
            road_mask=self.road_mask,
            vehicle_bboxes=[[100, 80, 180, 170]],
        )

        self.assertTrue(learned)
        self.assertEqual(1, detector.background_frames)
        self.assertGreater(detector.last_background_vehicle_ratio, 0.0)
        self.assertIsNone(detector.last_background_skip_reason)

    def test_reference_calibration_skips_heavily_occluded_frame(self):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            use_default_road_scope=False,
        )

        learned = detector.update_background(
            self.background,
            road_mask=self.road_mask,
            vehicle_bboxes=[[20, 30, 300, 220]],
        )

        self.assertFalse(learned)
        self.assertEqual(0, detector.background_frames)
        self.assertEqual(
            "insufficient_visible_road",
            detector.last_background_skip_reason,
        )

    def test_reference_legacy_strict_flag_no_longer_rejects_vehicle(self):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            use_default_road_scope=False,
            allow_background_vehicles=False,
        )

        learned = detector.update_background(
            self.background,
            road_mask=self.road_mask,
            vehicle_bboxes=[[100, 80, 180, 170]],
        )

        self.assertTrue(learned)
        self.assertEqual(1, detector.background_frames)
        self.assertIsNone(detector.last_background_skip_reason)

    def test_reference_calibration_uses_road_relative_visible_ratio(self):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            use_default_road_scope=False,
        )
        narrow_road = np.zeros_like(self.road_mask)
        cv2.rectangle(narrow_road, (120, 90), (190, 150), 255, -1)

        learned = detector.update_background(
            self.background,
            road_mask=narrow_road,
            vehicle_bboxes=[],
        )

        self.assertTrue(learned)
        self.assertEqual(1, detector.background_frames)
        self.assertGreaterEqual(detector.last_background_valid_ratio, 0.99)

    def test_reference_warmup_does_not_create_background_reference(self):
        detector = DinoReferenceDetector(
            feature_extractor=self.fake_features,
            device="cpu",
            use_default_road_scope=False,
        )

        elapsed_ms = detector.warmup()

        self.assertIsNotNone(elapsed_ms)
        self.assertTrue(detector.model_warmed_up)
        self.assertEqual(0, detector.background_frames)
        self.assertIsNone(detector.reference_sum)
        self.assertIsNone(detector.reference_count)


if __name__ == "__main__":
    unittest.main()
