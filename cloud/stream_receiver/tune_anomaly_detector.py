"""
Offline tuning helper for the road anomaly detector.

It uses clean road photos to initialize the MOG2 background model, then checks
test photos for persistent non-vehicle foreground objects on the road area.
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
from anomaly_detection.drivable_segmenter import DrivableAreaSegmenter
from vehicle_detection.detector import VehicleDetector


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(description="Tune road anomaly detector with photos.")
    parser.add_argument("--clean", default="data/sandbox_anomaly/clean_road", help="Clean road image folder.")
    parser.add_argument("--test", default="data/sandbox_anomaly/vehicle_test", help="Test image folder.")
    parser.add_argument("--output", default="data/sandbox_anomaly/output", help="Debug output folder.")
    parser.add_argument("--min-area", type=int, default=900, help="Minimum contour area.")
    parser.add_argument("--max-area", type=int, default=0, help="Maximum contour area; 0 uses max-area-ratio.")
    parser.add_argument("--max-area-ratio", type=float, default=0.08, help="Maximum contour area as a frame-area ratio.")
    parser.add_argument("--static-frames", type=int, default=1, help="Static frames threshold for photo tuning.")
    parser.add_argument("--var-threshold", type=float, default=24, help="MOG2 variance threshold.")
    parser.add_argument("--history", type=int, default=200, help="MOG2 history length.")
    parser.add_argument("--resize-width", type=int, default=960, help="Resize images for stable comparison; 0 disables.")
    parser.add_argument("--learning-rate", type=float, default=0, help="Detection-time MOG2 learning rate.")
    parser.add_argument("--drivable-model", default="", help="Optional YOLO-seg drivable-area model path.")
    parser.add_argument("--drivable-conf", type=float, default=0.15, help="Drivable segmentation confidence.")
    parser.add_argument("--vehicle-model", default="", help="Optional YOLO vehicle model path for normal-vehicle masking.")
    parser.add_argument("--vehicle-conf", type=float, default=0.35, help="Vehicle detection confidence.")
    parser.add_argument("--vehicle-padding", type=int, default=18, help="Extra padding around detected vehicle boxes.")
    parser.add_argument("--limit", type=int, default=0, help="Limit test images for quick tuning; 0 uses all.")
    parser.add_argument(
        "--single-frame",
        action="store_true",
        help="Evaluate independent non-fixed-camera photos without MOG2 clean-background initialization.",
    )
    parser.add_argument(
        "--pairwise",
        action="store_true",
        help="Evaluate sorted clean/test image pairs; useful for small same-viewpoint comparison sets.",
    )
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
    if args.limit > 0:
        test_images = test_images[:args.limit]
        clean_images = clean_images[:args.limit]

    if not args.single_frame and not clean_images:
        raise SystemExit(f"No clean images found in: {args.clean}")
    if not test_images:
        raise SystemExit(f"No test images found in: {args.test}")
    if args.pairwise and len(clean_images) != len(test_images):
        raise SystemExit(
            f"Pairwise mode needs the same number of clean/test images: "
            f"{len(clean_images)} clean, {len(test_images)} test"
        )

    detector = AnomalyDetector(
        history=args.history,
        var_threshold=args.var_threshold,
        min_area=args.min_area,
        max_area=args.max_area or None,
        max_area_ratio=args.max_area_ratio,
        static_frames_threshold=args.static_frames,
        vehicle_mask_padding=args.vehicle_padding,
        warmup_frames=0,
        learning_rate=args.learning_rate,
        startup_static_check=not args.pairwise,
        road_surface_outlier_check=not args.pairwise,
    )
    segmenter = (
        DrivableAreaSegmenter(args.drivable_model, confidence=args.drivable_conf)
        if args.drivable_model
        else None
    )
    vehicle_detector = (
        VehicleDetector(args.vehicle_model, conf_threshold=args.vehicle_conf)
        if args.vehicle_model
        else None
    )

    print("=" * 70)
    print("Road anomaly detector tuning")
    print("=" * 70)
    mode = "pairwise" if args.pairwise else ("single-frame" if args.single_frame else "fixed-camera MOG2")
    print(f"mode         : {mode}")
    print(f"clean images: {len(clean_images) if not args.single_frame else 0}")
    print(f"test images : {len(test_images)}")
    print(
        f"min_area={args.min_area}, max_area={args.max_area or 'ratio'}, "
        f"max_area_ratio={args.max_area_ratio}, var_threshold={args.var_threshold}, "
        f"static_frames={args.static_frames}"
    )
    if segmenter:
        print(f"drivable_model={args.drivable_model}, drivable_conf={args.drivable_conf}")
    if vehicle_detector:
        print(f"vehicle_model={args.vehicle_model}, vehicle_conf={args.vehicle_conf}, vehicle_padding={args.vehicle_padding}")

    if not args.single_frame and not args.pairwise:
        for image_path in clean_images:
            clean_image = read_image(image_path, args.resize_width)
            road_mask = segmenter.predict_mask(clean_image) if segmenter else None
            vehicle_bboxes = []
            if vehicle_detector:
                vehicle_bboxes = [vehicle["bbox"] for vehicle in vehicle_detector.detect(clean_image)]
            detector.update_background(clean_image, road_mask=road_mask, vehicle_bboxes=vehicle_bboxes)
        print("MOG2 background initialized")
    elif args.pairwise:
        print("MOG2 background initialized per clean/test pair")
    else:
        print("MOG2 background skipped for independent photos")

    output_dir = Path(args.output)
    if not args.no_save:
        output_dir.mkdir(parents=True, exist_ok=True)

    total_candidates = 0
    images_with_candidates = 0
    worst = []

    pairs = list(zip(clean_images, test_images)) if args.pairwise else [(None, image_path) for image_path in test_images]
    for clean_path, image_path in pairs:
        if args.single_frame or args.pairwise:
            detector.reset()
        if args.pairwise:
            clean_image = read_image(clean_path, args.resize_width)
            clean_road_mask = segmenter.predict_mask(clean_image) if segmenter else None
            clean_vehicle_bboxes = []
            if vehicle_detector:
                clean_vehicle_bboxes = [vehicle["bbox"] for vehicle in vehicle_detector.detect(clean_image)]
            detector.update_background(
                clean_image,
                road_mask=clean_road_mask,
                vehicle_bboxes=clean_vehicle_bboxes,
            )
        image = read_image(image_path, args.resize_width)
        road_mask = segmenter.predict_mask(image) if segmenter else None
        vehicle_bboxes = []
        if vehicle_detector:
            vehicle_bboxes = [vehicle["bbox"] for vehicle in vehicle_detector.detect(image)]
        anomalies = detector.detect(image, vehicle_bboxes=vehicle_bboxes, road_mask=road_mask)
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
