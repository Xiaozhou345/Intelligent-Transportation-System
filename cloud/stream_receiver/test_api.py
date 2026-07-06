"""
HTTP API测试脚本
模拟边端设备注册和心跳上报
"""
import requests
import json
from datetime import datetime


# 云端API地址（测试时用localhost，实际使用时改为你的电脑IP）
BASE_URL = "http://localhost:5000"


def test_health_check():
    """测试健康检查接口"""
    print("1. 测试健康检查接口...")
    response = requests.get(f"{BASE_URL}/api/health")
    print(f"   响应: {response.json()}")
    print()


def test_register_device():
    """测试设备注册接口"""
    print("2. 测试设备注册接口...")

    device_data = {
        "device_id": "mobile_001",
        "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
        "resolution": "1280x720",
        "fps": 15,
        "scene_id": "scene_704_sandbox",
        "codec": "H.264",
        "bitrate": "2Mbps",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    response = requests.post(
        f"{BASE_URL}/api/register_device",
        json=device_data,
        headers={"Content-Type": "application/json"}
    )

    print(f"   请求数据: {json.dumps(device_data, indent=2, ensure_ascii=False)}")
    print(f"   响应: {response.json()}")
    print()


def test_get_devices():
    """测试获取所有设备接口"""
    print("3. 测试获取所有设备接口...")
    response = requests.get(f"{BASE_URL}/api/devices")
    result = response.json()
    print(f"   在线设备数: {result.get('count')}")
    if result.get('devices'):
        for device in result['devices']:
            print(f"   - 设备ID: {device['device_id']}, 状态: {device['status']}")
    print()


def test_get_single_device():
    """测试获取单个设备信息接口"""
    print("4. 测试获取单个设备信息接口...")
    device_id = "mobile_001"
    response = requests.get(f"{BASE_URL}/api/device/{device_id}")
    result = response.json()
    if result.get('device'):
        device = result['device']
        print(f"   设备ID: {device['device_id']}")
        print(f"   推流地址: {device['stream_url']}")
        print(f"   分辨率: {device['resolution']}")
        print(f"   帧率: {device['fps']}")
        print(f"   场景ID: {device['scene_id']}")
        print(f"   状态: {device['status']}")
    print()


def test_heartbeat():
    """测试心跳接口"""
    print("5. 测试心跳接口...")

    heartbeat_data = {
        "device_id": "mobile_001",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    response = requests.post(
        f"{BASE_URL}/api/heartbeat",
        json=heartbeat_data,
        headers={"Content-Type": "application/json"}
    )

    print(f"   响应: {response.json()}")
    print()


def test_unregister_device():
    """测试设备注销接口"""
    print("6. 测试设备注销接口...")

    unregister_data = {
        "device_id": "mobile_001"
    }

    response = requests.post(
        f"{BASE_URL}/api/unregister_device",
        json=unregister_data,
        headers={"Content-Type": "application/json"}
    )

    print(f"   响应: {response.json()}")
    print()


if __name__ == '__main__':
    print("=" * 60)
    print("HTTP API接口测试")
    print("=" * 60)
    print()

    try:
        test_health_check()
        test_register_device()
        test_get_devices()
        test_get_single_device()
        test_heartbeat()
        test_unregister_device()

        print("=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except requests.exceptions.ConnectionError:
        print("错误: 无法连接到API服务器")
        print("请先运行: python3 api_server.py")
    except Exception as e:
        print(f"测试出错: {str(e)}")
