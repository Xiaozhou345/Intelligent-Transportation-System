"""
Smoke test for the road anomaly processor.
"""
import os
import sys

import cv2
import numpy as np


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from anomaly_processor import RoadAnomalyProcessor


def main():
    processor = RoadAnomalyProcessor(
        lane_regions={
            "lane_1": [[0, 0], [320, 0], [320, 480], [0, 480]],
            "lane_2": [[320, 0], [640, 0], [640, 480], [320, 480]],
        }
    )

    background = np.ones((480, 640, 3), dtype=np.uint8) * 100
    for _ in range(35):
        processor.update_background(background)

    frame = background.copy()
    cv2.rectangle(frame, (120, 220), (180, 280), (30, 30, 30), -1)

    events = []
    for _ in range(20):
        events = processor.process_frame(
            device_id="mobile_001",
            frame=frame,
            vehicle_bboxes=[[360, 200, 430, 300]],
        )

    assert events, "expected road anomaly warning event"
    event = events[-1]
    assert event["event_type"] == "road_anomaly"
    assert event["status"] == "warning"
    assert event["affected_lane"] == "lane_1"
    assert event["duration_frames"] >= 15
    print("road anomaly processor smoke test passed")


if __name__ == "__main__":
    main()
