"""
Project smoke tests that avoid real streams and model loading where possible.

Run from the repository root:
    python tools/smoke_test.py
"""
from __future__ import annotations

import io
import os
import py_compile
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def compile_key_files() -> None:
    files = [
        "cloud/stream_receiver/main_server.py",
        "cloud/stream_receiver/video_processor.py",
        "cloud/stream_receiver/anomaly_processor.py",
        "cloud/business_logic/illegal_parking.py",
        "cloud/ai_models/vehicle_tracking/vehicle_tracker.py",
        "edge_member_a/edge_client.py",
        "edge_member_a/stream_monitor.py",
        "edge_member_a/segment_upload.py",
    ]
    for relative_path in files:
        py_compile.compile(str(REPO_ROOT / relative_path), doraise=True)


def test_anomaly_processor() -> None:
    from cloud.stream_receiver.test_anomaly_processor import main

    main()


def test_main_server_health_and_upload() -> None:
    os.environ.setdefault("ITS_ENABLE_SANDBOX_AI", "false")

    stream_receiver_dir = REPO_ROOT / "cloud" / "stream_receiver"
    if str(stream_receiver_dir) not in sys.path:
        sys.path.insert(0, str(stream_receiver_dir))

    from main_server import app

    client = app.test_client()
    health = client.get("/api/health")
    assert health.status_code == 200, health.get_data(as_text=True)
    assert health.get_json()["status"] == "ok"

    upload = client.post(
        "/api/video/upload",
        data={
            "device_id": "smoke_001",
            "scene_id": "scene_704_sandbox",
            "video": (io.BytesIO(b"smoke-video-bytes"), "smoke.mp4"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200, upload.get_data(as_text=True)
    assert upload.get_json()["status"] == "success"


def main() -> int:
    compile_key_files()
    test_anomaly_processor()
    test_main_server_health_and_upload()
    print("project smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
