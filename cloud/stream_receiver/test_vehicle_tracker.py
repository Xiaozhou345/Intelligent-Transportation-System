"""Regression tests for real-time vehicle tracking output."""
import os
import sys
import unittest


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKING_DIR = os.path.join(CURRENT_DIR, "..", "ai_models", "vehicle_tracking")
if TRACKING_DIR not in sys.path:
    sys.path.append(TRACKING_DIR)

from vehicle_tracker import VehicleTracker


class VehicleTrackerTest(unittest.TestCase):
    @staticmethod
    def detection(bbox):
        return {
            "bbox": bbox,
            "confidence": 0.9,
            "class_name": "vehicle",
        }

    def test_short_dropout_reuses_track_id(self):
        tracker = VehicleTracker(max_time_lost=5, track_thresh=0.35, match_thresh=0.2)
        first = tracker.update([self.detection([100, 100, 200, 200])])
        track_id = first[0]["track_id"]

        self.assertEqual([], tracker.update([]))
        recovered = tracker.update([self.detection([102, 100, 202, 200])])

        self.assertEqual(track_id, recovered[0]["track_id"])
        self.assertEqual([102.0, 100.0, 202.0, 200.0], recovered[0]["bbox"])

    def test_result_bbox_is_current_detection_not_smoothed_position(self):
        tracker = VehicleTracker(max_time_lost=5, track_thresh=0.35, match_thresh=0.1)
        tracker.update([self.detection([100, 100, 200, 200])])
        current_bbox = [130, 100, 230, 200]
        result = tracker.update([self.detection(current_bbox)])

        self.assertEqual([float(value) for value in current_bbox], result[0]["bbox"])
        self.assertIn("smoothed_bbox", result[0])


if __name__ == "__main__":
    unittest.main()
