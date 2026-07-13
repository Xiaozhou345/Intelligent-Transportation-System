import argparse
from pathlib import Path
from statistics import median

import cv2


def count_images(path):
    return sum(1 for suffix in ("*.jpg", "*.jpeg", "*.png") for _ in path.glob(suffix))


def read_label_shapes(dataset_root, split):
    labels_dir = dataset_root / "labels" / split
    images_dir = dataset_root / "images" / split
    widths = []
    heights = []
    aspects = []
    missing_images = 0

    for label_path in labels_dir.glob("*.txt"):
        image_path = images_dir / f"{label_path.stem}.jpg"
        image = cv2.imread(str(image_path))
        if image is None:
            missing_images += 1
            continue

        image_h, image_w = image.shape[:2]
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            box_w = float(parts[3]) * image_w
            box_h = float(parts[4]) * image_h
            if box_w <= 0 or box_h <= 0:
                continue
            widths.append(box_w)
            heights.append(box_h)
            aspects.append(box_w / box_h)

    return widths, heights, aspects, missing_images


def print_split_report(dataset_root, split):
    images_dir = dataset_root / "images" / split
    image_paths = list(images_dir.glob("*.jpg"))
    rot90 = sum("rot90" in path.name for path in image_paths)
    rot270 = sum("rot270" in path.name for path in image_paths)
    widths, heights, aspects, missing_images = read_label_shapes(dataset_root, split)

    print(f"\n[{split}]")
    print(f"images: {len(image_paths)}")
    print(f"rot90: {rot90}")
    print(f"rot270: {rot270}")
    print(f"missing label images: {missing_images}")
    if aspects:
        print(f"bbox median width: {median(widths):.1f}")
        print(f"bbox median height: {median(heights):.1f}")
        print(f"bbox median aspect: {median(aspects):.2f}")
        print(f"bbox aspect < 1.0: {sum(value < 1.0 for value in aspects)}")


def main():
    parser = argparse.ArgumentParser(description="Audit YOLO plate dataset quality.")
    parser.add_argument(
        "--dataset-root",
        default="cloud/datasets/sandbox_plate",
        help="YOLO plate dataset root directory.",
    )
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root)
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")

    print(f"dataset: {dataset_root}")
    print_split_report(dataset_root, "train")
    print_split_report(dataset_root, "val")

    for list_name in ("train_labeled.txt", "val_labeled.txt"):
        list_path = dataset_root / list_name
        if not list_path.exists():
            continue
        lines = list_path.read_text(encoding="utf-8").splitlines()
        absolute_paths = sum(line.startswith("/") or (len(line) > 2 and line[1:3] == ":\\") for line in lines)
        print(f"\n[{list_name}]")
        print(f"lines: {len(lines)}")
        print(f"absolute paths: {absolute_paths}")


if __name__ == "__main__":
    main()
