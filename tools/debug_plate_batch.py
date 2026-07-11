import argparse
import csv
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.ai_models.plate_detection.detector import PlateDetector
from cloud.ai_models.plate_recognition.plate_recognizer import (
    PlateRecognizer,
    crop_plate_image,
    is_ocr_candidate_crop,
    is_valid_plate_number,
    normalize_plate_number,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def draw_detection(image, bbox, label, valid):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    color = (0, 200, 0) if valid else (0, 0, 255)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
    cv2.putText(
        image,
        label,
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
        cv2.LINE_AA,
    )


def main():
    parser = argparse.ArgumentParser(description="Batch debug plate detection and OCR.")
    parser.add_argument("--input-dir", default="data/plate_debug")
    parser.add_argument("--output-dir", default="data/plate_debug_report")
    parser.add_argument("--conf", type=float, default=0.20)
    parser.add_argument("--plate-model", default="cloud/ai_models/plate_detection/sandbox_plate_best.pt")
    parser.add_argument("--lpr-model", default="cloud/ai_models/plate_recognition/Final_LPRNet_model.pth")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    crops_dir = output_dir / "crops"
    annotated_dir = output_dir / "annotated"
    crops_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(path for path in input_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not image_paths:
        raise FileNotFoundError(f"No images found in {input_dir}")

    detector = PlateDetector(model_path=args.plate_model, conf_threshold=args.conf)
    recognizer = PlateRecognizer(model_path=args.lpr_model)

    rows = []
    summary = {
        "images": len(image_paths),
        "no_detection": 0,
        "detections": 0,
        "valid_ocr": 0,
        "invalid_ocr": 0,
    }

    for image_path in image_paths:
        image = cv2.imread(str(image_path))
        if image is None:
            rows.append({
                "image": image_path.name,
                "status": "read_failed",
                "bbox": "",
                "confidence": "",
                "ocr_raw": "",
                "ocr_normalized": "",
                "valid_plate": "false",
                "crop": "",
                "annotated": "",
            })
            continue

        annotated = image.copy()
        detections = detector.detect(image)
        if not detections:
            summary["no_detection"] += 1
            annotated_path = annotated_dir / f"{image_path.stem}_no_detection.jpg"
            cv2.imwrite(str(annotated_path), annotated)
            rows.append({
                "image": image_path.name,
                "status": "no_detection",
                "bbox": "",
                "confidence": "",
                "ocr_raw": "",
                "ocr_normalized": "",
                "valid_plate": "false",
                "crop": "",
                "annotated": str(annotated_path),
            })
            continue

        for index, detection in enumerate(detections, 1):
            summary["detections"] += 1
            bbox = detection["bbox"]
            crop = crop_plate_image(image, bbox)
            crop_path = ""
            raw_text = ""
            normalized = ""
            valid = False

            if is_ocr_candidate_crop(crop):
                crop_path_obj = crops_dir / f"{image_path.stem}_plate_{index}.jpg"
                cv2.imwrite(str(crop_path_obj), crop)
                crop_path = str(crop_path_obj)
                try:
                    raw_text = recognizer.recognize(crop)
                    normalized = recognizer.recognize_best(crop)
                    valid = is_valid_plate_number(normalized)
                except Exception as exc:
                    raw_text = f"OCR_ERROR: {exc}"
            elif crop is not None and crop.size > 0:
                crop_path_obj = crops_dir / f"{image_path.stem}_plate_{index}_filtered.jpg"
                cv2.imwrite(str(crop_path_obj), crop)
                crop_path = str(crop_path_obj)
                raw_text = "FILTERED_CROP"

            if valid:
                summary["valid_ocr"] += 1
            else:
                summary["invalid_ocr"] += 1

            label = normalized or raw_text or f"plate {detection['confidence']:.2f}"
            draw_detection(annotated, bbox, label, valid)
            rows.append({
                "image": image_path.name,
                "status": "ok" if valid else "invalid_ocr",
                "bbox": " ".join(str(v) for v in bbox),
                "confidence": f"{detection['confidence']:.4f}",
                "ocr_raw": raw_text,
                "ocr_normalized": normalized,
                "valid_plate": str(valid).lower(),
                "crop": crop_path,
                "annotated": "",
            })

        annotated_path = annotated_dir / f"{image_path.stem}_annotated.jpg"
        cv2.imwrite(str(annotated_path), annotated)
        for row in rows:
            if row["image"] == image_path.name and not row["annotated"]:
                row["annotated"] = str(annotated_path)

    report_path = output_dir / "report.csv"
    with report_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"images: {summary['images']}")
    print(f"no_detection: {summary['no_detection']}")
    print(f"detections: {summary['detections']}")
    print(f"valid_ocr: {summary['valid_ocr']}")
    print(f"invalid_ocr: {summary['invalid_ocr']}")
    print(f"report: {report_path}")
    print(f"crops: {crops_dir}")
    print(f"annotated: {annotated_dir}")


if __name__ == "__main__":
    main()
