"""
云端HTTP API接口
提供设备注册、心跳、状态查询等REST API
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from device_manager import DeviceManager
import os


# 创建Flask应用
app = Flask(__name__)
CORS(app)  # 允许跨域

# 创建设备管理器
device_manager = DeviceManager()


@app.route('/api/register_device', methods=['POST'])
def register_device():
    """
    设备注册接口

    请求体示例：
    {
        "device_id": "mobile_001",
        "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
        "resolution": "1280x720",
        "fps": 15,
        "scene_id": "scene_704_sandbox",
        "codec": "H.264",
        "bitrate": "2Mbps",
        "timestamp": "2026-07-06 13:00:00"
    }

    响应示例：
    {
        "status": "success",
        "message": "设备注册成功",
        "device_id": "mobile_001"
    }
    """
    try:
        data = request.json

        # 必需字段
        device_id = data.get('device_id')
        stream_url = data.get('stream_url')
        resolution = data.get('resolution', '1280x720')
        fps = data.get('fps', 15)
        scene_id = data.get('scene_id', 'default')

        # 可选字段
        codec = data.get('codec', 'H.264')
        bitrate = data.get('bitrate', '2Mbps')

        # 验证必需字段
        if not device_id or not stream_url:
            return jsonify({
                "status": "error",
                "message": "缺少必需字段：device_id 或 stream_url"
            }), 400

        # 注册设备
        success = device_manager.register_device(
            device_id=device_id,
            stream_url=stream_url,
            resolution=resolution,
            fps=fps,
            scene_id=scene_id,
            codec=codec,
            bitrate=bitrate
        )

        if success:
            return jsonify({
                "status": "success",
                "message": "设备注册成功",
                "device_id": device_id
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "设备注册失败"
            }), 500

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"注册失败: {str(e)}"
        }), 500


@app.route('/api/unregister_device', methods=['POST'])
def unregister_device():
    """
    设备注销接口

    请求体示例：
    {
        "device_id": "mobile_001"
    }

    响应示例：
    {
        "status": "success",
        "message": "设备注销成功"
    }
    """
    try:
        data = request.json
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({
                "status": "error",
                "message": "缺少device_id字段"
            }), 400

        success = device_manager.unregister_device(device_id)

        if success:
            return jsonify({
                "status": "success",
                "message": "设备注销成功"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "设备不存在"
            }), 404

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"注销失败: {str(e)}"
        }), 500


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """
    心跳接口（可选）

    请求体示例：
    {
        "device_id": "mobile_001",
        "timestamp": "2026-07-06 13:00:00"
    }

    响应示例：
    {
        "status": "success",
        "message": "心跳更新成功"
    }
    """
    try:
        data = request.json
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({
                "status": "error",
                "message": "缺少device_id字段"
            }), 400

        success = device_manager.update_heartbeat(device_id)

        if success:
            return jsonify({
                "status": "success",
                "message": "心跳更新成功"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "设备不存在"
            }), 404

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"心跳更新失败: {str(e)}"
        }), 500


@app.route('/api/devices', methods=['GET'])
def get_devices():
    """
    获取所有设备列表

    响应示例：
    {
        "status": "success",
        "count": 2,
        "devices": [
            {
                "device_id": "mobile_001",
                "stream_url": "rtmp://...",
                "resolution": "1280x720",
                "fps": 15,
                "scene_id": "scene_704_sandbox",
                "status": "online",
                ...
            }
        ]
    }
    """
    try:
        devices = device_manager.get_all_devices()
        device_list = [device.to_dict() for device in devices.values()]

        return jsonify({
            "status": "success",
            "count": len(device_list),
            "devices": device_list
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"获取设备列表失败: {str(e)}"
        }), 500


@app.route('/api/device/<device_id>', methods=['GET'])
def get_device(device_id):
    """
    获取单个设备信息

    响应示例：
    {
        "status": "success",
        "device": {
            "device_id": "mobile_001",
            ...
        }
    }
    """
    try:
        device = device_manager.get_device(device_id)

        if device:
            return jsonify({
                "status": "success",
                "device": device.to_dict()
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "设备不存在"
            }), 404

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"获取设备信息失败: {str(e)}"
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    健康检查接口

    响应示例：
    {
        "status": "ok",
        "message": "云端服务运行正常"
    }
    """
    return jsonify({
        "status": "ok",
        "message": "云端服务运行正常"
    }), 200


if __name__ == '__main__':
    print("=" * 50)
    print("云端HTTP API服务启动")
    print("=" * 50)
    print("\n可用接口：")
    print("  POST   /api/register_device   - 设备注册")
    print("  POST   /api/unregister_device - 设备注销")
    print("  POST   /api/heartbeat         - 心跳上报")
    print("  GET    /api/devices           - 获取所有设备")
    print("  GET    /api/device/<id>       - 获取单个设备信息")
    print("  GET    /api/health            - 健康检查")
    print("\n服务地址：http://0.0.0.0:5000")
    print("=" * 50 + "\n")

    # 启动Flask服务
    app.run(host='0.0.0.0', port=5000, debug=True)
