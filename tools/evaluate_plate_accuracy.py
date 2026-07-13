import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def split_plates(value):
    plates = []
    for item in (value or "").split(";"):
        plate = item.strip().upper()
        if is_valid_plate_text(plate):
            plates.append(plate)
    return plates


def is_valid_plate_text(value):
    if len(value) not in (7, 8):
        return False
    province_chars = set("京沪津渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新")
    letters = set("ABCDEFGHJKLMNPQRSTUVWXYZ")
    tail = set("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")
    return value[0] in province_chars and value[1] in letters and all(char in tail for char in value[2:])


def levenshtein_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i] + [0] * len(right)
        for j, right_char in enumerate(right, 1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (left_char != right_char),
            )
        previous = current
    return previous[-1]


def character_accuracy(expected, predicted):
    if not expected:
        return 1.0 if not predicted else 0.0
    distance = levenshtein_distance(expected, predicted)
    return max(0.0, 1.0 - distance / len(expected))


def match_plates(expected, predicted):
    unmatched_predicted = list(predicted)
    exact_matches = []
    missed = []

    for plate in expected:
        if plate in unmatched_predicted:
            unmatched_predicted.remove(plate)
            exact_matches.append((plate, plate))
        else:
            missed.append(plate)

    fuzzy_pairs = []
    for plate in missed:
        if not unmatched_predicted:
            fuzzy_pairs.append((plate, ""))
            continue
        best = min(unmatched_predicted, key=lambda item: levenshtein_distance(plate, item))
        unmatched_predicted.remove(best)
        fuzzy_pairs.append((plate, best))

    return exact_matches, fuzzy_pairs, unmatched_predicted


def load_predictions(report_path):
    predictions_by_image = defaultdict(list)
    with report_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            predictions_by_image.setdefault(row["image"], [])
            if row.get("valid_plate") == "true":
                plate = row.get("ocr_normalized", "").strip().upper()
                if plate:
                    predictions_by_image[row["image"]].append(plate)
    return predictions_by_image


def load_labels(labels_path):
    rows = []
    with labels_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            rows.append({
                "image": row["image"],
                "expected": split_plates(row.get("expected_plates", "")),
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Evaluate plate recognition accuracy against ground truth labels.")
    parser.add_argument("--report", default="data/plate_debug_report/report.csv")
    parser.add_argument("--labels", default="data/plate_debug_labels.csv")
    parser.add_argument("--errors-output", default="data/plate_debug_report/evaluation_errors.csv")
    args = parser.parse_args()

    report_path = Path(args.report)
    labels_path = Path(args.labels)
    errors_path = Path(args.errors_output)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels not found: {labels_path}")

    predictions_by_image = load_predictions(report_path)
    labels = load_labels(labels_path)

    image_total = 0
    image_exact = 0
    expected_total = 0
    predicted_total = 0
    exact_plate_total = 0
    char_scores = []
    error_rows = []

    for row in labels:
        image = row["image"]
        expected = row["expected"]
        predicted = predictions_by_image.get(image, [])

        image_total += 1
        expected_counter = Counter(expected)
        predicted_counter = Counter(predicted)
        if expected_counter == predicted_counter:
            image_exact += 1

        expected_total += len(expected)
        predicted_total += len(predicted)
        exact_matches, fuzzy_pairs, false_positives = match_plates(expected, predicted)
        exact_plate_total += len(exact_matches)

        for plate, matched in exact_matches + fuzzy_pairs:
            char_scores.append(character_accuracy(plate, matched))

        if expected_counter != predicted_counter:
            error_rows.append({
                "image": image,
                "expected_plates": ";".join(expected),
                "predicted_plates": ";".join(predicted),
                "false_positives": ";".join(false_positives),
                "closest_mismatches": ";".join(f"{left}->{right}" for left, right in fuzzy_pairs if left != right),
            })

    precision = exact_plate_total / predicted_total if predicted_total else 0.0
    recall = exact_plate_total / expected_total if expected_total else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    image_accuracy = image_exact / image_total if image_total else 0.0
    char_accuracy = sum(char_scores) / len(char_scores) if char_scores else 0.0

    errors_path.parent.mkdir(parents=True, exist_ok=True)
    with errors_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        fieldnames = ["image", "expected_plates", "predicted_plates", "false_positives", "closest_mismatches"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(error_rows)

    print(f"images: {image_total}")
    print(f"image exact accuracy: {image_exact}/{image_total} = {image_accuracy:.2%}")
    print(f"expected plates: {expected_total}")
    print(f"predicted plates: {predicted_total}")
    print(f"plate exact precision: {exact_plate_total}/{predicted_total} = {precision:.2%}")
    print(f"plate exact recall: {exact_plate_total}/{expected_total} = {recall:.2%}")
    print(f"plate exact F1: {f1:.2%}")
    print(f"character accuracy: {char_accuracy:.2%}")
    print(f"errors: {len(error_rows)}")
    print(f"errors output: {errors_path}")


if __name__ == "__main__":
    main()
