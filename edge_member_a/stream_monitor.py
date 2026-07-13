"""
Stream pull and transport status monitor for Member A.
This script verifies the full edge-to-cloud transmission path:
- cloud HTTP API health
- registered device status
- stream TCP port reachability
- real RTSP/RTMP frame pulling with OpenCV
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.example.json")


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_stream_url(config: Dict[str, Any]) -> str:
    if config.get("stream_url"):
        return config["stream_url"]

    server = config.get("rtmp_server")
    port = config.get("rtmp_port", 1935)
    app = config.get("rtmp_app", "live").strip("/")
    device_id = config["device_id"]
    if not server:
        raise ValueError("Set rtmp_server or stream_url in config.")
    return f"rtmp://{server}:{port}/{app}/{device_id}"


def parse_stream_endpoint(stream_url: str, config: Dict[str, Any]) -> Tuple[Optional[str], Optional[int], str]:
    parsed = urlparse(stream_url)
    scheme = parsed.scheme or "stream"
    if parsed.hostname and parsed.port:
        return parsed.hostname, parsed.port, scheme
    if parsed.hostname and scheme == "rtsp":
        return parsed.hostname, 8554, scheme
    if parsed.hostname and scheme == "rtmp":
        return parsed.hostname, 1935, scheme
    if config.get("rtmp_server"):
        return config.get("rtmp_server"), int(config.get("rtmp_port", 1935)), "rtmp"
    return None, None, scheme


def http_get_json(url: str, timeout: int) -> Dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return {
                "ok": 200 <= response.status < 300,
                "status": response.status,
                "body": json.loads(data) if data else {},
            }
    except HTTPError as error:
        data = error.read().decode("utf-8")
        try:
            body = json.loads(data) if data else {}
        except json.JSONDecodeError:
            body = {"raw": data}
        return {"ok": False, "status": error.code, "body": body}
    except URLError as error:
        return {"ok": False, "status": None, "error": str(error.reason)}
    except TimeoutError:
        return {"ok": False, "status": None, "error": "timeout"}


def check_tcp(host: str, port: int, timeout: int) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return {"ok": True, "latency_ms": latency_ms}
    except OSError as error:
        return {"ok": False, "error": str(error)}


def pull_frames(stream_url: str, frame_count: int, timeout_seconds: int) -> Dict[str, Any]:
    try:
        import cv2
    except ImportError:
        return {
            "ok": False,
            "error": "opencv-python is not installed. Install cloud requirements first.",
        }

    capture = cv2.VideoCapture(stream_url)
    if not capture.isOpened():
        capture.release()
        return {"ok": False, "error": f"cannot open stream: {stream_url}"}

    frames = 0
    width: Optional[int] = None
    height: Optional[int] = None
    started = time.perf_counter()
    last_frame_at: Optional[float] = None

    while frames < frame_count and time.perf_counter() - started < timeout_seconds:
        ok, frame = capture.read()
        if not ok:
            time.sleep(0.05)
            continue

        frames += 1
        last_frame_at = time.perf_counter()
        height, width = frame.shape[:2]

    capture.release()
    elapsed = time.perf_counter() - started
    measured_fps = round(frames / elapsed, 2) if elapsed > 0 else 0

    return {
        "ok": frames > 0,
        "frames": frames,
        "target_frames": frame_count,
        "elapsed_seconds": round(elapsed, 2),
        "measured_fps": measured_fps,
        "width": width,
        "height": height,
        "last_frame_age_seconds": round(time.perf_counter() - last_frame_at, 2)
        if last_frame_at
        else None,
    }


def print_result(name: str, result: Dict[str, Any]) -> None:
    status = "OK" if result.get("ok") else "FAIL"
    print(f"[{status}] {name}")
    detail = {key: value for key, value in result.items() if key != "ok"}
    if detail:
        print(json.dumps(detail, ensure_ascii=False, indent=2))


def run_once(config: Dict[str, Any], frame_count: int, timeout: int) -> int:
    base_url = normalize_base_url(config["cloud_api_base"])
    device_id = config["device_id"]
    stream_url = build_stream_url(config)
    stream_host, stream_port, stream_scheme = parse_stream_endpoint(stream_url, config)

    print("=" * 60)
    print(f"Monitor time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cloud API: {base_url}")
    print(f"Stream URL: {stream_url}")
    print("=" * 60)

    health = http_get_json(f"{base_url}/api/health", timeout)
    device = http_get_json(f"{base_url}/api/device/{device_id}", timeout)
    tcp = check_tcp(stream_host, stream_port, timeout) if stream_host and stream_port else {"ok": False, "error": "missing stream host"}
    frames = pull_frames(stream_url, frame_count, timeout)

    print_result("cloud api health", health)
    print_result("device registration status", device)
    print_result(f"{stream_scheme} tcp connectivity", tcp)
    print_result("stream frame pulling", frames)

    return 0 if all(item.get("ok") for item in [health, device, tcp, frames]) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor RTSP/RTMP video transmission status")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to edge config JSON")
    parser.add_argument("--frames", type=int, default=30, help="Number of frames to pull")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    parser.add_argument("--watch", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=10, help="Watch interval in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(Path(args.config))
        if args.watch:
            while True:
                run_once(config, args.frames, args.timeout)
                time.sleep(args.interval)
        return run_once(config, args.frames, args.timeout)
    except KeyboardInterrupt:
        print("\nMonitor stopped by user.")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
