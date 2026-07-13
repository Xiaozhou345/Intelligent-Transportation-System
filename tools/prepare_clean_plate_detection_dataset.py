import argparse
import random
import shutil
from pathlib import Path

import cv2


IMAGE_SUFFIXES = [".jpg", ".jpeg", ".png", ".bmp"]


def find_image(images_dir, stem):
    for suffix in IMAGE_SUFFIXES:
        path = images_dir / f"{stem}{suffix}"
        if path.exists():
            return path
    return None


def read_valid_labels(label_path, image_shape, min_aspect, min_box_height):
    image_h, image_w = image_shape[:2]
    valid_lines = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        class_id, x, y, w, h = parts[:5]
        box_w = float(w) * image_w
        box_h = float(h) * image_h
        if box_h < min_box_height:
            continue
        if box_w / max(box_h, 1.0) < min_aspect:
            continue
        valid_lines.append(f"{class_id} {float(x):.6f} {float(y):.6f} {float(w):.6f} {float(h):.6f}")
    return valid_lines


def collect_clean_items(source_root, split, min_aspect, min_box_height, drop_rotated):
    images_dir = source_root / "images" / split
    labels_dir = source_root / "labels" / split
    items = []
    skipped = {
        "rotated": 0,
        "missing_image": 0,
        "read_failed": 0,
        "no_valid_labels": 0,
    }

    for label_path in sorted(labels_dir.glob("*.txt")):
        if drop_rotated and ("rot90" in label_path.stem or "rot270" in label_path.stem):
            skipped["rotated"] += 1
            continue

        image_path = find_image(images_dir, label_path.stem)
        if image_path is None:
            skipped["missing_image"] += 1
            continue

        image = cv2.imread(str(image_path))
        if image is None:
            skipped["read_failed"] += 1
            continue

        valid_lines = read_valid_labels(label_path, image.shape, min_aspect, min_box_height)
        if not valid_lines:
            skipped["no_valid_labels"] += 1
            continue

        items.append((image_path, valid_lines))

    return items, skipped


def write_split(output_root, split, items):
    images_dir = output_root / "images" / split
    labels_dir = output_root / "labels" / split
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    for image_path, label_lines in items:
        dst_image = images_dir / image_path.name
        dst_label = labels_dir / f"{image_path.stem}.txt"
        shutil.copy2(image_path, dst_image)
        dst_label.write_text("\n".join(label_lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Create a cleaned YOLO plate detection dataset.")
    parser.add_argument("--source-root", default="cloud/datasets/sandbox_plate")
    parser.add_argument("--output-root", default="data/sandbox_plate_detection_clean")
    parser.add_argument("--min-aspect", type=float, default=1.0)
    parser.add_argument("--min-box-height", type=float, default=20.0)
    parser.add_argument("--drop-rotated", action="store_true", default=True)
    parser.add_argument("--shuffle-seed", type=int, default=42)
    args = parser.parse_args()

    source_root = Path(args.source_root)
    output_root = Path(args.output_root)
    if not source_root.exists():
        raise FileNotFoundError(f"Source dataset not found: {source_root}")

    total = 0
    for split in ("train", "val"):
        items, skipped = collect_clean_items(
            source_root=source_root,
            split=split,
            min_aspect=args.min_aspect,
            min_box_height=args.min_box_height,
            drop_rotated=args.drop_rotated,
        )
        random.seed(args.shuffle_seed)
        random.shuffle(items)
        write_split(output_root, split, items)
        total += len(items)
        print(f"[{split}] kept: {len(items)}")
        for key, value in skipped.items():
            print(f"[{split}] skipped {key}: {value}")

    data_yaml = output_root / "data.yaml"
    data_yaml.write_text(
        f"path: {output_root.resolve().as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n\n"
        "names:\n"
        "  0: plate\n",
        encoding="utf-8",
    )
    print(f"output: {output_root}")
    print(f"total kept: {total}")
    print(f"data yaml: {data_yaml}")


if __name__ == "__main__":
    main()
