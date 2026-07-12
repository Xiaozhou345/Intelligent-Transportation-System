from __future__ import annotations

import argparse
import csv
import random
import sys
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
            if random.random() < 0.4:
                alpha = random.uniform(0.75, 1.25)
                beta = random.uniform(-18, 18)
                image = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
            if random.random() < 0.25:
                try:
                    image = cv2.GaussianBlur(np.ascontiguousarray(image), (3, 3), 0)
                except cv2.error:
                    pass
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
    parser.add_argument("--output", default="cloud/ai_models/plate_recognition/sandbox_lprnet_best.pth")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--sandbox-weight", type=float, default=12.0)
    parser.add_argument("--samples-per-epoch", type=int, default=1200)
    parser.add_argument("--freeze-batchnorm", action="store_true")
    parser.add_argument("--freeze-backbone", action="store_true")
    args = parser.parse_args()

    ccpd_dir, sandbox_dir = Path(args.ccpd_dir), Path(args.sandbox_dir)
    train_set = PlateDataset([ccpd_dir / "train.csv", sandbox_dir / "train.csv"], augment=True)
    val_set = PlateDataset([sandbox_dir / "val.csv"], augment=False)
    if not train_set or not val_set:
        raise SystemExit(f"Empty dataset: train={len(train_set)}, val={len(val_set)}")

    weights = [args.sandbox_weight if source != "ccpd" else 1.0 for _, _, source in train_set.rows]
    epoch_samples = min(args.samples_per_epoch, len(train_set)) if args.samples_per_epoch > 0 else len(train_set)
    sampler = WeightedRandomSampler(weights, num_samples=epoch_samples, replacement=True)
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
