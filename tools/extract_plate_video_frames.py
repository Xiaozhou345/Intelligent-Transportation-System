from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}


def difference_hash(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (17, 16), interpolation=cv2.INTER_AREA)
    return (resized[:, 1:] > resized[:, :-1]).reshape(-1)


def hamming(left: np.ndarray, right: np.ndarray) -> int:
    return int(np.count_nonzero(left != right))


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract sharp, diverse frames from plate videos")
    parser.add_argument("--input", default="data/plate_debug_video")
    parser.add_argument("--output", default="data/plate_video_frames")
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument("--min-blur-score", type=float, default=45.0)
    parser.add_argument("--min-hash-distance", type=int, default=7)
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS)
    rows = []

    for video in videos:
        capture = cv2.VideoCapture(str(video))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(fps / args.sample_fps)))
        frame_index = read_count = kept_count = 0
        previous_hash = None
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step != 0:
                frame_index += 1
                continue
            read_count += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            frame_hash = difference_hash(frame)
            hash_distance = 256 if previous_hash is None else hamming(frame_hash, previous_hash)
            if blur_score >= args.min_blur_score and hash_distance >= args.min_hash_distance:
                timestamp_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
                name = f"{video.stem}__{int(timestamp_ms):07d}ms.jpg"
                destination = output_dir / name
                ok_write, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
                if ok_write:
                    encoded.tofile(destination)
                    rows.append((destination.as_posix(), video.name, f"{timestamp_ms / 1000:.3f}", f"{blur_score:.2f}"))
                    previous_hash = frame_hash
                    kept_count += 1
            frame_index += 1
        capture.release()
        print(f"{video.name}: sampled={read_count}, kept={kept_count}")

    with (output_dir / "frames.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image", "source_video", "timestamp_seconds", "blur_score"])
        writer.writerows(rows)
    print(f"Total kept: {len(rows)}")
    print(f"Output: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
