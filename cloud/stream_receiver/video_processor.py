"""
视频流处理引擎
负责从RTMP拉取视频流、解帧、送入AI模型、推送结果到前端
"""
import cv2
import threading
import time
from datetime import datetime
from queue import Queue
import json
import os
import sys
from pathlib import Path


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
AI_MODELS_DIR = os.path.join(CURRENT_DIR, "..", "ai_models")
VEHICLE_DETECTION_DIR = os.path.join(AI_MODELS_DIR, "vehicle_detection")
REPO_ROOT = Path(CURRENT_DIR).parents[1]
if AI_MODELS_DIR not in sys.path:
    sys.path.append(AI_MODELS_DIR)
if VEHICLE_DETECTION_DIR not in sys.path:
    sys.path.append(VEHICLE_DETECTION_DIR)


class VideoProcessor:
    """视频流处理器"""

    def __init__(self, device_manager, socketio):
        """
        初始化视频处理器

        Args:
            device_manager: 设备管理器实例
            socketio: SocketIO实例，用于推送结果
        """
        self.device_manager = device_manager
        self.socketio = socketio
        self.active_streams = {}  # {device_id: thread}
        self.stop_flags = {}  # {device_id: stop_event}
        self.frame_skip = int(os.getenv("ITS_FRAME_SKIP", "10"))
        self.enable_mock_fallback = os.getenv("ITS_ENABLE_MOCK_FALLBACK", "true").lower() == "true"
        self.disable_vehicle_mask = os.getenv("ITS_DISABLE_VEHICLE_MASK", "false").lower() == "true"
        self.vehicle_mask_min_conf = float(os.getenv("ITS_VEHICLE_MASK_MIN_CONF", "0.65"))
        self.emit_vehicle_events = os.getenv("ITS_EMIT_VEHICLE_EVENTS", "false").lower() == "true"
        self.disable_drivable_segmenter = os.getenv("ITS_DISABLE_DRIVABLE_SEGMENTER", "true").lower() == "true"
        self.debug_output_dir = REPO_ROOT / "data" / "sandbox_anomaly" / "output"
        self.anomaly_processor = None
        self.vehicle_detector = None

        self._init_sandbox_ai()

        print("视频处理引擎初始化完成")

    def _init_sandbox_ai(self):
        """Initialize sandbox-oriented AI modules without making server startup fragile."""
        if os.getenv("ITS_ENABLE_SANDBOX_AI", "true").lower() != "true":
            print("沙盘AI检测已通过环境变量关闭")
            return

        try:
            from anomaly_processor import RoadAnomalyProcessor
            from anomaly_detection.anomaly_detector import AnomalyDetector

            drivable_model_path = os.path.join(
                AI_MODELS_DIR,
                "anomaly_detection",
                "sandbox_drivable_best.pt",
            )
            if self.disable_drivable_segmenter or not os.path.exists(drivable_model_path):
                drivable_model_path = None
                print("沙盘道路分割模型未启用，将使用默认道路ROI")

            detector = AnomalyDetector(
                min_area=int(os.getenv("ITS_ANOMALY_MIN_AREA", "120")),
                static_frames_threshold=int(os.getenv("ITS_ANOMALY_STATIC_FRAMES", "3")),
                max_missed_frames=int(os.getenv("ITS_ANOMALY_MAX_MISSED", "4")),
                warmup_frames=int(os.getenv("ITS_ANOMALY_WARMUP_FRAMES", "0")),
                learning_rate=float(os.getenv("ITS_ANOMALY_LEARNING_RATE", "0")),
                startup_static_kernel=int(os.getenv("ITS_STARTUP_STATIC_KERNEL", "55")),
                startup_static_dilate=int(os.getenv("ITS_STARTUP_STATIC_DILATE", "7")),
                road_surface_outlier_check=os.getenv("ITS_ROAD_SURFACE_OUTLIER", "true").lower() == "true",
                outlier_min_area=int(os.getenv("ITS_OUTLIER_MIN_AREA", "250")),
                outlier_color_distance=float(os.getenv("ITS_OUTLIER_COLOR_DISTANCE", "24")),
                outlier_max_area=int(os.getenv("ITS_OUTLIER_MAX_AREA", "30000")),
            )
            self.anomaly_processor = RoadAnomalyProcessor(
                detector=detector,
                drivable_model_path=drivable_model_path,
                event_cooldown_frames=int(os.getenv("ITS_ANOMALY_EVENT_COOLDOWN", "30")),
            )
            print("✅ 沙盘道路异常检测已启用")
        except Exception as e:
            print(f"⚠️  沙盘道路异常检测初始化失败，将使用模拟降级: {str(e)}")
            self.anomaly_processor = None

        if self.disable_vehicle_mask:
            print("沙盘车辆掩膜已关闭，异常检测不会排除车辆框")
            return

        try:
            from detector import VehicleDetector

            sandbox_model_path = os.path.join(AI_MODELS_DIR, "vehicle_detection", "sandbox_vehicle_best.pt")
            default_model_path = os.path.join(AI_MODELS_DIR, "vehicle_detection", "yolo11s.pt")
            yolo_path = sandbox_model_path if os.path.exists(sandbox_model_path) else default_model_path
            if not os.path.exists(yolo_path):
                print("⚠️  未找到车辆检测权重，道路异常检测将不使用车辆掩膜")
                return

            self.vehicle_detector = VehicleDetector(
                model_path=yolo_path,
                conf_threshold=float(os.getenv("ITS_VEHICLE_CONF", "0.45")),
            )
            print("✅ 沙盘车辆掩膜检测已启用")
        except Exception as e:
            print(f"⚠️  车辆掩膜检测初始化失败，道路异常检测将继续运行: {str(e)}")
            self.vehicle_detector = None

    def start_processing(self, device_id, stream_url):
        """
        启动视频流处理

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
        """
        if device_id in self.active_streams:
            print(f"设备 {device_id} 已在处理中")
            return False

        # 创建停止标志
        stop_event = threading.Event()
        self.stop_flags[device_id] = stop_event

        # 启动处理线程
        thread = threading.Thread(
            target=self._process_stream,
            args=(device_id, stream_url, stop_event),
            daemon=True
        )
        thread.start()
        self.active_streams[device_id] = thread

        print(f"开始处理设备 {device_id} 的视频流: {stream_url}")
        return True

    def stop_processing(self, device_id):
        """
        停止视频流处理

        Args:
            device_id: 设备ID
        """
        if device_id not in self.active_streams:
            print(f"设备 {device_id} 未在处理中")
            return False

        # 设置停止标志
        self.stop_flags[device_id].set()

        # 等待线程结束
        self.active_streams[device_id].join(timeout=5)

        # 清理
        del self.active_streams[device_id]
        del self.stop_flags[device_id]

        print(f"停止处理设备 {device_id} 的视频流")
        return True

    def _process_stream(self, device_id, stream_url, stop_event):
        """
        视频流处理主循环

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
            stop_event: 停止事件
        """
        cap = None
        frame_count = 0

        try:
            # RTMP 推流端可能比设备注册晚几秒真正出画面，沙盘演示时这里耐心重试。
            open_attempts = 0
            max_open_attempts = int(os.getenv("ITS_RTMP_OPEN_ATTEMPTS", "60"))
            while not stop_event.is_set() and open_attempts < max_open_attempts:
                open_attempts += 1
                cap = cv2.VideoCapture(stream_url)

                if cap.isOpened():
                    break

                if cap:
                    cap.release()
                    cap = None

                if open_attempts == 1 or open_attempts % 5 == 0:
                    print(
                        f"视频流尚未可读: {stream_url} "
                        f"(打开尝试 {open_attempts}/{max_open_attempts})"
                    )
                time.sleep(1)

            if not cap or not cap.isOpened():
                print(f"无法打开视频流: {stream_url}")
                self._send_error(device_id, "无法打开视频流")
                return

            print(f"成功连接视频流: {device_id}")

            while not stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    print(f"视频流 {device_id} 读取失败")
                    time.sleep(0.1)
                    continue

                frame_count += 1

                # 跳帧策略：每3帧处理1帧
                if frame_count % self.frame_skip != 0:
                    continue

                # 处理帧
                self._analyze_frame(device_id, frame, frame_count)

                # 控制处理速度
                time.sleep(0.1)

        except Exception as e:
            print(f"视频流处理异常 {device_id}: {str(e)}")
            self._send_error(device_id, str(e))

        finally:
            if cap:
                cap.release()
            print(f"视频流处理结束: {device_id}")

    def _analyze_frame(self, device_id, frame, frame_count):
        """
        分析单帧图像

        Args:
            device_id: 设备ID
            frame: 图像帧
            frame_count: 帧计数
        """
        timestamp = datetime.now().isoformat()

        if self.anomaly_processor:
            self._analyze_road_anomaly(device_id, frame, frame_count, timestamp)
            return

        if not self.enable_mock_fallback:
            return

        # 每10帧生成一次模拟结果
        if frame_count % 10 == 0:
            event_type = self._get_event_type(frame_count)
            result = self._generate_mock_result(device_id, timestamp, event_type)

            # 通过WebSocket推送结果
            self._send_result(result)

    def _analyze_road_anomaly(self, device_id, frame, frame_count, timestamp):
        """Run the real sandbox road-anomaly detector and push warning events."""
        try:
            vehicle_bboxes = []
            if self.vehicle_detector:
                vehicles = self.vehicle_detector.detect(frame)
                vehicle_bboxes = [
                    vehicle["bbox"]
                    for vehicle in vehicles
                    if vehicle.get("confidence", 0) >= self.vehicle_mask_min_conf
                ]

                if vehicles and frame_count % 30 == 0:
                    vehicle_debug = [
                        {
                            "bbox": vehicle["bbox"],
                            "conf": round(vehicle.get("confidence", 0), 3),
                            "masked": vehicle.get("confidence", 0) >= self.vehicle_mask_min_conf,
                        }
                        for vehicle in vehicles
                    ]
                    print(
                        f"帧 {frame_count}: 车辆检测 {len(vehicles)} 个，"
                        f"用于掩膜 {len(vehicle_bboxes)} 个 {vehicle_debug}"
                    )

                if self.emit_vehicle_events:
                    for idx, vehicle in enumerate(vehicles):
                        self._send_result({
                            "event_type": "vehicle_detection",
                            "timestamp": timestamp,
                            "device_id": device_id,
                            "data": {
                                "vehicle_id": idx + 1,
                                "vehicle_type": vehicle["class_name"],
                                "confidence": vehicle["confidence"],
                            },
                            "bbox": vehicle["bbox"],
                            "status": "detected",
                        })

            events = self.anomaly_processor.process_frame(
                device_id=device_id,
                frame=frame,
                vehicle_bboxes=vehicle_bboxes,
                timestamp=timestamp,
            )

            for event in events:
                self._send_result(event)
                print(
                    f"道路异常告警: bbox={event.get('bbox')} "
                    f"area={event.get('data', {}).get('area')} "
                    f"duration={event.get('duration_frames')}"
                )

            if frame_count % 90 == 0:
                print(
                    f"帧 {frame_count}: 道路异常检测完成，"
                    f"车辆掩膜 {len(vehicle_bboxes)} 个，告警 {len(events)} 条"
                )
                self._save_debug_frame(frame, frame_count, vehicle_bboxes, events)
                self._save_road_mask_debug(frame, frame_count)
        except Exception as e:
            print(f"⚠️  道路异常检测处理异常: {str(e)}")

    def _save_debug_frame(self, frame, frame_count, vehicle_bboxes, events):
        """Write a lightweight snapshot so sandbox tuning can inspect boxes."""
        try:
            self.debug_output_dir.mkdir(parents=True, exist_ok=True)
            output = frame.copy()
            for x1, y1, x2, y2 in vehicle_bboxes:
                cv2.rectangle(output, (x1, y1), (x2, y2), (255, 160, 0), 2)
                cv2.putText(output, "vehicle-mask", (x1, max(18, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 160, 0), 2)
            for event in events:
                x1, y1, x2, y2 = event["bbox"]
                cv2.rectangle(output, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(output, "road-anomaly", (x1, max(18, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            cv2.imwrite(str(self.debug_output_dir / "live_rtmp_debug.jpg"), output)
        except Exception as e:
            print(f"⚠️  调试帧保存失败: {str(e)}")

    def _save_road_mask_debug(self, frame, frame_count):
        try:
            if not self.anomaly_processor:
                return
            road_mask = self.anomaly_processor.predict_road_mask(frame)
            if road_mask is None:
                return
            self.debug_output_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(self.debug_output_dir / "live_road_mask.jpg"), road_mask)
            print(f"帧 {frame_count}: 已保存道路mask调试图 live_road_mask.jpg")
        except Exception as e:
            print(f"⚠️  道路mask调试图保存失败: {str(e)}")

    def _get_event_type(self, frame_count):
        """根据帧数循环返回不同事件类型"""
        types = ['plate_recognition', 'traffic_density', 'illegal_parking', 'road_anomaly']
        return types[(frame_count // 10) % len(types)]

    def _generate_mock_result(self, device_id, timestamp, event_type):
        """
        生成模拟分析结果

        Args:
            device_id: 设备ID
            timestamp: 时间戳
            event_type: 事件类型

        Returns:
            dict: 分析结果
        """
        base_result = {
            'event_type': event_type,
            'timestamp': timestamp,
            'device_id': device_id,
            'status': 'normal'
        }

        if event_type == 'plate_recognition':
            base_result['data'] = {
                'plate_number': '京A12345',
                'is_in_whitelist': True,
                'decision': 'allow'
            }
            base_result['bbox'] = [120, 80, 220, 140]

        elif event_type == 'traffic_density':
            base_result['data'] = {
                'regions': [
                    {'region_id': 'road_A', 'vehicle_count': 2, 'status': 'smooth', 'color': 'green'},
                    {'region_id': 'road_B', 'vehicle_count': 5, 'status': 'slow', 'color': 'yellow'},
                    {'region_id': 'road_C', 'vehicle_count': 8, 'status': 'congested', 'color': 'red'}
                ]
            }

        elif event_type == 'illegal_parking':
            base_result['data'] = {
                'track_id': 17,
                'stay_time': 35.5,
                'threshold': 30
            }
            base_result['bbox'] = [230, 180, 310, 260]
            base_result['status'] = 'warning'

        elif event_type == 'road_anomaly':
            base_result['data'] = {
                'anomaly_type': 'unknown_object',
                'affected_lane': 'lane_1',
                'duration_frames': 20
            }
            base_result['bbox'] = [360, 220, 420, 280]
            base_result['status'] = 'warning'

        return base_result

    def _send_result(self, result):
        """
        通过WebSocket发送结果到前端

        Args:
            result: 分析结果字典
        """
        try:
            self.socketio.emit('analysis_result', result)
            print(f"推送结果: {result['event_type']}")
        except Exception as e:
            print(f"推送结果失败: {str(e)}")

    def _send_error(self, device_id, error_message):
        """
        发送错误信息

        Args:
            device_id: 设备ID
            error_message: 错误消息
        """
        try:
            self.socketio.emit('error', {
                'device_id': device_id,
                'message': error_message,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"发送错误信息失败: {str(e)}")

    def get_active_streams(self):
        """获取当前活跃的视频流列表"""
        return list(self.active_streams.keys())


if __name__ == '__main__':
    # 测试代码
    from device_manager import DeviceManager

    class MockSocketIO:
        def emit(self, event, data):
            print(f"[SocketIO] {event}: {data}")

    device_manager = DeviceManager()
    socketio = MockSocketIO()

    processor = VideoProcessor(device_manager, socketio)

    # 注册测试设备
    device_manager.register_device(
        device_id="test_001",
        stream_url="rtmp://localhost:1935/live/test_001",
        resolution="1280x720",
        fps=15,
        scene_id="test_scene"
    )

    print("\n视频处理引擎测试完成")
