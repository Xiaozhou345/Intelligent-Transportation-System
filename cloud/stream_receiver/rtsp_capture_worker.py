"""Isolated OpenCV capture worker used by the main AI service.

The process writes raw BGR frames to stdout. Keeping FFmpeg/OpenCV in a
separate process lets the parent terminate a capture that is stuck inside a
native read call without freezing Flask, Socket.IO, or the inference models.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import time

import cv2


FRAME_HEADER = struct.Struct("<4sIIId")
FRAME_MAGIC = b"ITSF"


def open_capture(url: str, open_timeout_ms: int, read_timeout_ms: int):
    if url.lower().startswith("rtsp://"):
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

    params = []
    for prop, value in (
        (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), open_timeout_ms),
        (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), read_timeout_ms),
    ):
        if prop is not None:
            params.extend([prop, int(value)])

    try:
        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    except (TypeError, cv2.error):
        capture = cv2.VideoCapture(url)

    if capture.isOpened():
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--open-timeout-ms", type=int, default=5000)
    parser.add_argument("--read-timeout-ms", type=int, default=5000)
    parser.add_argument("--read-failures", type=int, default=5)
    parser.add_argument("--failure-grace-seconds", type=float, default=6.0)
    parser.add_argument("--send-every", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture = open_capture(args.url, args.open_timeout_ms, args.read_timeout_ms)
    if not capture.isOpened():
        print("open_failed", file=sys.stderr, flush=True)
        capture.release()
        return 2

    print("connected", file=sys.stderr, flush=True)
    output = sys.stdout.buffer
    failures = 0
    failure_started_at = None
    frame_number = 0
    send_every = max(1, args.send_every)

    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None or frame.size == 0:
                failures += 1
                if failure_started_at is None:
                    failure_started_at = time.monotonic()
                failure_duration = time.monotonic() - failure_started_at
                if (
                    failures >= max(1, args.read_failures)
                    and failure_duration >= max(1.0, args.failure_grace_seconds)
                ):
                    print("read_failed", file=sys.stderr, flush=True)
                    return 3
                time.sleep(0.1)
                continue

            failures = 0
            failure_started_at = None
            frame_number += 1
            if frame_number % send_every != 0:
                continue

            height, width = frame.shape[:2]
            channels = 1 if frame.ndim == 2 else frame.shape[2]
            captured_at = time.monotonic()
            output.write(FRAME_HEADER.pack(FRAME_MAGIC, width, height, channels, captured_at))
            output.write(frame.tobytes(order="C"))
            output.flush()
    except (BrokenPipeError, OSError):
        return 0
    except Exception as exc:
        print(f"capture_error:{exc}", file=sys.stderr, flush=True)
        return 4
    finally:
        capture.release()


if __name__ == "__main__":
    raise SystemExit(main())
