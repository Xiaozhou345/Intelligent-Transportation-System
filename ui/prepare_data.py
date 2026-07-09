import os
import random
from config import CLPD_CSV, CLPD_ROOT


def split_dataset(train_ratio=0.7, val_ratio=0.15, test_ratio=0.15):
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 0.01, "Ratios must sum to 1"

    csv_path = CLPD_CSV
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    try:
        with open(csv_path, 'r', encoding='gbk') as f:
            lines = f.readlines()
    except:
        with open(csv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    header = lines[0].strip()
    records = []
    for line in lines[1:]:
        line = line.strip()
        if line:
            parts = line.split(',')
            if len(parts) >= 10:
                img_name = parts[0]
                label = parts[-1]
                records.append((img_name, label))

    random.seed(42)
    random.shuffle(records)

    total = len(records)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)

    train_records = records[:train_end]
    val_records = records[train_end:val_end]
    test_records = records[val_end:]

    output_dir = os.path.join(CLPD_ROOT, 'splits')
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, 'train.txt'), 'w', encoding='utf-8') as f:
        for img_name, label in train_records:
            f.write(f"{img_name},{label}\n")

    with open(os.path.join(output_dir, 'val.txt'), 'w', encoding='utf-8') as f:
        for img_name, label in val_records:
            f.write(f"{img_name},{label}\n")

    with open(os.path.join(output_dir, 'test.txt'), 'w', encoding='utf-8') as f:
        for img_name, label in test_records:
            f.write(f"{img_name},{label}\n")

    print(f"Total records: {total}")
    print(f"Train records: {len(train_records)}")
    print(f"Val records: {len(val_records)}")
    print(f"Test records: {len(test_records)}")
    print(f"Dataset split completed. Output directory: {output_dir}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Split CLPD dataset into train/val/test')
    parser.add_argument('--train_ratio', type=float, default=0.7, help='Train ratio')
    parser.add_argument('--val_ratio', type=float, default=0.15, help='Validation ratio')
    parser.add_argument('--test_ratio', type=float, default=0.15, help='Test ratio')
    args = parser.parse_args()

    split_dataset(args.train_ratio, args.val_ratio, args.test_ratio)