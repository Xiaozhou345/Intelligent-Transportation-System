"""
Offline tuning helper for the road anomaly detector.

It uses clean road photos to warm up MOG2, then checks test photos for foreground
objects that would become road anomaly candidates. It can run before the sandbox
vehicle YOLO model is ready.
"""
import argparse
import os
import sys
from pathlib import Path

import cv2


CURRENT_DIR = Path(__file__).resolve().parent
AI_MODELS_DIR = CURRENT_DIR.parent / "ai_models"
if str(AI_MODELS_DIR) not in sys.path:
    sys.path.append(str(AI_MODELS_DIR))

from anomaly_detection.anomaly_detector import AnomalyDetector


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(description="Tune MOG2 road anomaly detector with photos.")
    parser.add_argument("--clean", default="data/sandbox_anomaly/clean_road", help="Clean road image folder.")
    parser.add_argument("--test", default="data/sandbox_anomaly/vehicle_test", help="Test image folder.")
    parser.add_argument("--output", default="data/sandbox_anomaly/output", help="Debug output folder.")
    parser.add_argument("--min-area", type=int, default=900, help="Minimum contour area.")
    parser.add_argument("--static-frames", type=int, default=1, help="Static frames threshold for photo tuning.")
    parser.add_argument("--var-threshold", type=float, default=24, help="MOG2 variance threshold.")
    parser.add_argument("--history", type=int, default=200, help="MOG2 history length.")
    parser.add_argument("--resize-width", type=int, default=960, help="Resize images for stable comparison; 0 disables.")
    parser.add_argument("--learning-rate", type=float, default=0, help="Detection-time MOG2 learning rate.")
    parser.add_argument("--no-save", action="store_true", help="Do not write annotated output images.")
    return parser.parse_args()


def list_images(folder):
    path = Path(folder)
    if not path.exists():
        return []
    return sorted(
        p for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def read_image(path, resize_width):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    if resize_width and image.shape[1] > resize_width:
        scale = resize_width / image.shape[1]
        image = cv2.resize(image, (resize_width, int(image.shape[0] * scale)))
    return image


def draw_anomalies(image, anomalies):
    output = image.copy()
    for anomaly in anomalies:
        x1, y1, x2, y2 = anomaly["bbox"]
        color = (0, 0, 255) if anomaly["status"] == "warning" else (0, 200, 255)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        label = f"id={anomaly['anomaly_id']} area={anomaly['area']}"
        cv2.putText(output, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return output


def main():
    args = parse_args()
    clean_images = list_images(args.clean)
    test_images = list_images(args.test)

    if not clean_images:
        raise SystemExit(f"No clean images found in: {args.clean}")
    if not test_images:
        raise SystemExit(f"No test images found in: {args.test}")

    detector = AnomalyDetector(
        history=args.history,
        var_threshold=args.var_threshold,
        min_area=args.min_area,
        static_frames_threshold=args.static_frames,
        warmup_frames=0,
        learning_rate=args.learning_rate,
    )

    print("=" * 70)
    print("Road anomaly detector tuning")
    print("=" * 70)
    print(f"clean images: {len(clean_images)}")
    print(f"test images : {len(test_images)}")
    print(f"min_area={args.min_area}, var_threshold={args.var_threshold}, static_frames={args.static_frames}")

    for image_path in clean_images:
        detector.update_background(read_image(image_path, args.resize_width))
    print("background initialized")

    output_dir = Path(args.output)
    if not args.no_save:
        output_dir.mkdir(parents=True, exist_ok=True)

    total_candidates = 0
    images_with_candidates = 0
    worst = []

    for image_path in test_images:
        image = read_image(image_path, args.resize_width)
        anomalies = detector.detect(image, vehicle_bboxes=[])
        candidate_count = len(anomalies)
        total_candidates += candidate_count
        if candidate_count:
            images_with_candidates += 1
            max_area = max(a["area"] for a in anomalies)
            worst.append((max_area, candidate_count, image_path.name))
            print(f"[candidate] {image_path.name}: count={candidate_count}, max_area={max_area}")

        if not args.no_save:
            debug_image = draw_anomalies(image, anomalies)
            cv2.imwrite(str(output_dir / f"{image_path.stem}_debug.jpg"), debug_image)

    worst = sorted(worst, reverse=True)[:10]

    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"images with candidates: {images_with_candidates}/{len(test_images)}")
    print(f"total candidates       : {total_candidates}")
    if worst:
        print("top candidate images:")
        for max_area, count, name in worst:
            print(f"  {name}: count={count}, max_area={max_area}")
    else:
        print("no anomaly candidates found")

    if not args.no_save:
        print(f"debug images written to: {output_dir}")


if __name__ == "__main__":
    main()
