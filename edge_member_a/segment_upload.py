"""
Fallback HTTP video segment uploader for Member A.

SRT/RTMP real-time streaming through cloud MediaMTX is the primary transport.
This script is reserved for the documented degraded mode: upload short video
files when real-time streaming is unstable.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.example.json")


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def encode_multipart(fields: Dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----edge-member-a-{uuid.uuid4().hex}"
    parts = []

    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def upload(config: Dict[str, Any], video_path: Path) -> Dict[str, Any]:
    if not video_path.exists():
        raise FileNotFoundError(f"Video segment not found: {video_path}")

    base_url = config["cloud_api_base"].rstrip("/")
    endpoint = config.get("upload_endpoint", "/api/video/upload")
    url = f"{base_url}{endpoint}"
    fields = {
        "device_id": config["device_id"],
        "scene_id": config.get("scene_id", "scene_704_sandbox"),
        "timestamp": timestamp(),
        "resolution": config.get("resolution", "1280x720"),
        "fps": str(config.get("fps", 15)),
        "codec": config.get("codec", "H.264"),
    }
    body, boundary = encode_multipart(fields, "video", video_path)

    request = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=int(config.get("request_timeout_seconds", 5))) as response:
            data = response.read().decode("utf-8")
            return {"http_status": response.status, "body": json.loads(data) if data else {}}
    except HTTPError as error:
        data = error.read().decode("utf-8")
        try:
            body_data = json.loads(data) if data else {}
        except json.JSONDecodeError:
            body_data = {"raw": data}
        return {"http_status": error.code, "body": body_data}
    except URLError as error:
        raise ConnectionError(f"Cannot reach cloud API: {error.reason}") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload fallback video segment")
    parser.add_argument("video", help="Path to short video segment")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to edge config JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(Path(args.config))
        response = upload(config, Path(args.video))
        print(f"[upload] HTTP {response['http_status']}")
        print(json.dumps(response["body"], ensure_ascii=False, indent=2))
        return 0 if 200 <= response["http_status"] < 300 else 1
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
