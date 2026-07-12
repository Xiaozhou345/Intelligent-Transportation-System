#!/usr/bin/env python3
"""Evaluate fixed-camera DINOv2 reference matching on paired sandbox images."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torch.nn import functional as torch_functional
from torchvision.transforms import v2

from evaluate_anomalyvfm import (
    REPO_ROOT,
    calibrate_threshold,
    find_components,
    hottest_mean,
    make_road_mask,
    read_bgr,
    write_bgr,
)


DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "sandbox_anomaly"
DEFAULT_OUTPUT_ROOT = DEFAULT_DATA_ROOT / "output_dinov2_reference"
DEFAULT_ROI_CONFIG = REPO_ROOT / "cloud" / "stream_receiver" / "illegal_parking_config.json"
DEFAULT_VEHICLE_MODEL = (
    REPO_ROOT / "cloud" / "ai_models" / "vehicle_detection" / "sandbox_vehicle_best.pt"
)


@dataclass
class PairResult:
    pair_id: str
    clean_path: str
    anomaly_path: str
    heat_score: float
    pixel_high_score: float
    predicted_anomaly: bool = False
    component_count: int = 0
    largest_component_ratio: float = 0.0
    feature_inference_ms: float = 0.0
    clean_vehicle_count: int = 0
    anomaly_vehicle_count: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--model", default="dinov2_vits14_reg")
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--image-size", type=int, default=518)
    parser.add_argument("--max-pairs", type=int, default=10)
    parser.add_argument("--local-radius", type=int, default=1)
    parser.add_argument("--normal-quantile", type=float, default=0.99)
    parser.add_argument("--pixel-quantile", type=float, default=0.995)
    parser.add_argument("--top-fraction", type=float, default=0.005)
    parser.add_argument("--min-component-ratio", type=float, default=0.0008)
    parser.add_argument("--normal-variants", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--mask-vehicles", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--vehicle-model", type=Path, default=DEFAULT_VEHICLE_MODEL)
    parser.add_argument("--vehicle-confidence", type=float, default=0.75)
    parser.add_argument("--vehicle-padding-ratio", type=float, default=0.10)
    parser.add_argument("--use-road-roi", action="store_true")
    parser.add_argument("--roi-config", type=Path, default=DEFAULT_ROI_CONFIG)
    parser.add_argument("--no-overlays", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    if args.image_size <= 0 or args.image_size % 14 != 0:
        raise ValueError("--image-size must be positive and divisible by 14")
    if args.local_radius < 0 or args.local_radius > 3:
        raise ValueError("--local-radius must be between 0 and 3")
    if not 0.5 <= args.normal_quantile < 1.0:
        raise ValueError("--normal-quantile must be in [0.5, 1.0)")
    if not 0.5 <= args.pixel_quantile < 1.0:
        raise ValueError("--pixel-quantile must be in [0.5, 1.0)")


def configure_cache() -> None:
    cache_root = REPO_ROOT / ".tools" / "model-cache"
    os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))


def load_backbone(model_name: str, image_size: int, device: torch.device):
    configure_cache()
    print(f"Loading {model_name} on {device}...")
    model = torch.hub.load(
        "facebookresearch/dinov2",
        model_name,
        trust_repo=True,
        force_reload=False,
    )
    model.eval().to(device)
    transform = v2.Compose(
        [
            v2.Resize((image_size, image_size), antialias=True),
            v2.ToImage(),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            ),
        ]
    )
    return model, transform


def load_vehicle_detector(args: argparse.Namespace):
    if not args.mask_vehicles:
        return None
    if not args.vehicle_model.exists():
        print(f"Vehicle model not found; vehicle masking disabled: {args.vehicle_model}")
        return None
    ai_models = REPO_ROOT / "cloud" / "ai_models"
    sys.path.insert(0, str(ai_models))
    os.environ.setdefault("ITS_WARMUP_MODELS", "false")
    from vehicle_detection.detector import VehicleDetector

    return VehicleDetector(
        model_path=str(args.vehicle_model),
        conf_threshold=args.vehicle_confidence,
    )


def load_road_polygon(args: argparse.Namespace) -> list[list[float]]:
    if not args.use_road_roi or not args.roi_config.exists():
        return []
    payload = json.loads(args.roi_config.read_text(encoding="utf-8"))
    polygon = payload.get("default", {}).get("anomaly_road_roi", [])
    return polygon if isinstance(polygon, list) else []


def collect_pairs(data_root: Path, limit: int) -> list[tuple[str, Path, Path]]:
    clean_root = data_root / "clean_road_pair"
    anomaly_root = data_root / "anomaly_test_pair"
    pairs: list[tuple[str, Path, Path]] = []
    for clean_path in sorted(clean_root.glob("*_clean.*")):
        pair_id = clean_path.stem.removesuffix("_clean")
        candidates = sorted(anomaly_root.glob(f"{pair_id}_anomaly.*"))
        if candidates:
            pairs.append((pair_id, clean_path, candidates[0]))
    if limit > 0:
        pairs = pairs[:limit]
    return pairs


def extract_features(
    model,
    transform,
    bgr: np.ndarray,
    device: torch.device,
) -> tuple[torch.Tensor, float]:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    tensor = transform(Image.fromarray(rgb)).unsqueeze(0).to(device)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.inference_mode(), torch.autocast(
        device_type=device.type,
        dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
    ):
        features = model.get_intermediate_layers(
            tensor,
            n=1,
            reshape=True,
            norm=True,
        )[0]
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return torch_functional.normalize(features.float(), dim=1), elapsed_ms


def local_cosine_distance(
    reference: torch.Tensor,
    candidate: torch.Tensor,
    radius: int,
) -> np.ndarray:
    batch, channels, height, width = reference.shape
    kernel_size = radius * 2 + 1
    reference_neighbors = torch_functional.unfold(
        reference,
        kernel_size=kernel_size,
        padding=radius,
    )
    reference_neighbors = reference_neighbors.reshape(
        batch,
        channels,
        kernel_size * kernel_size,
        height * width,
    )
    candidate_flat = candidate.reshape(batch, channels, height * width).unsqueeze(2)
    similarity = (reference_neighbors * candidate_flat).sum(dim=1)
    max_similarity = similarity.max(dim=1).values
    distance = (1.0 - max_similarity).clamp(min=0.0)
    return distance.reshape(height, width).detach().cpu().numpy()


def make_normal_variants(bgr: np.ndarray) -> list[np.ndarray]:
    height, width = bgr.shape[:2]
    variants = [cv2.convertScaleAbs(bgr, alpha=0.92, beta=3)]
    variants.append(cv2.convertScaleAbs(bgr, alpha=1.08, beta=-3))
    variants.append(cv2.GaussianBlur(bgr, (3, 3), 0.8))
    affine = np.float32([[1, 0, 2], [0, 1, -2]])
    variants.append(
        cv2.warpAffine(
            bgr,
            affine,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
    )
    return variants


def detect_vehicle_boxes(detector, bgr: np.ndarray) -> list[list[int]]:
    if detector is None:
        return []
    return [item["bbox"] for item in detector.detect(bgr)]


def apply_box_exclusions(
    distance: np.ndarray,
    boxes_with_shapes: list[tuple[list[int], tuple[int, int]]],
    padding_ratio: float,
) -> np.ndarray:
    filtered = distance.copy()
    target_height, target_width = filtered.shape
    for box, (source_height, source_width) in boxes_with_shapes:
        x1, y1, x2, y2 = box
        pad_x = int(round((x2 - x1) * padding_ratio))
        pad_y = int(round((y2 - y1) * padding_ratio))
        sx = target_width / max(1, source_width)
        sy = target_height / max(1, source_height)
        tx1 = max(0, int(round((x1 - pad_x) * sx)))
        ty1 = max(0, int(round((y1 - pad_y) * sy)))
        tx2 = min(target_width, int(round((x2 + pad_x) * sx)))
        ty2 = min(target_height, int(round((y2 + pad_y) * sy)))
        filtered[ty1:ty2, tx1:tx2] = 0.0
    return filtered


def upscale_distance(distance: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    return cv2.resize(distance, (width, height), interpolation=cv2.INTER_CUBIC)


def distance_metrics(
    distance: np.ndarray,
    road_mask: np.ndarray,
    top_fraction: float,
    pixel_quantile: float,
) -> tuple[float, float]:
    active = distance[road_mask > 0]
    return hottest_mean(active, top_fraction), float(np.quantile(active, pixel_quantile))


def save_pair_overlay(
    output_path: Path,
    clean: np.ndarray,
    anomaly: np.ndarray,
    distance: np.ndarray,
    road_mask: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    result: PairResult,
) -> None:
    maximum = max(float(np.quantile(distance[road_mask > 0], 0.999)), 1e-6)
    normalized = np.clip(distance / maximum, 0.0, 1.0)
    heat = cv2.applyColorMap(np.uint8(normalized * 255), cv2.COLORMAP_JET)
    overlay = anomaly.copy()
    active = road_mask > 0
    overlay[active] = cv2.addWeighted(anomaly, 0.55, heat, 0.45, 0)[active]
    for x1, y1, x2, y2 in boxes[:5]:
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 255), 3)
    label = (
        f"pair={result.pair_id} pred={int(result.predicted_anomaly)} "
        f"heat={result.heat_score:.3f} time={result.feature_inference_ms:.0f}ms"
    )
    cv2.rectangle(overlay, (0, 0), (min(overlay.shape[1], 900), 42), (0, 0, 0), -1)
    cv2.putText(overlay, label, (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)

    target_height = min(clean.shape[0], overlay.shape[0])
    clean_resized = cv2.resize(clean, (overlay.shape[1], target_height))
    overlay_resized = cv2.resize(overlay, (overlay.shape[1], target_height))
    comparison = np.hstack((clean_resized, overlay_resized))
    write_bgr(output_path, comparison)


def main() -> int:
    args = parse_args()
    validate_args(args)
    pairs = collect_pairs(args.data_root, args.max_pairs)
    if not pairs:
        raise RuntimeError("No matching clean/anomaly pairs were found")
    args.output.mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    model, transform = load_backbone(args.model, args.image_size, device)
    vehicle_detector = load_vehicle_detector(args)
    road_polygon = load_road_polygon(args)

    pair_payloads: list[dict] = []
    normal_heat_scores: list[float] = []
    normal_pixel_scores: list[float] = []
    feature_times: list[float] = []

    for index, (pair_id, clean_path, anomaly_path) in enumerate(pairs, start=1):
        clean = read_bgr(clean_path)
        anomaly = read_bgr(anomaly_path)
        if clean is None or anomaly is None:
            raise RuntimeError(f"Unable to read pair {pair_id}")

        reference_features, elapsed = extract_features(model, transform, clean, device)
        feature_times.append(elapsed)
        clean_vehicle_boxes = detect_vehicle_boxes(vehicle_detector, clean)
        anomaly_vehicle_boxes = detect_vehicle_boxes(vehicle_detector, anomaly)

        for variant in make_normal_variants(clean)[: args.normal_variants]:
            variant_features, elapsed = extract_features(model, transform, variant, device)
            feature_times.append(elapsed)
            normal_distance = local_cosine_distance(
                reference_features,
                variant_features,
                args.local_radius,
            )
            normal_distance = upscale_distance(normal_distance, clean.shape[:2])
            normal_distance = apply_box_exclusions(
                normal_distance,
                [(box, clean.shape[:2]) for box in clean_vehicle_boxes],
                args.vehicle_padding_ratio,
            )
            normal_road_mask = make_road_mask(normal_distance.shape, road_polygon)
            heat_score, pixel_score = distance_metrics(
                normal_distance,
                normal_road_mask,
                args.top_fraction,
                args.pixel_quantile,
            )
            normal_heat_scores.append(heat_score)
            normal_pixel_scores.append(pixel_score)

        anomaly_features, anomaly_elapsed = extract_features(model, transform, anomaly, device)
        feature_times.append(anomaly_elapsed)
        anomaly_distance = local_cosine_distance(
            reference_features,
            anomaly_features,
            args.local_radius,
        )
        anomaly_distance = upscale_distance(anomaly_distance, anomaly.shape[:2])
        exclusions = [
            (box, clean.shape[:2]) for box in clean_vehicle_boxes
        ] + [
            (box, anomaly.shape[:2]) for box in anomaly_vehicle_boxes
        ]
        anomaly_distance = apply_box_exclusions(
            anomaly_distance,
            exclusions,
            args.vehicle_padding_ratio,
        )
        anomaly_road_mask = make_road_mask(anomaly_distance.shape, road_polygon)
        heat_score, pixel_score = distance_metrics(
            anomaly_distance,
            anomaly_road_mask,
            args.top_fraction,
            args.pixel_quantile,
        )
        result = PairResult(
            pair_id=pair_id,
            clean_path=str(clean_path.relative_to(REPO_ROOT)),
            anomaly_path=str(anomaly_path.relative_to(REPO_ROOT)),
            heat_score=heat_score,
            pixel_high_score=pixel_score,
            feature_inference_ms=anomaly_elapsed,
            clean_vehicle_count=len(clean_vehicle_boxes),
            anomaly_vehicle_count=len(anomaly_vehicle_boxes),
        )
        pair_payloads.append(
            {
                "result": result,
                "clean": clean,
                "anomaly": anomaly,
                "distance": anomaly_distance,
                "road_mask": anomaly_road_mask,
            }
        )
        print(
            f"[{index:02d}/{len(pairs):02d}] pair={pair_id} "
            f"heat={heat_score:.4f} pixel={pixel_score:.4f} "
            f"time={anomaly_elapsed:.1f}ms vehicles={len(anomaly_vehicle_boxes)}"
        )

    heat_threshold = calibrate_threshold(normal_heat_scores, args.normal_quantile)
    pixel_threshold = calibrate_threshold(normal_pixel_scores, args.normal_quantile)
    results: list[PairResult] = []
    for payload in pair_payloads:
        result = payload["result"]
        boxes, largest_ratio = find_components(
            payload["distance"],
            payload["road_mask"],
            pixel_threshold,
            args.min_component_ratio,
        )
        result.component_count = len(boxes)
        result.largest_component_ratio = largest_ratio
        result.predicted_anomaly = bool(result.heat_score > heat_threshold and boxes)
        results.append(result)
        if not args.no_overlays:
            save_pair_overlay(
                args.output / "overlays" / f"pair_{result.pair_id}.jpg",
                payload["clean"],
                payload["anomaly"],
                payload["distance"],
                payload["road_mask"],
                boxes,
                result,
            )

    detected = sum(item.predicted_anomaly for item in results)
    normal_false_positives = sum(score > heat_threshold for score in normal_heat_scores)
    peak_memory_mb = None
    if device.type == "cuda":
        peak_memory_mb = round(torch.cuda.max_memory_allocated(device) / (1024**2), 2)
    report = {
        "model": args.model,
        "device": str(device),
        "pair_count": len(results),
        "pair_recall": round(detected / len(results), 4),
        "normal_variant_count": len(normal_heat_scores),
        "normal_variant_false_positive_rate": round(
            normal_false_positives / len(normal_heat_scores),
            4,
        ),
        "mean_feature_inference_ms": round(float(np.mean(feature_times[1:])), 2),
        "p95_feature_inference_ms": round(float(np.quantile(feature_times[1:], 0.95)), 2),
        "gpu_peak_allocated_mb": peak_memory_mb,
        "thresholds": {
            "heat": heat_threshold,
            "pixel": pixel_threshold,
            "normal_quantile": args.normal_quantile,
            "pixel_quantile": args.pixel_quantile,
            "local_radius": args.local_radius,
            "min_component_ratio": args.min_component_ratio,
        },
        "vehicle_masking": {
            "enabled": vehicle_detector is not None,
            "confidence": args.vehicle_confidence,
            "padding_ratio": args.vehicle_padding_ratio,
        },
        "road_roi": road_polygon,
        "pairs": [asdict(item) for item in results],
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nReference benchmark summary")
    print(json.dumps({key: value for key, value in report.items() if key != "pairs"}, indent=2))
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
