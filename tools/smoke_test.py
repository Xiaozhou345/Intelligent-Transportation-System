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
from unittest.mock import patch


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
    import unittest
    from cloud.stream_receiver.test_anomaly_processor import RoadAnomalyProcessorTest

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RoadAnomalyProcessorTest)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("road anomaly smoke tests failed")


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

    invalid_registration = client.post(
        "/api/register_device",
        json={"device_id": "../bad", "stream_url": "file:///etc/passwd"},
    )
    assert invalid_registration.status_code == 400

    invalid_upload = client.post(
        "/api/video/upload",
        data={
            "device_id": "../bad",
            "video": (io.BytesIO(b"not-a-video"), "payload.exe"),
        },
        content_type="multipart/form-data",
    )
    assert invalid_upload.status_code == 400


def test_edge_api_token_header() -> None:
    from edge_member_a.edge_client import post_json

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"ok"}'

    with patch('edge_member_a.edge_client.urlopen', return_value=FakeResponse()) as mocked:
        result = post_json(
            'http://127.0.0.1:5000',
            '/api/heartbeat',
            {'device_id': 'smoke_001'},
            1,
            api_token='smoke-secret',
        )

    assert result['http_status'] == 200
    request = mocked.call_args.args[0]
    assert request.headers['X-api-key'] == 'smoke-secret'


def main() -> int:
    compile_key_files()
    test_anomaly_processor()
    test_main_server_health_and_upload()
    test_edge_api_token_header()
    print("project smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
