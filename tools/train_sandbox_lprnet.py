from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloud.ai_models.plate_recognition.plate_recognizer import (  # noqa: E402
    BLANK_INDEX,
    CHARS,
    CHARS_DICT,
    LPRNet,
)


def augment_plate(image: np.ndarray) -> np.ndarray:
    """Apply mild degradations seen in the sandbox camera without changing text."""
    height, width = image.shape[:2]

    if random.random() < 0.35:
        max_dx = width * 0.035
        max_dy = height * 0.08
        source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        target = source + np.float32(
            [[random.uniform(-max_dx, max_dx), random.uniform(-max_dy, max_dy)] for _ in range(4)]
        )
        transform = cv2.getPerspectiveTransform(source, target)
        image = cv2.warpPerspective(
            image,
            transform,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    if random.random() < 0.35:
        scale = random.uniform(0.55, 0.88)
        reduced = cv2.resize(
            image,
            (max(32, round(width * scale)), max(10, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        image = cv2.resize(reduced, (width, height), interpolation=cv2.INTER_LINEAR)

    if random.random() < 0.45:
        alpha = random.uniform(0.78, 1.22)
        beta = random.uniform(-16, 16)
        image = np.clip(image.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

    if random.random() < 0.28:
        if random.random() < 0.5:
            image = cv2.GaussianBlur(image, (3, 3), random.uniform(0.2, 0.8))
        else:
            kernel = np.zeros((3, 3), dtype=np.float32)
            kernel[random.choice((0, 1, 2)), :] = 1 / 3
            image = cv2.filter2D(image, -1, kernel)

    if random.random() < 0.25:
        noise = np.random.normal(0, random.uniform(2.0, 7.0), image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    if random.random() < 0.25:
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, random.randint(55, 90)])
        if ok:
            decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if decoded is not None:
                image = decoded

    return image


class PlateDataset(Dataset):
    def __init__(self, csv_paths: list[Path], augment: bool = False):
        self.rows: list[tuple[Path, str, str]] = []
        self.augment = augment
        for csv_path in csv_paths:
            if not csv_path.exists():
                continue
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    image = Path(row["image"])
                    if not image.is_absolute():
                        root_relative = ROOT / image
                        image = root_relative if root_relative.exists() else csv_path.parent / image
                    label = (row.get("plate") or row.get("label") or "").strip().upper().replace("-", "")
                    if image.exists() and 7 <= len(label) <= 8 and all(char in CHARS_DICT for char in label):
                        self.rows.append((image, label, row.get("source", "sandbox")))

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        path, text, source = self.rows[index]
        # cv2.imread cannot reliably open non-ASCII Windows paths.
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Cannot read {path}")
        image = cv2.resize(image, (94, 24))
        if self.augment:
            image = augment_plate(image)
        image = image.astype(np.float32)
        image = (image - 127.5) * 0.0078125
        image = np.transpose(image, (2, 0, 1))
        label = torch.tensor([CHARS_DICT[char] for char in text], dtype=torch.long)
        return torch.from_numpy(image), label, source


def collate(batch):
    images = torch.stack([item[0] for item in batch])
    labels = [item[1] for item in batch]
    lengths = torch.tensor([len(label) for label in labels], dtype=torch.long)
    return images, torch.cat(labels), lengths


def decode(logits: torch.Tensor) -> list[str]:
    predictions = logits.argmax(dim=1).cpu().numpy()
    results = []
    for prediction in predictions:
        chars = []
        previous = -1
        for index in prediction:
            if index != BLANK_INDEX and index != previous:
                chars.append(CHARS[index])
            previous = index
        results.append("".join(chars))
    return results


def evaluate(model, loader, device):
    model.eval()
    exact = total = characters = edit_errors = 0
    with torch.no_grad():
        for images, targets, lengths in loader:
            texts = []
            offset = 0
            for length in lengths.tolist():
                texts.append("".join(CHARS[i] for i in targets[offset:offset + length].tolist()))
                offset += length
            predictions = decode(model(images.to(device)))
            for prediction, target in zip(predictions, texts):
                total += 1
                exact += prediction == target
                characters += len(target)
                edit_errors += levenshtein(prediction, target)
    return exact / max(total, 1), 1 - edit_errors / max(characters, 1)


def levenshtein(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune runtime-compatible LPRNet")
    parser.add_argument("--ccpd-dir", default="data/ccpd_plate_ocr")
    parser.add_argument("--sandbox-dir", default="data/sandbox_plate_ocr")
    parser.add_argument("--pretrained", default="cloud/ai_models/plate_recognition/Final_LPRNet_model.pth")
    parser.add_argument("--output", default="cloud/ai_models/plate_recognition/sandbox_lprnet_candidate_v2.pth")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument(
        "--sandbox-ratio",
        type=float,
        default=0.35,
        help="Target fraction of sandbox samples drawn per epoch.",
    )
    parser.add_argument(
        "--sandbox-weight",
        type=float,
        default=None,
        help="Legacy per-sample weight; overrides --sandbox-ratio when provided.",
    )
    parser.add_argument("--samples-per-epoch", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--freeze-batchnorm", action="store_true")
    parser.add_argument("--freeze-backbone", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    ccpd_dir, sandbox_dir = Path(args.ccpd_dir), Path(args.sandbox_dir)
    train_set = PlateDataset([ccpd_dir / "train.csv", sandbox_dir / "train.csv"], augment=True)
    val_set = PlateDataset([sandbox_dir / "val.csv"], augment=False)
    if not train_set or not val_set:
        raise SystemExit(f"Empty dataset: train={len(train_set)}, val={len(val_set)}")

    source_counts = Counter(source for _, _, source in train_set.rows)
    ccpd_count = source_counts.get("ccpd", 0)
    sandbox_count = len(train_set) - ccpd_count
    if ccpd_count == 0 or sandbox_count == 0:
        raise SystemExit(f"Both CCPD and sandbox samples are required: {dict(source_counts)}")
    if args.sandbox_weight is not None:
        weights = [args.sandbox_weight if source != "ccpd" else 1.0 for _, _, source in train_set.rows]
        sandbox_mass = sandbox_count * args.sandbox_weight
        effective_sandbox_ratio = sandbox_mass / (ccpd_count + sandbox_mass)
    else:
        if not 0 < args.sandbox_ratio < 1:
            raise SystemExit("--sandbox-ratio must be between 0 and 1")
        weights = [
            (1 - args.sandbox_ratio) / ccpd_count if source == "ccpd" else args.sandbox_ratio / sandbox_count
            for _, _, source in train_set.rows
        ]
        effective_sandbox_ratio = args.sandbox_ratio
    epoch_samples = args.samples_per_epoch if args.samples_per_epoch > 0 else len(train_set)
    generator = torch.Generator().manual_seed(args.seed)
    sampler = WeightedRandomSampler(weights, num_samples=epoch_samples, replacement=True, generator=generator)
    train_loader = DataLoader(train_set, batch_size=args.batch_size, sampler=sampler, collate_fn=collate, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False, collate_fn=collate, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LPRNet(8, True, len(CHARS), 0.2).to(device)
    checkpoint = torch.load(args.pretrained, map_location=device)
    model.load_state_dict(checkpoint.get("model_state_dict", checkpoint), strict=True)
    if args.freeze_backbone:
        for parameter in model.backbone.parameters():
            parameter.requires_grad = False
    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.Adam(trainable_parameters, lr=args.lr, weight_decay=1e-5)
    criterion = nn.CTCLoss(blank=BLANK_INDEX, zero_infinity=True)

    baseline_exact, baseline_char = evaluate(model, val_loader, device)
    print(f"Baseline: exact={baseline_exact:.2%}, char={baseline_char:.2%}", flush=True)
    best = baseline_exact
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Device: {device}; train_pool={len(train_set)}; "
        f"ccpd_train={ccpd_count}; sandbox_train={sandbox_count}; "
        f"sandbox_ratio={effective_sandbox_ratio:.0%}; "
        f"samples_per_epoch={epoch_samples}; sandbox_val={len(val_set)}",
        flush=True,
    )
    for epoch in range(1, args.epochs + 1):
        model.train()
        if args.freeze_backbone:
            model.backbone.eval()
        if args.freeze_batchnorm:
            for module in model.modules():
                if isinstance(module, nn.modules.batchnorm._BatchNorm):
                    module.eval()
        loss_sum = samples = 0
        for images, targets, lengths in train_loader:
            images, targets, lengths = images.to(device), targets.to(device), lengths.to(device)
            optimizer.zero_grad()
            logits = model(images)
            log_probs = logits.log_softmax(1).permute(2, 0, 1)
            input_lengths = torch.full((images.size(0),), logits.size(2), dtype=torch.long, device=device)
            loss = criterion(log_probs, targets, input_lengths, lengths)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * images.size(0)
            samples += images.size(0)
        exact, char_acc = evaluate(model, val_loader, device)
        print(f"Epoch {epoch}/{args.epochs}: loss={loss_sum / samples:.4f}, exact={exact:.2%}, char={char_acc:.2%}", flush=True)
        if exact > best or (exact == best and char_acc > baseline_char):
            best = exact
            baseline_char = char_acc
            torch.save(model.state_dict(), output)
            print(f"Saved: {output}", flush=True)


if __name__ == "__main__":
    main()
