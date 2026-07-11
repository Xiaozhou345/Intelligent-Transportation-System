from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from PIL import Image


PROVINCES = [
    "皖", "沪", "津", "渝", "冀", "晋", "蒙", "辽", "吉", "黑", "苏",
    "浙", "京", "闽", "赣", "鲁", "豫", "鄂", "湘", "粤", "桂", "琼",
    "川", "贵", "云", "藏", "陕", "甘", "青", "宁", "新",
]
ALPHABETS = list("ABCDEFGHJKLMNPQRSTUVWXYZ")
ADS = ALPHABETS + list("0123456789")


def parse_ccpd(filename: str) -> tuple[tuple[int, int, int, int], str]:
    parts = Path(filename).stem.split("-")
    if len(parts) < 5:
        raise ValueError("invalid CCPD filename")

    top_left, bottom_right = parts[2].split("_")
    x1, y1 = (int(value) for value in top_left.split("&"))
    x2, y2 = (int(value) for value in bottom_right.split("&"))

    indices = [int(value) for value in parts[4].split("_")]
    if len(indices) != 7:
        raise ValueError("invalid CCPD plate label")
    label = PROVINCES[indices[0]] + ALPHABETS[indices[1]]
    label += "".join(ADS[index] for index in indices[2:])
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), label


def collect_images(root: Path, subsets: list[str]) -> list[Path]:
    images: list[Path] = []
    for subset in subsets:
        subset_dir = root / subset
        if not subset_dir.is_dir():
            print(f"Skip missing subset: {subset_dir}")
            continue
        images.extend(subset_dir.glob("*.jpg"))
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description="Create cropped OCR data from CCPD2019")
    parser.add_argument("--ccpd-root", required=True)
    parser.add_argument("--output", default="data/ccpd_plate_ocr")
    parser.add_argument("--max-images", type=int, default=10000)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--subsets", nargs="*",
        default=["ccpd_base", "ccpd_blur", "ccpd_challenge", "ccpd_rotate", "ccpd_tilt", "ccpd_weather"],
    )
    args = parser.parse_args()

    root = Path(args.ccpd_root)
    output = Path(args.output)
    random.seed(args.seed)
    images = collect_images(root, args.subsets)
    random.shuffle(images)
    if args.max_images > 0:
        images = images[: args.max_images]

    val_count = int(len(images) * args.val_ratio)
    rows = {"train": [], "val": []}
    skipped = 0
    for index, image_path in enumerate(images):
        split = "val" if index < val_count else "train"
        try:
            bbox, label = parse_ccpd(image_path.name)
            with Image.open(image_path) as image:
                x1, y1, x2, y2 = bbox
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(image.width, x2 + 1), min(image.height, y2 + 1)
                if x2 - x1 < 20 or y2 - y1 < 8:
                    raise ValueError("crop is too small")
                crop = image.crop((x1, y1, x2, y2)).convert("RGB")
                name = f"{image_path.parent.name}__{image_path.stem}.jpg"
                destination = output / split / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                crop.save(destination, quality=95)
            rows[split].append((destination.as_posix(), label, "ccpd"))
        except (OSError, ValueError, IndexError) as exc:
            skipped += 1
            if skipped <= 20:
                print(f"Skip {image_path}: {exc}")

    output.mkdir(parents=True, exist_ok=True)
    for split, split_rows in rows.items():
        with (output / f"{split}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image", "plate", "source"])
            writer.writerows(split_rows)

    print(f"Train crops: {len(rows['train'])}")
    print(f"Val crops: {len(rows['val'])}")
    print(f"Skipped: {skipped}")
    print(f"Output: {output.resolve()}")


if __name__ == "__main__":
    main()
