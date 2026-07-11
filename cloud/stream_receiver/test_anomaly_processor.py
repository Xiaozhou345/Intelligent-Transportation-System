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


if __name__ == "__main__":
    unittest.main()
