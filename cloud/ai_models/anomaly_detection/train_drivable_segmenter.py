"""
Train the sandbox drivable-area YOLO segmentation model.

Example:
    python cloud/ai_models/anomaly_detection/train_drivable_segmenter.py ^
        --data "D:/path/to/sandbox_drivable.v1i.yolov8/data.yaml"
"""
import argparse
import os
from pathlib import Path
import tempfile

import yaml


def parse_args():
    parser = argparse.ArgumentParser(description="Train YOLO-seg for sandbox drivable area.")
    parser.add_argument("--data", default="data/sandbox_drivable/data.yaml", help="YOLO dataset yaml path.")
    parser.add_argument("--model", default="yolo11n-seg.pt", help="Base segmentation model.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--project", default=None)
    parser.add_argument("--name", default="sandbox_drivable")
    parser.add_argument("--device", default=None, help="Example: 0, cpu. Default lets ultralytics decide.")
    parser.add_argument("--resume", action="store_true", help="Resume from a previous last.pt checkpoint.")
    return parser.parse_args()


def resolve_dataset_yaml(data_path):
    """Return a YAML path whose train/val entries match the local Roboflow export."""
    data_path = Path(data_path)
    if data_path.is_dir():
        dataset_dir = data_path
        yaml_path = dataset_dir / "data.yaml"
    else:
        dataset_dir = data_path.parent
        yaml_path = data_path

    if not yaml_path.exists():
        raise SystemExit(f"Dataset yaml not found: {yaml_path}")

    train_dir = dataset_dir / "train" / "images"
    valid_dir = dataset_dir / "valid" / "images"
    if not train_dir.exists() or not valid_dir.exists():
        return yaml_path

    fixed = {
        "path": str(dataset_dir),
        "train": "train/images",
        "val": "valid/images",
        "nc": 1,
        "names": ["drivable_area"],
    }
    temp_dir = Path(tempfile.gettempdir()) / "its_drivable_training"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fixed_yaml = temp_dir / "data.yaml"
    fixed_yaml.write_text(yaml.safe_dump(fixed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return fixed_yaml


def main():
    args = parse_args()
    data_path = resolve_dataset_yaml(args.data)
    repo_root = Path(__file__).resolve().parents[3]
    yolo_config_dir = repo_root / ".ultralytics_config"
    yolo_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(yolo_config_dir))

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is not installed. Run: pip install -r cloud/requirements.txt") from exc

    project = args.project or str(repo_root / "runs" / "drivable_seg")
    model = YOLO(args.model)
    train_kwargs = {
        "data": str(data_path),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "project": project,
        "name": args.name,
        "task": "segment",
    }
    if args.device:
        train_kwargs["device"] = args.device
    if args.resume:
        train_kwargs["resume"] = True

    result = model.train(**train_kwargs)
    print("training finished")
    print(result)


if __name__ == "__main__":
    main()
