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
    clean_road = np.zeros((480, 640), dtype=np.uint8)
    cv2.rectangle(clean_road, (40, 80), (600, 430), 255, -1)

    for _ in range(35):
        processor.update_background(background, road_mask=clean_road)

    frame = background.copy()
    cv2.rectangle(frame, (120, 220), (180, 280), (30, 30, 30), -1)

    emitted_events = []
    for _ in range(20):
        emitted_events.extend(processor.process_frame(
            device_id="mobile_001",
            frame=frame,
            vehicle_bboxes=[[360, 200, 430, 300]],
            road_mask=clean_road,
        ))

    assert emitted_events, "expected road anomaly warning event"
    event = emitted_events[-1]
    assert event["event_type"] == "road_anomaly"
    assert event["status"] == "warning"
    assert event["affected_lane"] == "lane_1"
    assert event["duration_frames"] >= 15
    assert len(emitted_events) == 1, "same stable object should be throttled"

    vehicle_frame = background.copy()
    cv2.rectangle(vehicle_frame, (360, 200), (430, 300), (30, 30, 30), -1)
    vehicle_events = processor.process_frame(
        device_id="mobile_001",
        frame=vehicle_frame,
        vehicle_bboxes=[[360, 200, 430, 300]],
        road_mask=clean_road,
    )
    assert not vehicle_events, "vehicle mask should not become road anomaly"
    print("road anomaly processor smoke test passed")


if __name__ == "__main__":
    main()
