from pathlib import Path
from PIL import Image
import argparse
import random
import shutil


def parse_ccpd_bbox(filename):
    """
    Parse CCPD filename format:
    area-tilt-bbox-corners-plate-brightness-blur.jpg

    bbox field example: 154&383_386&473
    """
    stem = Path(filename).stem
    parts = stem.split("-")
    if len(parts) < 3:
        raise ValueError(f"Invalid CCPD filename: {filename}")

    bbox_part = parts[2]
    left_top, right_bottom = bbox_part.split("_")
    x1, y1 = map(int, left_top.split("&"))
    x2, y2 = map(int, right_bottom.split("&"))

    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def bbox_to_yolo(x1, y1, x2, y2, img_w, img_h):
    x_center = ((x1 + x2) / 2) / img_w
    y_center = ((y1 + y2) / 2) / img_h
    width = (x2 - x1) / img_w
    height = (y2 - y1) / img_h
    return x_center, y_center, width, height


def collect_images(src_root, subsets):
    image_paths = []
    subset_names = subsets or [p.name for p in src_root.iterdir() if p.is_dir() and p.name.startswith("ccpd_")]
    for subset in subset_names:
        subset_dir = src_root / subset
        if not subset_dir.exists():
            print(f"Skip missing subset: {subset_dir}")
            continue
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
            image_paths.extend(subset_dir.glob(ext))
    return image_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ccpd-root", required=True, help="Path to CCPD2019 root")
    parser.add_argument("--output", required=True, help="Output YOLO dataset directory")
    parser.add_argument("--max-images", type=int, default=30000)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--subsets",
        nargs="*",
        default=["ccpd_base", "ccpd_blur", "ccpd_challenge", "ccpd_rotate", "ccpd_tilt", "ccpd_weather"],
        help="CCPD subsets to sample from",
    )
    args = parser.parse_args()

    src_root = Path(args.ccpd_root)
    out_root = Path(args.output)

    image_paths = collect_images(src_root, args.subsets)
    image_paths = [p for p in image_paths if "-" in p.stem]

    random.seed(args.seed)
    random.shuffle(image_paths)

    if args.max_images > 0:
        image_paths = image_paths[: args.max_images]

    val_count = int(len(image_paths) * args.val_ratio)
    val_paths = set(image_paths[:val_count])

    for split in ("train", "val"):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    ok = 0
    bad = 0
    split_counts = {"train": 0, "val": 0}

    for img_path in image_paths:
        split = "val" if img_path in val_paths else "train"
        try:
            x1, y1, x2, y2 = parse_ccpd_bbox(img_path.name)
            with Image.open(img_path) as img:
                img_w, img_h = img.size

            if x2 <= x1 or y2 <= y1:
                raise ValueError("Invalid bbox size")

            x, y, w, h = bbox_to_yolo(x1, y1, x2, y2, img_w, img_h)
            if not all(0 <= v <= 1 for v in (x, y, w, h)) or w <= 0 or h <= 0:
                raise ValueError("YOLO bbox out of range")

            # Prefix subset name to avoid filename collisions across CCPD subsets.
            dst_name = f"{img_path.parent.name}__{img_path.name}"
            dst_img = out_root / "images" / split / dst_name
            dst_lab = out_root / "labels" / split / f"{Path(dst_name).stem}.txt"

            shutil.copy2(img_path, dst_img)
            dst_lab.write_text(f"0 {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n")
            ok += 1
            split_counts[split] += 1
        except Exception as exc:
            bad += 1
            if bad <= 20:
                print(f"Skip {img_path}: {exc}")

    data_wsl = out_root / "data_wsl.yaml"
    data_wsl.write_text(
        f"path: {out_root}\n"
        "train: images/train\n"
        "val: images/val\n\n"
        "names:\n"
        "  0: plate\n"
    )

    print(f"Converted: {ok}")
    print(f"Skipped: {bad}")
    print(f"Train images: {split_counts['train']}")
    print(f"Val images: {split_counts['val']}")
    print(f"Output: {out_root}")
    print(f"Data yaml: {data_wsl}")


if __name__ == "__main__":
    main()
