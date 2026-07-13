#!/usr/bin/env python3
"""Offline AnomalyVFM benchmark for the sandbox road scene.

The script is intentionally independent from the live video pipeline. It uses
clean road images to calibrate thresholds, treats normal vehicle images as a
false-positive holdout set, and measures recall on known obstacle images.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import torch
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "sandbox_anomaly"
DEFAULT_OUTPUT_ROOT = DEFAULT_DATA_ROOT / "output_anomalyvfm"
DEFAULT_CONFIG = REPO_ROOT / "cloud" / "stream_receiver" / "illegal_parking_config.json"
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass
class Prediction:
    group: str
    expected_anomaly: bool
    path: str
    image_score: float
    heat_score: float
    pixel_high_score: float
    inference_ms: float
    predicted_anomaly: bool = False
    component_count: int = 0
    largest_component_ratio: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--model",
        default="anomalyvfm_dinov2",
        choices=(
            "anomalyvfm_dinov2",
            "anomalyvfm_radio",
            "anomalyvfm_clip",
            "anomalyvfm_siglip2",
        ),
    )
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument(
        "--max-per-group",
        type=int,
        default=12,
        help="Maximum images from each group; 0 means all images.",
    )
    parser.add_argument(
        "--normal-quantile",
        type=float,
        default=0.99,
        help="Quantile of clean-road scores used as the decision threshold.",
    )
    parser.add_argument(
        "--pixel-quantile",
        type=float,
        default=0.995,
        help="Per-image ROI pixel quantile used to calibrate mask threshold.",
    )
    parser.add_argument(
        "--top-fraction",
        type=float,
        default=0.005,
        help="Fraction of hottest ROI pixels averaged into the heat score.",
    )
    parser.add_argument(
        "--min-component-ratio",
        type=float,
        default=0.0005,
        help="Minimum connected-component area divided by road ROI area.",
    )
    parser.add_argument("--roi-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--no-road-roi",
        action="store_true",
        help="Evaluate the entire frame instead of the configured road polygon.",
    )
    parser.add_argument(
        "--no-overlays",
        action="store_true",
        help="Skip heatmap overlay generation.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    for name in ("normal_quantile", "pixel_quantile"):
        value = getattr(args, name)
        if not 0.5 <= value < 1.0:
            raise ValueError(f"--{name.replace('_', '-')} must be in [0.5, 1.0)")
    if not 0.0 < args.top_fraction <= 0.25:
        raise ValueError("--top-fraction must be in (0, 0.25]")
    if not 0.0 < args.min_component_ratio < 0.25:
        raise ValueError("--min-component-ratio must be in (0, 0.25)")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")


def configure_model_cache() -> None:
    cache_root = REPO_ROOT / ".tools" / "model-cache"
    os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))
    os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def load_model(model_name: str, device: torch.device):
    configure_model_cache()
    print(f"Loading {model_name} on {device}; the first run downloads model weights...")
    model = torch.hub.load(
        "MaticFuc/AnomalyVFM",
        model_name,
        trust_repo=True,
        force_reload=False,
    )
    model.eval().to(device)
    transform = model.model.get_img_transform()
    return model, transform


def list_images(directories: Iterable[Path]) -> list[Path]:
    images: list[Path] = []
    for directory in directories:
        if not directory.exists():
            continue
        images.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    return sorted(set(images))


def evenly_sample(items: list[Path], limit: int) -> list[Path]:
    if limit <= 0 or len(items) <= limit:
        return items
    indices = np.linspace(0, len(items) - 1, num=limit, dtype=np.int64)
    return [items[int(index)] for index in indices]


def build_groups(data_root: Path, limit: int) -> dict[str, tuple[bool, list[Path]]]:
    groups = {
        "clean": (
            False,
            list_images((data_root / "clean_road", data_root / "clean_road_pair")),
        ),
        "vehicle": (False, list_images((data_root / "vehicle_test",))),
        "anomaly": (
            True,
            list_images((data_root / "anomaly_test", data_root / "anomaly_test_pair")),
        ),
    }
    return {
        name: (expected, evenly_sample(paths, limit))
        for name, (expected, paths) in groups.items()
    }


def load_normalized_road_polygon(config_path: Path) -> list[list[float]]:
    if not config_path.exists():
        return []
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    polygon = payload.get("default", {}).get("anomaly_road_roi", [])
    if not isinstance(polygon, list) or len(polygon) < 3:
        return []
    return polygon


def make_road_mask(
    shape: tuple[int, int],
    normalized_polygon: list[list[float]],
) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    if not normalized_polygon:
        mask.fill(255)
        return mask
    points = np.asarray(
        [
            (
                int(round(float(x) * (width - 1))),
                int(round(float(y) * (height - 1))),
            )
            for x, y in normalized_polygon
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [points], 255)
    return mask


def read_bgr(path: Path) -> np.ndarray | None:
    """Read an image without relying on OpenCV's Unicode path handling."""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def write_bgr(path: Path, image: np.ndarray) -> None:
    """Write an image to a path that may contain non-ASCII characters."""
    suffix = path.suffix.lower() or ".jpg"
    success, encoded = cv2.imencode(suffix, image)
    if not success:
        raise RuntimeError(f"Unable to encode image: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def hottest_mean(values: np.ndarray, fraction: float) -> float:
    flat = values.reshape(-1)
    if flat.size == 0:
        return 0.0
    count = max(1, int(round(flat.size * fraction)))
    start = flat.size - count
    hottest = np.partition(flat, start)[start:]
    return float(np.mean(hottest))


def infer_image(
    model,
    transform,
    image_path: Path,
    device: torch.device,
    polygon: list[list[float]],
    top_fraction: float,
    pixel_quantile: float,
) -> tuple[Prediction, np.ndarray, np.ndarray]:
    bgr = read_bgr(image_path)
    if bgr is None:
        raise RuntimeError(f"Unable to read image: {image_path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    tensor = transform(Image.fromarray(rgb)).unsqueeze(0).to(device)

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.inference_mode():
        image_score, anomaly_mask = model(tensor)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    inference_ms = (time.perf_counter() - started) * 1000.0

    mask = anomaly_mask.detach().float().squeeze().cpu().numpy()
    mask = cv2.resize(mask, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    mask = np.clip(mask, 0.0, 1.0)
    road_mask = make_road_mask(mask.shape, polygon)
    road_values = mask[road_mask > 0]

    prediction = Prediction(
        group="",
        expected_anomaly=False,
        path=str(image_path.relative_to(REPO_ROOT)),
        image_score=float(image_score.detach().float().max().cpu().item()),
        heat_score=hottest_mean(road_values, top_fraction),
        pixel_high_score=float(np.quantile(road_values, pixel_quantile)),
        inference_ms=inference_ms,
    )
    return prediction, mask, bgr


def calibrate_threshold(values: list[float], quantile: float) -> float:
    if not values:
        raise RuntimeError("No clean-road values are available for threshold calibration")
    return float(np.quantile(np.asarray(values, dtype=np.float32), quantile))


def find_components(
    mask: np.ndarray,
    road_mask: np.ndarray,
    pixel_threshold: float,
    min_component_ratio: float,
) -> tuple[list[tuple[int, int, int, int]], float]:
    binary = np.zeros_like(road_mask)
    binary[(mask >= pixel_threshold) & (road_mask > 0)] = 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    roi_area = max(1, int(np.count_nonzero(road_mask)))
    min_area = max(12, int(round(roi_area * min_component_ratio)))
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    boxes: list[tuple[int, int, int, int]] = []
    largest_ratio = 0.0
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if int(area) < min_area:
            continue
        boxes.append((int(x), int(y), int(x + width), int(y + height)))
        largest_ratio = max(largest_ratio, float(area) / roi_area)
    boxes.sort(key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), reverse=True)
    return boxes, largest_ratio


def save_overlay(
    output_path: Path,
    bgr: np.ndarray,
    mask: np.ndarray,
    road_mask: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    prediction: Prediction,
) -> None:
    heat = cv2.applyColorMap(np.uint8(np.clip(mask * 255.0, 0, 255)), cv2.COLORMAP_JET)
    overlay = bgr.copy()
    active = road_mask > 0
    overlay[active] = cv2.addWeighted(bgr, 0.55, heat, 0.45, 0)[active]
    for x1, y1, x2, y2 in boxes[:5]:
        color = (0, 0, 255) if prediction.predicted_anomaly else (0, 200, 255)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 3)
    label = (
        f"expected={int(prediction.expected_anomaly)} "
        f"pred={int(prediction.predicted_anomaly)} "
        f"heat={prediction.heat_score:.3f} "
        f"time={prediction.inference_ms:.0f}ms"
    )
    cv2.rectangle(overlay, (0, 0), (min(overlay.shape[1], 900), 42), (0, 0, 0), -1)
    cv2.putText(overlay, label, (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    write_bgr(output_path, overlay)


def summarize(predictions: list[Prediction]) -> dict:
    summary: dict[str, dict] = {}
    for group in sorted({item.group for item in predictions}):
        items = [item for item in predictions if item.group == group]
        positives = sum(item.predicted_anomaly for item in items)
        expected = bool(items[0].expected_anomaly) if items else False
        summary[group] = {
            "count": len(items),
            "expected_anomaly": expected,
            "predicted_anomaly_count": positives,
            "recall" if expected else "false_positive_rate": (
                round(positives / len(items), 4) if items else None
            ),
            "mean_inference_ms": (
                round(float(np.mean([item.inference_ms for item in items])), 2)
                if items
                else None
            ),
            "p95_inference_ms": (
                round(float(np.quantile([item.inference_ms for item in items], 0.95)), 2)
                if items
                else None
            ),
        }
    return summary


def write_reports(
    output_root: Path,
    predictions: list[Prediction],
    report: dict,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_root / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(predictions[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(item) for item in predictions)


def main() -> int:
    args = parse_args()
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=True)

    polygon = [] if args.no_road_roi else load_normalized_road_polygon(args.roi_config)
    groups = build_groups(args.data_root, args.max_per_group)
    for name, (_, paths) in groups.items():
        print(f"{name}: {len(paths)} images")
    if not groups["clean"][1] or not groups["anomaly"][1]:
        raise RuntimeError("Both clean and anomaly image groups are required")

    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    model, transform = load_model(args.model, device)

    predictions: list[Prediction] = []
    masks: dict[str, np.ndarray] = {}
    source_images: dict[str, np.ndarray] = {}
    total = sum(len(paths) for _, paths in groups.values())
    completed = 0

    for group, (expected_anomaly, paths) in groups.items():
        for path in paths:
            completed += 1
            prediction, mask, bgr = infer_image(
                model=model,
                transform=transform,
                image_path=path,
                device=device,
                polygon=polygon,
                top_fraction=args.top_fraction,
                pixel_quantile=args.pixel_quantile,
            )
            prediction.group = group
            prediction.expected_anomaly = expected_anomaly
            predictions.append(prediction)
            masks[prediction.path] = mask
            source_images[prediction.path] = bgr
            print(
                f"[{completed:03d}/{total:03d}] {group:<7} "
                f"heat={prediction.heat_score:.4f} "
                f"score={prediction.image_score:.4f} "
                f"time={prediction.inference_ms:.1f}ms {path.name}"
            )

    clean = [item for item in predictions if item.group == "clean"]
    heat_threshold = calibrate_threshold(
        [item.heat_score for item in clean],
        args.normal_quantile,
    )
    pixel_threshold = calibrate_threshold(
        [item.pixel_high_score for item in clean],
        args.normal_quantile,
    )

    for prediction in predictions:
        bgr = source_images[prediction.path]
        mask = masks[prediction.path]
        road_mask = make_road_mask(mask.shape, polygon)
        boxes, largest_ratio = find_components(
            mask,
            road_mask,
            pixel_threshold,
            args.min_component_ratio,
        )
        prediction.component_count = len(boxes)
        prediction.largest_component_ratio = largest_ratio
        prediction.predicted_anomaly = bool(
            prediction.heat_score > heat_threshold and boxes
        )
        if not args.no_overlays:
            relative = Path(prediction.path)
            overlay_name = f"{relative.parent.name}_{relative.stem}.jpg"
            save_overlay(
                args.output / "overlays" / prediction.group / overlay_name,
                bgr,
                mask,
                road_mask,
                boxes,
                prediction,
            )

    group_summary = summarize(predictions)
    gpu_peak_mb = None
    if device.type == "cuda":
        gpu_peak_mb = round(torch.cuda.max_memory_allocated(device) / (1024**2), 2)
    report = {
        "model": args.model,
        "device": str(device),
        "torch_version": torch.__version__,
        "thresholds": {
            "heat": heat_threshold,
            "pixel": pixel_threshold,
            "normal_quantile": args.normal_quantile,
            "pixel_quantile": args.pixel_quantile,
            "top_fraction": args.top_fraction,
            "min_component_ratio": args.min_component_ratio,
        },
        "road_roi": polygon,
        "gpu_peak_allocated_mb": gpu_peak_mb,
        "groups": group_summary,
        "predictions": [asdict(item) for item in predictions],
    }
    write_reports(args.output, predictions, report)

    print("\nBenchmark summary")
    print(json.dumps(group_summary, ensure_ascii=False, indent=2))
    print(f"Heat threshold: {heat_threshold:.5f}")
    print(f"Pixel threshold: {pixel_threshold:.5f}")
    if gpu_peak_mb is not None:
        print(f"Peak CUDA memory allocated: {gpu_peak_mb:.1f} MB")
    print(f"Report: {args.output / 'report.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
