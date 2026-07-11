import argparse
import csv
from collections import defaultdict
from pathlib import Path


def split_plates(value):
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def main():
    parser = argparse.ArgumentParser(description="Create a plate ground-truth label template.")
    parser.add_argument("--report", default="data/plate_debug_report/report.csv")
    parser.add_argument("--output", default="data/plate_debug_labels.csv")
    args = parser.parse_args()

    report_path = Path(args.report)
    output_path = Path(args.output)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    predictions_by_image = defaultdict(list)
    with report_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            plate = row.get("ocr_normalized", "").strip()
            if row.get("valid_plate") == "true" and plate:
                predictions_by_image[row["image"]].append(plate)
            else:
                predictions_by_image.setdefault(row["image"], [])

    rows = []
    for image in sorted(predictions_by_image):
        predictions = predictions_by_image[image]
        deduped = []
        for plate in predictions:
            if plate not in deduped:
                deduped.append(plate)
        rows.append({
            "image": image,
            "expected_plates": ";".join(deduped),
            "predicted_plates": ";".join(deduped),
            "note": "请确认 expected_plates；多车牌用英文分号分隔，无车牌留空",
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["image", "expected_plates", "predicted_plates", "note"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"label template: {output_path}")
    print(f"images: {len(rows)}")


if __name__ == "__main__":
    main()
