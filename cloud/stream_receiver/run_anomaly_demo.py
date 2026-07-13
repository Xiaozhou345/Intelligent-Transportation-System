"""
Local sandbox road-anomaly demo.

Use this before full RTMP/frontend integration. The first warmup frames should
show a clean sandbox road. After warmup, put an obstacle on the road and the
script writes an annotated video with anomaly boxes.
"""
import argparse
import os
import sys
from pathlib import Path

import cv2


CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parents[1]
AI_MODELS_DIR = CURRENT_DIR.parent / "ai_models"
if str(AI_MODELS_DIR) not in sys.path:
    sys.path.append(str(AI_MODELS_DIR))
if str(AI_MODELS_DIR / "vehicle_detection") not in sys.path:
    sys.path.append(str(AI_MODELS_DIR / "vehicle_detection"))

from anomaly_detection.anomaly_detector import AnomalyDetector
from anomaly_detection.drivable_segmenter import DrivableAreaSegmenter


def parse_args():
    parser = argparse.ArgumentParser(description="Run local sandbox road-anomaly detection demo.")
    parser.add_argument("--source", default="0", help="Camera index or video path. Default: 0.")
    parser.add_argument("--output", default="data/sandbox_anomaly/output/anomaly_demo.mp4")
    parser.add_argument("--warmup-frames", type=int, default=60, help="Clean-road frames for background init.")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means process until source ends.")
    parser.add_argument("--min-area", type=int, default=700)
    parser.add_argument("--static-frames", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0)
    parser.add_argument("--display", action="store_true", help="Show live preview window.")
    parser.add_argument("--no-drivable", action="store_true", help="Disable drivable-area segmentation mask.")
    parser.add_argument("--no-vehicle-mask", action="store_true", help="Disable YOLO vehicle mask.")
    parser.add_argument("--vehicle-conf", type=float, default=0.45)
    return parser.parse_args()


def open_source(source):
    if source.isdigit():
        return cv2.VideoCapture(int(source))
    return cv2.VideoCapture(source)


def load_segmenter(disabled):
    if disabled:
        return None

    model_path = AI_MODELS_DIR / "anomaly_detection" / "sandbox_drivable_best.pt"
    if not model_path.exists():
        print("drivable model not found; detection will use full frame")
        return None

    try:
        return DrivableAreaSegmenter(str(model_path), confidence=0.15)
    except Exception as exc:
        print(f"drivable segmenter unavailable: {exc}")
        return None


def load_vehicle_detector(disabled, confidence):
    if disabled:
        return None

    try:
        from detector import VehicleDetector

        sandbox_model = AI_MODELS_DIR / "vehicle_detection" / "sandbox_vehicle_best.pt"
        default_model = AI_MODELS_DIR / "vehicle_detection" / "yolo11s.pt"
        model_path = sandbox_model if sandbox_model.exists() else default_model
        if not model_path.exists():
            print("vehicle model not found; anomaly detection will not mask vehicles")
            return None
        return VehicleDetector(model_path=str(model_path), conf_threshold=confidence)
    except Exception as exc:
        print(f"vehicle detector unavailable: {exc}")
        return None


def make_writer(output_path, fps, width, height):
    if not output_path:
        return None
    path = Path(output_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, max(1.0, fps), (width, height))
    return writer, path


def draw_boxes(frame, anomalies, vehicles):
    annotated = frame.copy()
    for vehicle in vehicles:
        x1, y1, x2, y2 = vehicle["bbox"]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 160, 0), 2)
        cv2.putText(
            annotated,
            f"vehicle {vehicle['confidence']:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 160, 0),
            2,
        )

    for anomaly in anomalies:
        x1, y1, x2, y2 = anomaly["bbox"]
        is_warning = anomaly["status"] == "warning"
        color = (0, 0, 255) if is_warning else (0, 200, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"id={anomaly['anomaly_id']} {anomaly['status']} f={anomaly['static_frames']}"
        cv2.putText(
            annotated,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
    return annotated


def main():
    args = parse_args()
    cap = open_source(args.source)
    if not cap.isOpened():
        raise SystemExit(f"cannot open source: {args.source}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    writer, output_path = make_writer(args.output, fps, width, height)

    segmenter = load_segmenter(args.no_drivable)
    vehicle_detector = load_vehicle_detector(args.no_vehicle_mask, args.vehicle_conf)
    detector = AnomalyDetector(
        min_area=args.min_area,
        static_frames_threshold=args.static_frames,
        warmup_frames=args.warmup_frames,
        learning_rate=args.learning_rate,
        max_missed_frames=4,
    )

    frame_id = 0
    warning_count = 0
    print("start demo; keep the road clean during warmup frames")
    print(f"source={args.source}, warmup_frames={args.warmup_frames}, output={output_path}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_id += 1
        if args.max_frames and frame_id > args.max_frames:
            break

        road_mask = segmenter.predict_mask(frame) if segmenter else None
        vehicles = vehicle_detector.detect(frame) if vehicle_detector else []
        vehicle_bboxes = [vehicle["bbox"] for vehicle in vehicles]
        anomalies = detector.detect(frame, vehicle_bboxes=vehicle_bboxes, road_mask=road_mask)

        warnings = [item for item in anomalies if item["status"] == "warning"]
        if warnings:
            warning_count += len(warnings)
            print(f"frame {frame_id}: warnings={len(warnings)} anomalies={warnings}")

        annotated = draw_boxes(frame, anomalies, vehicles)
        if frame_id <= args.warmup_frames:
            cv2.putText(
                annotated,
                f"warming up {frame_id}/{args.warmup_frames}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )

        if writer:
            writer.write(annotated)
        if args.display:
            cv2.imshow("sandbox anomaly demo", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    if writer:
        writer.release()
    if args.display:
        cv2.destroyAllWindows()
    print(f"done. frames={frame_id}, warning_frames={warning_count}, output={output_path}")


if __name__ == "__main__":
    main()
