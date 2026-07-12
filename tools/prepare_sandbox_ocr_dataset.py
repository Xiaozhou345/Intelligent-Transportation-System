import argparse
import csv
import random
import shutil
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.ai_models.plate_recognition.plate_recognizer import normalize_plate_number, is_valid_plate_number


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def split_plates(value):
    plates = []
    for item in (value or "").split(";"):
        plate = normalize_plate_number(item)
        if is_valid_plate_number(plate):
            plates.append(plate)
    return plates


def main():
    parser = argparse.ArgumentParser(description="Prepare OCR crops from sandbox plate debug report and labels.")
    parser.add_argument("--report", default="data/plate_debug_report/report.csv")
    parser.add_argument("--labels", default="data/plate_debug_labels.csv")
    parser.add_argument("--output-dir", default="data/sandbox_plate_ocr")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    report_path = Path(args.report)
    labels_path = Path(args.labels)
    output_dir = Path(args.output_dir)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels not found: {labels_path}")

    labels_by_image = {}
    with labels_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            labels_by_image[row["image"]] = split_plates(row.get("expected_plates", ""))

    rows = []
    with report_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            crop_path = Path(row.get("crop", ""))
            if not crop_path.exists() or crop_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            image = row["image"]
            expected = labels_by_image.get(image, [])
            predicted = normalize_plate_number(row.get("ocr_normalized", ""))

            label = ""
            if predicted in expected:
                label = predicted
            elif len(expected) == 1:
                label = expected[0]

            if not is_valid_plate_number(label):
                continue

            crop = cv2.imread(str(crop_path))
            if crop is None or crop.size == 0:
                continue
            rows.append({
                "source_image": image,
                "source_crop": str(crop_path),
                "label": label,
            })

    random.seed(args.seed)
    random.shuffle(rows)
    val_count = int(round(len(rows) * args.val_ratio))
    val_rows = rows[:val_count]
    train_rows = rows[val_count:]

    for split in ("train", "val"):
        (output_dir / split).mkdir(parents=True, exist_ok=True)

    def write_split(split, split_rows):
        manifest_path = output_dir / f"{split}.csv"
        with manifest_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["image", "label", "source_image"])
            writer.writeheader()
            for index, row in enumerate(split_rows, 1):
                src = Path(row["source_crop"])
                dst_name = f"{split}_{index:05d}{src.suffix.lower()}"
                dst = output_dir / split / dst_name
                shutil.copy2(src, dst)
                writer.writerow({
                    "image": str(dst.relative_to(output_dir)).replace("\\", "/"),
                    "label": row["label"],
                    "source_image": row["source_image"],
                })
        return manifest_path

    train_manifest = write_split("train", train_rows)
    val_manifest = write_split("val", val_rows)

    print(f"output: {output_dir}")
    print(f"total crops: {len(rows)}")
    print(f"train crops: {len(train_rows)} -> {train_manifest}")
    print(f"val crops: {len(val_rows)} -> {val_manifest}")
    print("请人工确认 labels CSV 后再将该数据用于训练。")


if __name__ == "__main__":
    main()
