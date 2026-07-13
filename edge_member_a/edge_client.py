"""
Member A edge client.

Responsibilities:
- Register the tablet/mobile edge device with the cloud API.
- Report heartbeat while RTMP streaming is active.
- Unregister the device after streaming stops.

The actual video capture and RTMP push are performed by the tablet RTMP app,
as required by the first-stage design.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.example.json")


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    required = ["cloud_api_base", "device_id", "scene_id"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing required config fields: {', '.join(missing)}")

    return config


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


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def post_json(base_url: str, path: str, payload: Dict[str, Any], timeout: int, api_token: str = "") -> Dict[str, Any]:
    url = f"{normalize_base_url(base_url)}{path}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["X-API-Key"] = api_token
    request = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return {
                "http_status": response.status,
                "body": json.loads(data) if data else {},
            }
    except HTTPError as error:
        data = error.read().decode("utf-8")
        try:
            body_data = json.loads(data) if data else {}
        except json.JSONDecodeError:
            body_data = {"raw": data}
        return {"http_status": error.code, "body": body_data}
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", str(error))
        raise ConnectionError(f"Cannot reach cloud API: {reason}") from error


def register_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_id": config["device_id"],
        "device_type": config.get("device_type", "huawei_tablet"),
        "stream_url": build_stream_url(config),
        "resolution": config.get("resolution", "1280x720"),
        "fps": int(config.get("fps", 15)),
        "scene_id": config["scene_id"],
        "codec": config.get("codec", "H.264"),
        "bitrate": config.get("bitrate", "2Mbps"),
        "timestamp": timestamp(),
    }


def heartbeat_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_id": config["device_id"],
        "timestamp": timestamp(),
    }


def print_response(action: str, response: Dict[str, Any]) -> None:
    print(f"[{action}] HTTP {response['http_status']}")
    print(json.dumps(response["body"], ensure_ascii=False, indent=2))


def cmd_print_config(config: Dict[str, Any]) -> int:
    printable = dict(config)
    printable["stream_url"] = build_stream_url(config)
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0


def cmd_register(config: Dict[str, Any]) -> int:
    response = post_json(
        config["cloud_api_base"],
        "/api/register_device",
        register_payload(config),
        int(config.get("request_timeout_seconds", 5)), config.get("api_token", ""),
    )
    print_response("register", response)
    return 0 if 200 <= response["http_status"] < 300 else 1


def cmd_heartbeat(config: Dict[str, Any]) -> int:
    response = post_json(
        config["cloud_api_base"],
        "/api/heartbeat",
        heartbeat_payload(config),
        int(config.get("request_timeout_seconds", 5)), config.get("api_token", ""),
    )
    print_response("heartbeat", response)
    return 0 if 200 <= response["http_status"] < 300 else 1


def cmd_watch(config: Dict[str, Any]) -> int:
    interval = int(config.get("heartbeat_interval_seconds", 10))
    timeout = int(config.get("request_timeout_seconds", 5))

    try:
        while True:
            while True:
                try:
                    register_result = post_json(
                        config["cloud_api_base"],
                        "/api/register_device",
                        register_payload(config),
                        timeout,
                        config.get("api_token", ""),
                    )
                    print_response("register", register_result)
                    if 200 <= register_result["http_status"] < 300:
                        break
                except ConnectionError as error:
                    print(f"[register] {error}")

                print(f"Register failed. Retry in {interval}s.")
                time.sleep(interval)

            print(f"Heartbeat started. Press Ctrl+C to stop. interval={interval}s")
            while True:
                time.sleep(interval)
                try:
                    response = post_json(
                        config["cloud_api_base"],
                        "/api/heartbeat",
                        heartbeat_payload(config),
                        timeout,
                        config.get("api_token", ""),
                    )
                    print_response("heartbeat", response)
                    if response["http_status"] == 404:
                        print("Device registration was lost. Registering again now.")
                        break
                except ConnectionError as error:
                    print(f"[heartbeat] {error}. Retry in {interval}s.")
    except KeyboardInterrupt:
        print("\nHeartbeat stopped by user.")
        return 0


def cmd_unregister(config: Dict[str, Any]) -> int:
    response = post_json(
        config["cloud_api_base"],
        "/api/unregister_device",
        {"device_id": config["device_id"]},
        int(config.get("request_timeout_seconds", 5)), config.get("api_token", ""),
    )
    print_response("unregister", response)
    return 0 if 200 <= response["http_status"] < 300 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Member A edge device client")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to edge config JSON. Copy config.example.json to config.json for real use.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("print-config", help="Print resolved device and stream config")
    subparsers.add_parser("register", help="Register device with cloud")
    subparsers.add_parser("heartbeat", help="Send one heartbeat")
    subparsers.add_parser("watch", help="Register then keep sending heartbeat")
    subparsers.add_parser("unregister", help="Unregister device from cloud")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(Path(args.config))
        commands = {
            "print-config": cmd_print_config,
            "register": cmd_register,
            "heartbeat": cmd_heartbeat,
            "watch": cmd_watch,
            "unregister": cmd_unregister,
        }
        return commands[args.command](config)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
