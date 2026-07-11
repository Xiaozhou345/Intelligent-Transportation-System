from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


def levenshtein(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def source_group(image_name: str) -> str:
    return image_name.split("__", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build OCR crops from user-confirmed plate labels")
    parser.add_argument("--report", required=True)
    parser.add_argument("--plates", nargs="*", default=[])
    parser.add_argument("--plates-file", default="")
    parser.add_argument("--output", default="data/confirmed_video_plate_ocr")
    parser.add_argument("--max-distance", type=int, default=3)
    parser.add_argument("--val-group", default="")
    args = parser.parse_args()

    report = Path(args.report)
    output = Path(args.output)
    plate_values = list(args.plates)
    if args.plates_file:
        plate_values.extend(Path(args.plates_file).read_text(encoding="utf-8-sig").splitlines())
    candidates = [plate.strip().upper().replace("-", "") for plate in plate_values if plate.strip()]
    if not candidates:
        raise SystemExit("Provide --plates or --plates-file")
    accepted = []
    rejected = 0
    groups: dict[str, int] = {}

    with report.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            crop = Path(row.get("crop", ""))
            prediction = row.get("ocr_normalized", "").strip().upper().replace("-", "")
            if not crop.exists() or not prediction:
                rejected += 1
                continue
            ranked = sorted((levenshtein(prediction, plate), plate) for plate in candidates)
            best_distance, label = ranked[0]
            second_distance = ranked[1][0] if len(ranked) > 1 else best_distance + 2
            if best_distance > args.max_distance or second_distance <= best_distance:
                rejected += 1
                continue
            group = source_group(row["image"])
            groups[group] = groups.get(group, 0) + 1
            accepted.append((crop, label, group, prediction, best_distance))

    if not accepted:
        raise SystemExit("No unambiguous crops found")
    val_group = args.val_group or min(groups, key=lambda group: (abs(groups[group] - len(accepted) * 0.2), group))
    rows = {"train": [], "val": []}
    for index, (crop, label, group, prediction, distance) in enumerate(accepted, 1):
        split = "val" if group == val_group else "train"
        destination = output / split / f"{split}_{index:05d}{crop.suffix.lower()}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(crop, destination)
        rows[split].append((destination.as_posix(), label, "sandbox_video", group, prediction, distance))

    for split, split_rows in rows.items():
        with (output / f"{split}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image", "plate", "source", "source_group", "original_prediction", "edit_distance"])
            writer.writerows(split_rows)

    print(f"Confirmed plates: {', '.join(candidates)}")
    print(f"Accepted: {len(accepted)}; rejected: {rejected}")
    print(f"Train: {len(rows['train'])}; val: {len(rows['val'])}; val_group: {val_group}")
    print("Groups: " + ", ".join(f"{name}={count}" for name, count in sorted(groups.items())))


if __name__ == "__main__":
    main()
