"""
云端主服务器 - 集成HTTP API + WebSocket + 视频流处理
提供设备管理、视频流接收和实时结果推送
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from device_manager import DeviceManager
from video_processor import VideoProcessor
import os


# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'intelligent-transportation-system-2026'
CORS(app, resources={r"/*": {"origins": "*"}})

# 创建SocketIO实例
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 创建设备管理器和视频处理器
device_manager = DeviceManager()
video_processor = VideoProcessor(device_manager, socketio)


# ==================== HTTP API 接口 ====================

@app.route('/api/register_device', methods=['POST'])
def register_device():
    """设备注册接口"""
    try:
        data = request.json

        # 必需字段
        device_id = data.get('device_id')
        stream_url = data.get('stream_url')
        resolution = data.get('resolution', '1280x720')
        fps = data.get('fps', 15)
        scene_id = data.get('scene_id', 'default')

        # 可选字段
        device_type = data.get('device_type', 'unknown')
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
            device_type=device_type,
            codec=codec,
            bitrate=bitrate
        )

        if success:
            # 自动启动视频流处理
            video_processor.start_processing(device_id, stream_url)

            return jsonify({
                "status": "success",
                "message": "设备注册成功，已启动视频流处理",
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
    """设备注销接口"""
    try:
        data = request.json
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({
                "status": "error",
                "message": "缺少device_id字段"
            }), 400

        # 停止视频流处理
        video_processor.stop_processing(device_id)

        # 注销设备
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
    """心跳接口"""
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
    """获取所有设备列表"""
    try:
        devices = device_manager.get_all_devices()
        device_list = [device.to_dict() for device in devices.values()]

        # 添加视频流处理状态
        active_streams = video_processor.get_active_streams()
        for device in device_list:
            device['stream_processing'] = device['device_id'] in active_streams

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
    """获取单个设备信息"""
    try:
        device = device_manager.get_device(device_id)

        if device:
            device_info = device.to_dict()
            # 添加视频流处理状态
            device_info['stream_processing'] = device_id in video_processor.get_active_streams()

            return jsonify({
                "status": "success",
                "device": device_info
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
    """健康检查接口"""
    active_streams = video_processor.get_active_streams()
    return jsonify({
        "status": "ok",
        "message": "云端服务运行正常",
        "active_devices": len(device_manager.get_all_devices()),
        "active_streams": len(active_streams)
    }), 200


# ==================== WebSocket 事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """前端连接事件"""
    print(f"前端客户端已连接")
    emit('connection_status', {'status': 'connected', 'message': '已连接到云端服务器'})


@socketio.on('disconnect')
def handle_disconnect():
    """前端断开连接事件"""
    print(f"前端客户端已断开")


@socketio.on('request_devices')
def handle_request_devices():
    """前端请求设备列表"""
    devices = device_manager.get_all_devices()
    device_list = [device.to_dict() for device in devices.values()]
    emit('devices_list', {'devices': device_list})


@socketio.on('switch_scene')
def handle_switch_scene(data):
    """前端请求切换场景"""
    device_id = data.get('device_id')
    scene_id = data.get('scene_id')
    print(f"切换场景请求: device={device_id}, scene={scene_id}")
    # TODO: 实现场景切换逻辑
    emit('scene_switched', {'device_id': device_id, 'scene_id': scene_id})


# ==================== 启动服务器 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("云端智慧交通AI分析服务器启动")
    print("=" * 60)
    print("\n✅ HTTP API 服务: http://0.0.0.0:5000")
    print("   - POST   /api/register_device   - 设备注册")
    print("   - POST   /api/unregister_device - 设备注销")
    print("   - POST   /api/heartbeat         - 心跳上报")
    print("   - GET    /api/devices           - 获取所有设备")
    print("   - GET    /api/device/<id>       - 获取单个设备信息")
    print("   - GET    /api/health            - 健康检查")
    print("\n✅ WebSocket 服务: ws://0.0.0.0:5000/socket.io/")
    print("   - 事件: analysis_result  - AI分析结果推送")
    print("   - 事件: connection_status - 连接状态")
    print("   - 事件: devices_list     - 设备列表")
    print("\n✅ 视频流处理引擎: 自动启动")
    print("   - 设备注册后自动开始处理RTMP视频流")
    print("   - 抽帧策略: 每3帧处理1帧")
    print("   - 实时推送分析结果到前端")
    print("\n📝 提供给边端的信息:")
    print("   - HTTP API地址: http://<你的IP>:5000")
    print("   - RTMP推流地址: rtmp://<你的IP>:1935/live/<device_id>")
    print("   - 推荐参数: 1280x720, 15fps, H.264, 2Mbps")
    print("\n⚠️  注意: RTMP服务器需要单独启动（使用MediaMTX或nginx-rtmp）")
    print("=" * 60 + "\n")

    # 启动Flask-SocketIO服务
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
