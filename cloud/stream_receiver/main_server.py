"""
云端主服务器 - 集成HTTP API + WebSocket + 视频流处理
提供设备管理、视频流接收和实时结果推送
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from device_manager import DeviceManager
from video_processor import VideoProcessor
from cloud.database import mysql_client
from datetime import datetime
import os
import platform
from pathlib import Path
import shutil
import subprocess
import time

try:
    import psutil
except ImportError:
    psutil = None


# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'intelligent-transportation-system-2026'
CORS(app, resources={r"/*": {"origins": "*"}})

# 创建SocketIO实例
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 创建设备管理器和视频处理器
device_manager = DeviceManager()
video_processor = VideoProcessor(device_manager, socketio)
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads" / "video_segments"
PROCESS_STARTED_AT = time.time()


def _safe_percent(value):
    try:
        return round(max(0, min(100, float(value))), 1)
    except (TypeError, ValueError):
        return 0


def _read_gpu_usage():
    """Return GPU utilization percent when NVIDIA tooling is available."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return 0

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        values = [
            float(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        return _safe_percent(sum(values) / len(values)) if values else 0
    except Exception:
        return 0


def collect_system_status():
    active_streams = video_processor.get_active_streams()
    devices = device_manager.get_all_devices()

    if psutil:
        cpu_usage = psutil.cpu_percent(interval=0.05)
        memory_usage = psutil.virtual_memory().percent
        process = psutil.Process(os.getpid())
        process_memory_mb = round(process.memory_info().rss / 1024 / 1024, 1)
    else:
        cpu_usage = 0
        memory_usage = 0
        process_memory_mb = 0

    return {
        "cpu_usage": _safe_percent(cpu_usage),
        "gpu_usage": _read_gpu_usage(),
        "memory_usage": _safe_percent(memory_usage),
        "stream_status": "streaming" if active_streams else "disconnected",
        "active_streams": len(active_streams),
        "active_devices": len(devices),
        "bitrate": None,
        "process_memory_mb": process_memory_mb,
        "uptime_seconds": int(time.time() - PROCESS_STARTED_AT),
        "platform": platform.platform(),
        "timestamp": datetime.now().isoformat(),
    }


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
    db_ok = mysql_client.check_connection()
    return jsonify({
        "status": "ok",
        "message": "云端服务运行正常",
        "active_devices": len(device_manager.get_all_devices()),
        "active_streams": len(active_streams),
        "database": {
            "enabled": db_ok,
            "host": mysql_client.DB_SETTINGS['host'],
            "port": mysql_client.DB_SETTINGS['port'],
            "name": mysql_client.DB_SETTINGS['database'],
            "error": None if db_ok else mysql_client.get_last_error(),
        },
    }), 200


@app.route('/api/system/status', methods=['GET'])
def get_system_status():
    """获取后端主机和视频处理运行状态。"""
    return jsonify({
        "status": "success",
        "data": collect_system_status(),
    }), 200


@app.route('/api/video/upload', methods=['POST'])
def upload_video_segment():
    """备用视频段上传接口。

    实时演示仍以云端 MediaMTX 的 RTSP 拉流为主；该接口只用于弱网或
    推流不稳定时保存短视频段，便于后续离线分析或排查。
    """
    try:
        device_id = request.form.get('device_id')
        if not device_id:
            return jsonify({
                "status": "error",
                "message": "缺少device_id字段"
            }), 400

        file = request.files.get('video')
        if not file or not file.filename:
            return jsonify({
                "status": "error",
                "message": "缺少video文件"
            }), 400

        original_name = Path(file.filename).name
        extension = Path(original_name).suffix.lower()
        if extension not in {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.webm'}:
            return jsonify({
                "status": "error",
                "message": f"不支持的视频格式: {extension or 'unknown'}"
            }), 400

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved_name = f"{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
        saved_path = UPLOAD_DIR / saved_name
        file.save(saved_path)

        segment_info = {
            "device_id": device_id,
            "scene_id": request.form.get('scene_id', 'scene_704_sandbox'),
            "timestamp": request.form.get('timestamp') or datetime.now().isoformat(),
            "resolution": request.form.get('resolution', '1280x720'),
            "fps": request.form.get('fps', '15'),
            "codec": request.form.get('codec', 'H.264'),
            "original_filename": original_name,
            "saved_filename": saved_name,
            "saved_path": str(saved_path),
            "size_bytes": saved_path.stat().st_size,
        }

        socketio.emit('analysis_result', {
            "event_type": "video_segment_uploaded",
            "timestamp": datetime.now().isoformat(),
            "device_id": device_id,
            "status": "normal",
            "data": segment_info,
        })

        return jsonify({
            "status": "success",
            "message": "视频段上传成功",
            "segment": segment_info,
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"视频段上传失败: {str(e)}"
        }), 500


@app.route('/api/anomaly/background/start', methods=['POST'])
def start_anomaly_background_learning():
    """手动进入道路异常背景学习模式。"""
    data = request.json or {}
    result = video_processor.start_anomaly_background_learning(
        device_id=data.get('device_id'),
        reset=data.get('reset', True),
    )
    status_code = 200 if result.get("status") == "success" else 503
    return jsonify(result), status_code


@app.route('/api/anomaly/detection/start', methods=['POST'])
def start_anomaly_detection():
    """结束背景学习并进入道路异常检测模式。"""
    data = request.json or {}
    result = video_processor.start_anomaly_detection(device_id=data.get('device_id'))
    status_code = 200 if result.get("status") == "success" else 503
    return jsonify(result), status_code


@app.route('/api/anomaly/reset', methods=['POST'])
def reset_anomaly_background():
    """重置道路异常背景模型。"""
    data = request.json or {}
    result = video_processor.reset_anomaly_background(device_id=data.get('device_id'))
    status_code = 200 if result.get("status") == "success" else 503
    return jsonify(result), status_code


@app.route('/api/anomaly/status', methods=['GET'])
def get_anomaly_status():
    """获取道路异常检测当前模式。"""
    return jsonify(video_processor.get_anomaly_status(device_id=request.args.get('device_id'))), 200


# ==================== WebSocket 事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """前端连接事件"""
    print(f"前端客户端已连接")
    emit('connection_status', {'status': 'connected', 'message': '已连接到云端服务器'})
    emit('analysis_result', {
        "event_type": "system_status",
        "timestamp": datetime.now().isoformat(),
        "device_id": "cloud_server",
        "status": "normal",
        "data": collect_system_status(),
    })


@socketio.on('disconnect')
def handle_disconnect():
    """前端断开连接事件"""
    print(f"前端客户端已断开")


@socketio.on('request_devices')
def handle_request_devices():
    """前端请求设备列表"""
    devices = device_manager.get_all_devices()
    device_list = [device.to_dict() for device in devices.values()]
    active_streams = video_processor.get_active_streams()
    for device in device_list:
        device['stream_processing'] = device['device_id'] in active_streams
    emit('devices_list', {'devices': device_list})


@socketio.on('client_command')
def handle_client_command(data):
    """前端通用控制指令入口"""
    command = data.get('command')
    device_id = data.get('device_id')

    print(f"前端控制指令: command={command}, payload={data}")

    if command == 'switch_scene':
        scene_id = data.get('scene_id', 'vehicle_detection')
        video_processor.set_active_scene(scene_id, device_id=device_id)
        emit('scene_switched', {'device_id': device_id, 'scene_id': scene_id})
        return

    if command == 'set_threshold':
        threshold = data.get('threshold', 30)
        video_processor.set_parking_threshold(threshold, device_id=device_id)
        emit('threshold_updated', {'device_id': device_id, 'threshold': threshold})
        return

    if command == 'set_confidence':
        confidence = data.get('confidence', 0.45)
        video_processor.set_vehicle_confidence(confidence)
        emit('confidence_updated', {'confidence': confidence})
        return

    if command == 'anomaly_background_start':
        result = video_processor.start_anomaly_background_learning(
            device_id=device_id,
            reset=data.get('reset', True),
        )
        emit('anomaly_mode_updated', result)
        return

    if command == 'anomaly_detection_start':
        result = video_processor.start_anomaly_detection(device_id=device_id)
        emit('anomaly_mode_updated', result)
        return

    if command == 'anomaly_reset':
        result = video_processor.reset_anomaly_background(device_id=device_id)
        emit('anomaly_mode_updated', result)
        return

    if command == 'anomaly_status':
        emit('anomaly_mode_updated', video_processor.get_anomaly_status(device_id=device_id))
        return

    if command == 'start_analysis':
        emit('analysis_status', {'status': 'running'})
        return

    if command == 'stop_analysis':
        emit('analysis_status', {'status': 'stopped'})
        return

    emit('command_ack', {'status': 'ignored', 'payload': data})


@socketio.on('switch_scene')
def handle_switch_scene(data):
    """兼容旧前端直接发送 switch_scene 事件。"""
    handle_client_command({
        'command': 'switch_scene',
        'scene_id': data.get('scene_id'),
        'device_id': data.get('device_id'),
    })


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
    print("   - 设备注册后自动从 stream_url 拉流处理")
    print("   - 推荐 stream_url: rtsp://<云端IP>:8554/live/<device_id>")
    print("   - 抽帧策略: 通过 ITS_FRAME_SKIP 环境变量配置")
    print("   - 实时推送分析结果到前端")
    print("\n📝 提供给边端的信息:")
    print("   - HTTP API地址: http://<frp公网IP>:15000 或 http://<本机IP>:5000")
    print("   - SRT推流地址: srt://<云端IP>:8890?streamid=publish:live/<device_id>&latency=200")
    print("   - RTMP兜底地址: rtmp://<云端IP>:1935/live/<device_id>")
    print("   - AI拉流地址: rtsp://<云端IP>:8554/live/<device_id>")
    print("   - 推荐参数: 1280x720, 15fps, H.264, 2Mbps")
    print("\n⚠️  注意: 本地 AI 电脑不启动 MediaMTX；MediaMTX 运行在云端服务器。")
    print("=" * 60 + "\n")

    # 启动Flask-SocketIO服务
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
