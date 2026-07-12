import argparse
import csv
import random
import shutil
import sys
from collections import defaultdict
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

    # Keep every crop from the same source frame in a single split. Splitting
    # crops independently leaks nearly identical visual context into validation.
    grouped_rows = defaultdict(list)
    for row in rows:
        grouped_rows[row["source_image"]].append(row)

    source_images = sorted(grouped_rows)
    random.seed(args.seed)
    random.shuffle(source_images)
    val_source_count = int(round(len(source_images) * args.val_ratio))
    if len(source_images) > 1:
        val_source_count = min(len(source_images) - 1, max(1, val_source_count))
    else:
        val_source_count = 0
    val_sources = set(source_images[:val_source_count])
    val_rows = [row for source in source_images if source in val_sources for row in grouped_rows[source]]
    train_rows = [row for source in source_images if source not in val_sources for row in grouped_rows[source]]

    for split in ("train", "val"):
        split_dir = output_dir / split
        if split_dir.exists():
            shutil.rmtree(split_dir)
        split_dir.mkdir(parents=True, exist_ok=True)

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
    print(
        f"train crops: {len(train_rows)} from "
        f"{len(source_images) - len(val_sources)} source images -> {train_manifest}"
    )
    print(f"val crops: {len(val_rows)} from {len(val_sources)} source images -> {val_manifest}")
    overlap = {row["source_image"] for row in train_rows} & {row["source_image"] for row in val_rows}
    print(f"source overlap: {len(overlap)}")
    print("请人工确认 labels CSV 后再将该数据用于训练。")


if __name__ == "__main__":
    main()
