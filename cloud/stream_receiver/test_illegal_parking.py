"""Regression tests for parking timers and tracker-ID handoff."""
import os
import sys
import unittest


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BUSINESS_LOGIC_DIR = os.path.join(CURRENT_DIR, "..", "business_logic")
if BUSINESS_LOGIC_DIR not in sys.path:
    sys.path.append(BUSINESS_LOGIC_DIR)

from illegal_parking import IllegalParkingMonitor


class IllegalParkingMonitorTest(unittest.TestCase):
    def build_monitor(self):
        return IllegalParkingMonitor(
            zones=[{
                "zone_id": "zone_a",
                "name": "Zone A",
                "polygon": [[0, 0], [500, 0], [500, 500], [0, 500]],
                "threshold_seconds": 2,
            }],
            stationary_pixel_threshold=20,
            release_grace_frames=10,
            min_history=2,
        )

    @staticmethod
    def vehicle(track_id, bbox=None):
        return {
            "track_id": track_id,
            "bbox": bbox or [100, 100, 200, 200],
            "class_name": "vehicle",
            "confidence": 0.9,
        }

    def test_stationary_vehicle_emits_after_threshold(self):
        monitor = self.build_monitor()
        self.assertEqual([], monitor.update("mobile_001", [self.vehicle(1)], "2026-07-12T10:00:00"))
        self.assertEqual([], monitor.update("mobile_001", [self.vehicle(1)], "2026-07-12T10:00:01"))
        events = monitor.update("mobile_001", [self.vehicle(1)], "2026-07-12T10:00:02.100000")

        self.assertEqual(1, len(events))
        self.assertEqual(1, events[0]["data"]["track_id"])
        self.assertGreaterEqual(events[0]["data"]["stay_time"], 2)

    def test_new_track_id_inherits_pre_alert_timer(self):
        monitor = self.build_monitor()
        monitor.update("mobile_001", [self.vehicle(7)], "2026-07-12T10:00:00")
        monitor.update("mobile_001", [self.vehicle(7)], "2026-07-12T10:00:01")

        self.assertEqual(
            [],
            monitor.update("mobile_001", [self.vehicle(19)], "2026-07-12T10:00:01.500000"),
        )
        statuses = monitor.get_active_statuses("2026-07-12T10:00:01.500000")
        self.assertEqual(1, len(statuses))
        self.assertEqual(19, statuses[0]["track_id"])
        self.assertEqual(1.5, statuses[0]["stay_time"])

        events = monitor.update(
            "mobile_001", [self.vehicle(19)], "2026-07-12T10:00:02.100000"
        )
        self.assertEqual(1, len(events))
        self.assertEqual(19, events[0]["data"]["track_id"])

        statuses = monitor.get_active_statuses("2026-07-12T10:00:02.100000")
        self.assertTrue(statuses[0]["has_warned"])
        self.assertEqual("warning", statuses[0]["status"])


if __name__ == "__main__":
    unittest.main()
