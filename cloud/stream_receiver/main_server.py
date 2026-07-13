"""
云端主服务器 - 集成HTTP API + WebSocket + 视频流处理
提供设备管理、视频流接收和实时结果推送
"""
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from device_manager import DeviceManager
from video_processor import VideoProcessor
from datetime import datetime
import os
import platform
import re
import secrets
import hmac
from pathlib import Path
import shutil
import subprocess
import time
import sys
from urllib.parse import urlparse
import bcrypt

# 添加父目录到Python路径以支持database模块导入
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUD_DIR = os.path.dirname(CURRENT_DIR)
if CLOUD_DIR not in sys.path:
    sys.path.insert(0, CLOUD_DIR)

from database import mysql_client

try:
    import psutil
except ImportError:
    psutil = None


# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('ITS_SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('ITS_MAX_UPLOAD_MB', '100')) * 1024 * 1024
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('ITS_ALLOWED_ORIGINS', '*').split(',')
    if origin.strip()
]
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})

# 创建SocketIO实例（使用threading模式 + simple-websocket后端）
socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode='threading',
    logger=False,
    engineio_logger=False
)

# 创建设备管理器和视频处理器
device_manager = DeviceManager()
video_processor = VideoProcessor(device_manager, socketio)
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads" / "video_segments"
PROCESS_STARTED_AT = time.time()
DEVICE_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
ALLOWED_STREAM_SCHEMES = {'rtsp', 'rtmp', 'srt', 'http', 'https'}
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.webm'}
API_TOKEN = os.getenv('ITS_API_TOKEN', '').strip()


def _valid_device_id(value):
    return isinstance(value, str) and DEVICE_ID_PATTERN.fullmatch(value) is not None


def _valid_stream_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlparse(value)
    return parsed.scheme.lower() in ALLOWED_STREAM_SCHEMES and bool(parsed.hostname)


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({
        "status": "error",
        "message": f"上传文件超过 {app.config['MAX_CONTENT_LENGTH'] // 1024 // 1024} MB 限制",
    }), 413


def _request_token():
    bearer = request.headers.get('Authorization', '')
    if bearer.lower().startswith('bearer '):
        return bearer[7:].strip()
    return request.headers.get('X-API-Key', '').strip()


@app.before_request
def protect_mutating_api_routes():
    """配置 ITS_API_TOKEN 后保护所有会修改状态的 API；未配置时保持演示兼容。"""
    if not API_TOKEN or not request.path.startswith('/api/'):
        return None
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    if not hmac.compare_digest(_request_token(), API_TOKEN):
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    return None


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
        "models": video_processor.get_model_status(),
        "timestamp": datetime.now().isoformat(),
    }


# ==================== HTTP API 接口 ====================

@app.route('/api/register_device', methods=['POST'])
def register_device():
    """设备注册接口"""
    try:
        data = request.get_json(silent=True) or {}

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
        if not _valid_device_id(device_id):
            return jsonify({"status": "error", "message": "device_id格式无效"}), 400
        if not _valid_stream_url(stream_url):
            return jsonify({"status": "error", "message": "stream_url仅支持有效的RTSP/RTMP/SRT/HTTP(S)地址"}), 400
        try:
            fps = int(fps)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "fps必须为整数"}), 400
        if not 1 <= fps <= 120:
            return jsonify({"status": "error", "message": "fps必须在1到120之间"}), 400

        previous_device = device_manager.get_device(device_id)
        stream_changed = previous_device is not None and previous_device.stream_url != stream_url
        if stream_changed:
            video_processor.stop_processing(device_id)

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
        data = request.get_json(silent=True) or {}
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
        data = request.get_json(silent=True) or {}
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({
                "status": "error",
                "message": "缺少device_id字段"
            }), 400
        if not _valid_device_id(device_id):
            return jsonify({"status": "error", "message": "device_id格式无效"}), 400
        if not _valid_device_id(device_id):
            return jsonify({"status": "error", "message": "device_id格式无效"}), 400

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
            "error": None if db_ok else "database unavailable",
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
        if not _valid_device_id(device_id):
            return jsonify({"status": "error", "message": "device_id格式无效"}), 400

        file = request.files.get('video')
        if not file or not file.filename:
            return jsonify({
                "status": "error",
                "message": "缺少video文件"
            }), 400

        original_name = Path(file.filename).name
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_VIDEO_EXTENSIONS:
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


# ==================== 历史数据查询 API ====================

@app.route('/api/history/events', methods=['GET'])
def get_history_events():
    """
    查询历史识别事件

    参数:
        event_type: 事件类型 (可选)
        device_id: 设备ID (可选)
        limit: 返回记录数 (默认50，最大1000)
        offset: 偏移量 (默认0)
    """
    try:
        from database import mysql_client

        if not mysql_client.check_connection():
            return jsonify({
                "status": "error",
                "message": "数据库连接失败",
                "data": []
            }), 503

        event_type = request.args.get('event_type')
        device_id = request.args.get('device_id')
        limit = min(int(request.args.get('limit', 50)), 1000)
        offset = int(request.args.get('offset', 0))

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                # 构建查询
                where_clauses = []
                params = []

                if event_type:
                    where_clauses.append('event_type = %s')
                    params.append(event_type)

                if device_id:
                    where_clauses.append('device_id = %s')
                    params.append(device_id)

                where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'

                # 查询数据
                sql = f'''
                SELECT id, event_type, device_id, scene_id, plate_number,
                       bbox, result_json, created_at
                FROM recognition_event
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                '''
                params.extend([limit, offset])

                cursor.execute(sql, params)
                events = cursor.fetchall()

                # 将 datetime 对象转换为字符串，避免时区转换
                for event in events:
                    if event.get('created_at'):
                        event['created_at'] = event['created_at'].strftime('%Y-%m-%d %H:%M:%S')

                # 查询总数
                count_sql = f'SELECT COUNT(*) as total FROM recognition_event WHERE {where_sql}'
                cursor.execute(count_sql, params[:-2])
                total = cursor.fetchone()['total']

                return jsonify({
                    "status": "success",
                    "data": events,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": []
        }), 500


@app.route('/api/history/alarms', methods=['GET'])
def get_history_alarms():
    """
    查询历史告警记录

    参数:
        alarm_type: 告警类型 (可选)
        device_id: 设备ID (可选)
        status: 告警状态 (可选: warning, acknowledged, resolved)
        limit: 返回记录数 (默认50，最大1000)
        offset: 偏移量 (默认0)
    """
    try:
        from database import mysql_client

        if not mysql_client.check_connection():
            return jsonify({
                "status": "error",
                "message": "数据库连接失败",
                "data": []
            }), 503

        alarm_type = request.args.get('alarm_type')
        device_id = request.args.get('device_id')
        status = request.args.get('status')
        limit = min(int(request.args.get('limit', 50)), 1000)
        offset = int(request.args.get('offset', 0))

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                where_clauses = []
                params = []

                if alarm_type:
                    where_clauses.append('alarm_type = %s')
                    params.append(alarm_type)

                if device_id:
                    where_clauses.append('device_id = %s')
                    params.append(device_id)

                if status:
                    where_clauses.append('status = %s')
                    params.append(status)

                where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'

                sql = f'''
                SELECT id, alarm_type, device_id, scene_id, target_type, target_id,
                       plate_number, description, bbox, status, detail_json,
                       created_at, resolved_at
                FROM alarm_record
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                '''
                params.extend([limit, offset])

                cursor.execute(sql, params)
                alarms = cursor.fetchall()

                count_sql = f'SELECT COUNT(*) as total FROM alarm_record WHERE {where_sql}'
                cursor.execute(count_sql, params[:-2])
                total = cursor.fetchone()['total']

                return jsonify({
                    "status": "success",
                    "data": alarms,
                    "total": total,
                    "limit": limit,
                    "offset": offset
                })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": []
        }), 500


@app.route('/api/whitelist', methods=['GET'])
def get_whitelist():
    """获取车牌白名单"""
    try:
        from database import mysql_client

        if not mysql_client.check_connection():
            return jsonify({
                "status": "error",
                "message": "数据库连接失败",
                "data": []
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT id, plate_number, vehicle_type,
                       permission_status, remark, created_at, updated_at
                FROM vehicle_whitelist
                ORDER BY created_at DESC
                ''')
                whitelist = cursor.fetchall()

                return jsonify({
                    "status": "success",
                    "data": whitelist
                })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": []
        }), 500


@app.route('/api/whitelist', methods=['POST'])
def add_whitelist_entry():
    """新增或更新车牌白名单。"""
    try:
        data = request.get_json(silent=True) or {}
        plate_number = mysql_client._normalize_plate_number(data.get('plate_number') or data.get('plate'))
        vehicle_type = (data.get('vehicle_type') or data.get('role') or 'visitor').strip() or 'visitor'
        remark = data.get('remark')

        if not plate_number:
            return jsonify({"status": "error", "message": "车牌号不能为空"}), 400
        if not mysql_client.check_connection():
            return jsonify({"status": "error", "message": "数据库连接失败"}), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                INSERT INTO vehicle_whitelist (
                    plate_number, vehicle_type, permission_status, remark, created_at, updated_at
                ) VALUES (%s, %s, 1, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    vehicle_type = VALUES(vehicle_type),
                    permission_status = 1,
                    remark = VALUES(remark),
                    updated_at = NOW()
                ''', (plate_number, vehicle_type, remark))
                conn.commit()

                cursor.execute('''
                SELECT id, plate_number, vehicle_type,
                       permission_status, remark, created_at, updated_at
                FROM vehicle_whitelist
                WHERE plate_number = %s
                LIMIT 1
                ''', (plate_number,))
                record = cursor.fetchone()

        return jsonify({"status": "success", "data": record})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/whitelist/<plate_number>/status', methods=['PATCH'])
def update_whitelist_status(plate_number):
    """启用或停用车牌白名单。"""
    try:
        data = request.get_json(silent=True) or {}
        normalized_plate = mysql_client._normalize_plate_number(plate_number)
        enabled = bool(data.get('enabled'))
        permission_status = 1 if enabled else 0

        if not normalized_plate:
            return jsonify({"status": "error", "message": "车牌号不能为空"}), 400
        if not mysql_client.check_connection():
            return jsonify({"status": "error", "message": "数据库连接失败"}), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                UPDATE vehicle_whitelist
                SET permission_status = %s, updated_at = NOW()
                WHERE plate_number = %s
                ''', (permission_status, normalized_plate))
                if cursor.rowcount == 0:
                    conn.rollback()
                    return jsonify({"status": "error", "message": "白名单记录不存在"}), 404
                conn.commit()

        return jsonify({"status": "success", "data": {"plate_number": normalized_plate, "permission_status": permission_status}})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_system_config():
    """获取系统配置"""
    try:
        from database import mysql_client

        config = mysql_client.load_system_config()
        device_id = request.args.get('device_id')
        config['runtime'] = {
            'parkingThreshold': video_processor.get_parking_threshold(device_id=device_id),
            'vehicleConf': video_processor.vehicle_conf,
            'plateConf': video_processor.plate_conf,
            'trafficThresholds': video_processor.get_traffic_thresholds(device_id=device_id)
        }

        return jsonify({
            "status": "success",
            "data": config
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": {}
        }), 500


# ==================== 用户管理 API ====================

@app.route('/api/users/login', methods=['POST'])
def user_login():
    """用户登录"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({
                "status": "error",
                "message": "用户名和密码不能为空"
            }), 400

        from database import mysql_client

        if not mysql_client or not mysql_client.pool:
            return jsonify({
                "status": "error",
                "message": "数据库连接失败"
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT id, username, password_hash, role, status, last_login
                FROM system_user
                WHERE username = %s
                ''', (username,))
                user = cursor.fetchone()

                if not user:
                    return jsonify({
                        "status": "error",
                        "message": "用户名或密码错误"
                    }), 401

                if user['status'] != 1:
                    return jsonify({
                        "status": "error",
                        "message": "账号已被禁用"
                    }), 403

                # 验证密码
                if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                    return jsonify({
                        "status": "error",
                        "message": "用户名或密码错误"
                    }), 401

                # 更新最后登录时间
                cursor.execute('''
                UPDATE system_user
                SET last_login = NOW()
                WHERE id = %s
                ''', (user['id'],))
                conn.commit()

                return jsonify({
                    "status": "success",
                    "message": "登录成功",
                    "data": {
                        "id": user['id'],
                        "username": user['username'],
                        "role": user['role']
                    }
                })

    except Exception as e:
        print(f"登录错误: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/users', methods=['GET'])
def get_users():
    """获取用户列表（仅管理员）"""
    try:
        from database import mysql_client

        if not mysql_client or not mysql_client.pool:
            return jsonify({
                "status": "error",
                "message": "数据库连接失败",
                "data": []
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                SELECT id, username, role, status, last_login, created_at, updated_at
                FROM system_user
                ORDER BY created_at DESC
                ''')
                users = cursor.fetchall()

                # 将 datetime 对象转换为字符串
                for user in users:
                    if user.get('last_login'):
                        user['last_login'] = user['last_login'].strftime('%Y-%m-%d %H:%M:%S')
                    if user.get('created_at'):
                        user['created_at'] = user['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    if user.get('updated_at'):
                        user['updated_at'] = user['updated_at'].strftime('%Y-%m-%d %H:%M:%S')

                return jsonify({
                    "status": "success",
                    "data": users
                })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": []
        }), 500


@app.route('/api/users', methods=['POST'])
def create_user():
    """创建新用户（仅管理员）"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'user')

        if not username or not password:
            return jsonify({
                "status": "error",
                "message": "用户名和密码不能为空"
            }), 400

        if role not in ['admin', 'user']:
            return jsonify({
                "status": "error",
                "message": "角色必须是 admin 或 user"
            }), 400

        # 密码哈希
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        from database import mysql_client

        if not mysql_client or not mysql_client.pool:
            return jsonify({
                "status": "error",
                "message": "数据库连接失败"
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                # 检查用户名是否已存在
                cursor.execute('SELECT id FROM system_user WHERE username = %s', (username,))
                if cursor.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "用户名已存在"
                    }), 409

                # 插入新用户
                cursor.execute('''
                INSERT INTO system_user (username, password_hash, role, status)
                VALUES (%s, %s, %s, 1)
                ''', (username, password_hash, role))
                conn.commit()

                return jsonify({
                    "status": "success",
                    "message": "用户创建成功"
                })

    except Exception as e:
        print(f"创建用户错误: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """更新用户信息（仅管理员）"""
    try:
        data = request.get_json()
        role = data.get('role')
        status = data.get('status')
        password = data.get('password')

        from database import mysql_client

        if not mysql_client or not mysql_client.pool:
            return jsonify({
                "status": "error",
                "message": "数据库连接失败"
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                # 构建更新SQL
                updates = []
                params = []

                if role and role in ['admin', 'user']:
                    updates.append('role = %s')
                    params.append(role)

                if status is not None:
                    updates.append('status = %s')
                    params.append(1 if status else 0)

                if password:
                    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    updates.append('password_hash = %s')
                    params.append(password_hash)

                if not updates:
                    return jsonify({
                        "status": "error",
                        "message": "没有要更新的字段"
                    }), 400

                params.append(user_id)
                sql = f"UPDATE system_user SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(sql, params)
                conn.commit()

                return jsonify({
                    "status": "success",
                    "message": "用户信息更新成功"
                })

    except Exception as e:
        print(f"更新用户错误: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """删除用户（仅管理员）"""
    try:
        from database import mysql_client

        if not mysql_client or not mysql_client.pool:
            return jsonify({
                "status": "error",
                "message": "数据库连接失败"
            }), 503

        with mysql_client.get_connection() as conn:
            with conn.cursor() as cursor:
                # 不允许删除管理员账号
                cursor.execute('SELECT role FROM system_user WHERE id = %s', (user_id,))
                user = cursor.fetchone()
                if user and user['role'] == 'admin':
                    return jsonify({
                        "status": "error",
                        "message": "不能删除管理员账号"
                    }), 403

                cursor.execute('DELETE FROM system_user WHERE id = %s', (user_id,))
                conn.commit()

                return jsonify({
                    "status": "success",
                    "message": "用户删除成功"
                })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ==================== WebSocket 事件处理 ====================

def system_status_background_task():
    """后台定时推送系统状态到所有连接的前端客户端"""
    print("✅ 系统状态推送后台任务已启动")
    while True:
        try:
            time.sleep(3)  # 每3秒推送一次
            status_data = {
                "event_type": "system_status",
                "timestamp": datetime.now().isoformat(),
                "device_id": "cloud_server",
                "status": "normal",
                "data": collect_system_status(),
            }
            socketio.emit('analysis_result', status_data, namespace='/')
        except Exception as e:
            print(f"系统状态推送失败: {e}")
            time.sleep(5)  # 出错后等待5秒再重试


@socketio.on('connect')
def handle_connect(auth=None):
    """前端连接事件"""
    if API_TOKEN:
        supplied_token = (auth or {}).get('token', '')
        if not hmac.compare_digest(str(supplied_token), API_TOKEN):
            return False
    print(f"前端客户端已连接")
    emit('connection_status', {'status': 'connected', 'message': '已连接到云端服务器'})
    # 立即推送一次系统状态
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
def handle_request_devices(_data=None):
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

    if command == 'update_config':
        config_type = data.get('config_type')
        config_data = data.get('data', {})

        try:
            result = video_processor.update_config(config_type, config_data, device_id=device_id)
            emit('config_updated', {
                'status': 'success',
                'config_type': config_type,
                'message': result.get('message', '配置更新成功')
            })
            print(f"✅ 配置更新成功: {config_type} = {config_data}")
        except Exception as e:
            emit('config_updated', {
                'status': 'error',
                'config_type': config_type,
                'message': str(e)
            })
            print(f"❌ 配置更新失败: {e}")
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
    server_port = int(os.getenv('ITS_PORT', '5001'))
    print("=" * 60)
    print("云端智慧交通AI分析服务器启动")
    print("=" * 60)
    print(f"\n✅ HTTP API 服务: http://0.0.0.0:{server_port}")
    print("   - POST   /api/register_device   - 设备注册")
    print("   - POST   /api/unregister_device - 设备注销")
    print("   - POST   /api/heartbeat         - 心跳上报")
    print("   - GET    /api/devices           - 获取所有设备")
    print("   - GET    /api/device/<id>       - 获取单个设备信息")
    print("   - GET    /api/health            - 健康检查")
    print("   - GET    /api/system/status     - 系统状态查询")
    print(f"\n✅ WebSocket 服务: ws://0.0.0.0:{server_port}/socket.io/")
    print("   - 事件: analysis_result  - AI分析结果推送")
    print("   - 事件: connection_status - 连接状态")
    print("   - 事件: devices_list     - 设备列表")
    print("\n✅ 视频流处理引擎: 自动启动")
    print("   - 设备注册后自动从 stream_url 拉流处理")
    print("   - 推荐 stream_url: rtsp://<云端IP>:8554/live/<device_id>")
    print("   - 抽帧策略: 通过 ITS_FRAME_SKIP 环境变量配置")
    print("   - 实时推送分析结果到前端")
    print("\n✅ 系统监控: 后台定时推送（每3秒）")
    print("   - CPU使用率、GPU使用率、内存使用率")
    print("   - 活跃设备数、视频流状态")
    print("\n📝 提供给边端的信息:")
    print(f"   - HTTP API地址: http://<frp公网IP>:15000 或 http://<本机IP>:{server_port}")
    print("   - SRT推流地址: srt://<云端IP>:8890?streamid=publish:live/<device_id>&latency=200")
    print("   - RTMP兜底地址: rtmp://<云端IP>:1935/live/<device_id>")
    print("   - AI拉流地址: rtsp://<云端IP>:8554/live/<device_id>")
    print("   - 推荐参数: 1280x720, 15fps, H.264, 2Mbps")
    print("\n⚠️  注意: 本地 AI 电脑不启动 MediaMTX；MediaMTX 运行在云端服务器。")
    print("=" * 60 + "\n")

    # 启动系统状态推送后台任务
    socketio.start_background_task(system_status_background_task)

    # 启动Flask-SocketIO服务
    socketio.run(app, host='0.0.0.0', port=server_port, debug=False, allow_unsafe_werkzeug=True)
