"""
云端API服务器 - 车辆检测功能（修复版）
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from device_manager import DeviceManager
from vehicle_detection_processor import VehicleDetectionProcessor
import os


# 创建Flask应用
app = Flask(__name__)
CORS(app)

# 创建设备管理器和车辆检测处理器
device_manager = DeviceManager()
vehicle_processor = None


def init_processor():
    """初始化车辆检测处理器"""
    global vehicle_processor
    if vehicle_processor is None:
        try:
            vehicle_processor = VehicleDetectionProcessor(device_manager)
        except Exception as e:
            print(f"警告: AI模型初始化失败: {str(e)}")
            print("服务将以基础模式运行（无AI识别功能）")
            vehicle_processor = None


@app.route('/api/register_device', methods=['POST'])
def register_device():
    """设备注册接口"""
    try:
        data = request.json

        device_id = data.get('device_id')
        stream_url = data.get('stream_url')
        resolution = data.get('resolution', '1280x720')
        fps = data.get('fps', 15)
        scene_id = data.get('scene_id', 'default')
        device_type = data.get('device_type', 'unknown')
        codec = data.get('codec', 'H.264')
        bitrate = data.get('bitrate', '2Mbps')

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
            # 启动车辆检测处理
            if vehicle_processor:
                started = vehicle_processor.start_processing(device_id, stream_url)
                if started:
                    message = "设备注册成功，AI车辆检测已启动"
                else:
                    message = "设备注册成功，AI车辆检测已在运行"
            else:
                message = "设备注册成功（AI模型未加载）"

            return jsonify({
                "status": "success",
                "message": message,
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

        # 停止车辆检测处理
        if vehicle_processor:
            vehicle_processor.stop_processing(device_id)

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


@app.route('/api/detection_results', methods=['GET'])
def get_detection_results():
    """
    获取最新的车辆检测结果

    Query参数:
        limit: 最多返回的结果数，默认10
    """
    try:
        if not vehicle_processor:
            return jsonify({
                "status": "error",
                "message": "AI模型未加载"
            }), 503

        limit = request.args.get('limit', 10, type=int)
        results = vehicle_processor.get_latest_results(max_count=limit)

        return jsonify({
            "status": "success",
            "count": len(results),
            "results": results
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"获取检测结果失败: {str(e)}"
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "message": "云端服务运行正常",
        "ai_enabled": vehicle_processor is not None
    }), 200


if __name__ == '__main__':
    print("=" * 60)
    print("云端智慧交通AI分析服务器")
    print("车辆检测功能")
    print("=" * 60)
    print("\n正在初始化...")

    # 初始化AI模型
    init_processor()

    print("\n" + "=" * 60)
    print("✅ HTTP API 服务")
    print("=" * 60)
    print("  POST   /api/register_device     - 设备注册")
    print("  POST   /api/unregister_device   - 设备注销")
    print("  POST   /api/heartbeat           - 心跳上报")
    print("  GET    /api/devices             - 获取所有设备")
    print("  GET    /api/device/<id>         - 获取单个设备")
    print("  GET    /api/detection_results   - 获取车辆检测结果")
    print("  GET    /api/health              - 健康检查")
    print("\n服务地址：http://0.0.0.0:5000")
    print("=" * 60)
    print("\n🚀 服务器启动中...\n")

    # 启动Flask服务
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
