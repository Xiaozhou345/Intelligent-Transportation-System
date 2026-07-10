"""
视频流处理引擎
负责从 RTMP 拉取视频流、解帧、送入 AI 模型、推送结果到前端。

当前主链路复用同一套车辆 YOLO 检测结果，同时服务于：
1. 车辆检测事件（可选）
2. 拥堵统计 / 热力图
3. 违停跟踪与告警（YOLO + ByteTrack + 业务规则）
4. 道路异常检测中的车辆掩膜
"""
import cv2
import threading
import time
from datetime import datetime
from pathlib import Path
import json
import os
import sys
from typing import Dict, List, Optional


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
AI_MODELS_DIR = os.path.join(CURRENT_DIR, "..", "ai_models")
VEHICLE_DETECTION_DIR = os.path.join(AI_MODELS_DIR, "vehicle_detection")
VEHICLE_TRACKING_DIR = os.path.join(AI_MODELS_DIR, "vehicle_tracking")
PLATE_DETECTION_DIR = os.path.join(AI_MODELS_DIR, "plate_detection")
BUSINESS_LOGIC_DIR = os.path.join(os.path.dirname(CURRENT_DIR), "business_logic")
REPO_ROOT = Path(CURRENT_DIR).parents[1]
if AI_MODELS_DIR not in sys.path:
    sys.path.append(AI_MODELS_DIR)
if VEHICLE_DETECTION_DIR not in sys.path:
    sys.path.append(VEHICLE_DETECTION_DIR)
if VEHICLE_TRACKING_DIR not in sys.path:
    sys.path.append(VEHICLE_TRACKING_DIR)
if PLATE_DETECTION_DIR not in sys.path:
    sys.path.append(PLATE_DETECTION_DIR)
if BUSINESS_LOGIC_DIR not in sys.path:
    sys.path.append(BUSINESS_LOGIC_DIR)

from detector import VehicleDetector
from vehicle_tracker import VehicleTracker
from illegal_parking import IllegalParkingMonitor
from plate_detection.detector import PlateDetector
from plate_recognition.plate_recognizer import PlateRecognizer

# 添加父目录到Python路径以支持database模块导入
CURRENT_DIR_VP = os.path.dirname(os.path.abspath(__file__))
CLOUD_DIR_VP = os.path.dirname(CURRENT_DIR_VP)
if CLOUD_DIR_VP not in sys.path:
    sys.path.insert(0, CLOUD_DIR_VP)

from database import mysql_client


class VideoProcessor:
    """视频流处理器"""

    def __init__(self, device_manager, socketio):
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
        self.plate_detector = None
        self.plate_recognizer = None
        self.vehicle_conf = float(os.getenv("ITS_VEHICLE_CONF", "0.45"))
        self.plate_conf = float(os.getenv("ITS_PLATE_CONF", "0.20"))

        # 车牌号缓存：{device_id: [(bbox, plate_number, timestamp), ...]}
        self.plate_cache: Dict[str, List[tuple]] = {}

        self.runtime_defaults = self._load_runtime_defaults()
        self.runtime_state: Dict[str, dict] = {}

        self._init_sandbox_ai()
        print("视频处理引擎初始化完成")

    def _load_runtime_defaults(self):
        config_path = Path(CURRENT_DIR) / "illegal_parking_config.json"
        defaults = {
            "traffic_regions": [],
            "traffic_thresholds": {"smooth_max": 2, "slow_max": 5},
            "no_parking_zones": [],
            "parking_stationary_pixel_threshold": 18,
            "parking_release_grace_frames": 3,
            "parking_min_history": 3,
            "density_emit_every_processed_frames": 3,
            "active_scene": "vehicle_detection",
            "anomaly_mode": "background_learning",
            "anomaly_road_roi": [],
            "anomaly_min_background_frames": 8,
        }
        if not config_path.exists():
            print("⚠️  未找到 illegal_parking_config.json，将使用内置默认配置")
        else:
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                file_defaults = data.get("default", {})
                defaults.update(file_defaults)
                print(f"✅ 已加载违停/热力图本地配置: {config_path}")
            except Exception as exc:
                print(f"⚠️  违停配置加载失败，将使用内置默认配置: {exc}")

        db_config = mysql_client.load_system_config()
        if db_config:
            if 'traffic_thresholds' in db_config:
                defaults['traffic_thresholds'] = db_config['traffic_thresholds']
            if 'no_parking_zone_default' in db_config:
                defaults['no_parking_zones'] = db_config['no_parking_zone_default']
            print("✅ 已从 MySQL system_config 加载运行时配置")
        else:
            print("ℹ️  system_config 未加载，继续使用本地 JSON 配置")
        return defaults

    def _init_sandbox_ai(self):
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
                min_area=int(os.getenv("ITS_ANOMALY_MIN_AREA", "900")),
                max_area=int(os.getenv("ITS_ANOMALY_MAX_AREA", "0")) or None,
                max_area_ratio=float(os.getenv("ITS_ANOMALY_MAX_AREA_RATIO", "0.08")),
                static_frames_threshold=int(os.getenv("ITS_ANOMALY_STATIC_FRAMES", "3")),
                max_missed_frames=int(os.getenv("ITS_ANOMALY_MAX_MISSED", "4")),
                road_roi=self._scale_polygon_for_base_size(self.runtime_defaults.get("anomaly_road_roi", [])),
                warmup_frames=int(os.getenv("ITS_ANOMALY_WARMUP_FRAMES", "0")),
                learning_rate=float(os.getenv("ITS_ANOMALY_LEARNING_RATE", "0")),
                startup_static_kernel=int(os.getenv("ITS_STARTUP_STATIC_KERNEL", "55")),
                startup_static_dilate=int(os.getenv("ITS_STARTUP_STATIC_DILATE", "7")),
                road_surface_outlier_check=os.getenv("ITS_ROAD_SURFACE_OUTLIER", "true").lower() == "true",
                outlier_min_area=int(os.getenv("ITS_OUTLIER_MIN_AREA", "250")),
                outlier_color_distance=float(os.getenv("ITS_OUTLIER_COLOR_DISTANCE", "24")),
                outlier_max_area=int(os.getenv("ITS_OUTLIER_MAX_AREA", "30000")),
                min_road_overlap=float(os.getenv("ITS_ANOMALY_MIN_ROAD_OVERLAP", "0.65")),
                filter_lane_markings=os.getenv("ITS_FILTER_LANE_MARKINGS", "true").lower() == "true",
                use_default_road_scope=os.getenv("ITS_USE_DEFAULT_ROAD_SCOPE", "true").lower() == "true",
                max_background_vehicle_ratio=float(os.getenv("ITS_BG_MAX_VEHICLE_RATIO", "0.18")),
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
            sandbox_model_path = os.path.join(AI_MODELS_DIR, "vehicle_detection", "sandbox_vehicle_best.pt")
            default_model_path = os.path.join(AI_MODELS_DIR, "vehicle_detection", "yolo11s.pt")
            yolo_path = sandbox_model_path if os.path.exists(sandbox_model_path) else default_model_path
            if not os.path.exists(yolo_path):
                print("⚠️  未找到车辆检测权重，道路异常检测将不使用车辆掩膜")
                return

            self.vehicle_detector = VehicleDetector(
                model_path=yolo_path,
                conf_threshold=self.vehicle_conf,
            )
            print("✅ 共享车辆检测已启用（服务于拥堵/违停/异常检测）")

            plate_model_path = os.path.join(AI_MODELS_DIR, "plate_detection", "sandbox_plate_best.pt")
            if os.path.exists(plate_model_path):
                self.plate_detector = PlateDetector(
                    model_path=plate_model_path,
                    conf_threshold=self.plate_conf,
                )
                print("✅ 共享车牌检测已启用（服务于视频叠加显示）")

                # 尝试加载车牌识别模型（LPRNet）
                lprnet_candidates = [
                    os.path.join(AI_MODELS_DIR, "plate_recognition", "Final_LPRNet_model.pth"),
                    os.path.join(REPO_ROOT, "models", "lprnet_best.pth"),
                ]

                lprnet_path = None
                lprnet_load_success = False

                for path in lprnet_candidates:
                    if os.path.exists(path):
                        print(f"🔍 尝试加载LPRNet模型: {path}")
                        try:
                            # 验证文件是否可读且大小合理
                            file_size = os.path.getsize(path)
                            if file_size < 1000:  # 模型文件至少应该有1KB
                                print(f"⚠️  模型文件过小 ({file_size} bytes)，可能已损坏，跳过")
                                continue

                            self.plate_recognizer = PlateRecognizer(model_path=path)
                            print(f"✅ 车牌识别（LPRNet）已启用: {path}")
                            lprnet_path = path
                            lprnet_load_success = True
                            break
                        except Exception as e:
                            print(f"⚠️  模型加载失败 ({path}): {str(e)}")
                            self.plate_recognizer = None
                            continue

                if not lprnet_load_success:
                    if lprnet_path is None:
                        print(f"⚠️  未找到LPRNet模型文件，搜索路径:")
                        for path in lprnet_candidates:
                            print(f"     - {path} {'[存在]' if os.path.exists(path) else '[不存在]'}")
                    print("⚠️  车牌识别功能不可用，车牌框将不显示车牌号")
                    self.plate_recognizer = None
            else:
                print("⚠️  未找到车牌检测权重，视频叠加中的车牌框将为空")
        except Exception as e:
            print(f"⚠️  车辆检测初始化失败，道路异常检测将继续运行: {str(e)}")
            self.vehicle_detector = None
            self.plate_detector = None

    def _get_or_create_runtime_state(self, device_id, frame_shape=None):
        state = self.runtime_state.get(device_id)
        if state is None:
            state = {
                "tracker": VehicleTracker(
                    max_time_lost=int(os.getenv("ITS_TRACKER_MAX_LOST", "45")),
                    track_thresh=float(os.getenv("ITS_TRACKER_TRACK_THRESH", "0.40")),
                    match_thresh=float(os.getenv("ITS_TRACKER_MATCH_THRESH", "0.30")),
                ),
                "parking_monitor": IllegalParkingMonitor(
                    stationary_pixel_threshold=float(self.runtime_defaults.get("parking_stationary_pixel_threshold", 18)),
                    release_grace_frames=int(self.runtime_defaults.get("parking_release_grace_frames", 3)),
                    min_history=int(self.runtime_defaults.get("parking_min_history", 3)),
                ),
                "frame_shape": None,
                "traffic_regions": [],
                "no_parking_zones": [],
                "anomaly_road_roi": [],
                "traffic_thresholds": dict(self.runtime_defaults.get("traffic_thresholds", {"smooth_max": 2, "slow_max": 5})),
                "density_emit_every_processed_frames": int(self.runtime_defaults.get("density_emit_every_processed_frames", 3)),
                "processed_frames": 0,
                "active_scene": self._resolve_scene_for_device(device_id),
                "anomaly_mode": self.runtime_defaults.get("anomaly_mode", "detecting"),
                "anomaly_background_frames": 0,
                "anomaly_background_skipped_frames": 0,
            }
            self.runtime_state[device_id] = state

        if frame_shape is not None and state["frame_shape"] != frame_shape:
            state["frame_shape"] = frame_shape
            state["traffic_regions"] = self._scale_regions(self.runtime_defaults.get("traffic_regions", []), frame_shape)
            state["no_parking_zones"] = self._scale_regions(self.runtime_defaults.get("no_parking_zones", []), frame_shape)
            state["anomaly_road_roi"] = self._scale_polygon(self.runtime_defaults.get("anomaly_road_roi", []), frame_shape)
            state["parking_monitor"].zones = state["no_parking_zones"]
            if self.anomaly_processor:
                self.anomaly_processor.detector.road_roi = state["anomaly_road_roi"] or None
        return state

    @staticmethod
    def _normalize_scene_name(scene_id: Optional[str]) -> str:
        if not scene_id:
            return 'vehicle_detection'
        scene_id = scene_id.lower()
        if 'illegal' in scene_id or 'parking' in scene_id:
            return 'illegal_parking'
        if 'anomaly' in scene_id:
            return 'road_anomaly'
        if 'traffic' in scene_id or 'density' in scene_id:
            return 'traffic_density'
        if 'plate' in scene_id:
            return 'plate_recognition'
        return 'vehicle_detection'

    def _resolve_scene_for_device(self, device_id: str) -> str:
        device = self.device_manager.get_device(device_id)
        scene_id = device.scene_id if device else self.runtime_defaults.get('active_scene')
        return self._normalize_scene_name(scene_id)

    @staticmethod
    def _scale_regions(regions, frame_shape):
        height, width = frame_shape[:2]
        scaled = []
        for region in regions:
            polygon = []
            for x, y in region.get("polygon", []):
                if 0 <= x <= 1 and 0 <= y <= 1:
                    polygon.append([int(round(x * width)), int(round(y * height))])
                else:
                    polygon.append([int(round(x)), int(round(y))])
            item = dict(region)
            item["polygon"] = polygon
            scaled.append(item)
        return scaled

    @staticmethod
    def _scale_polygon(polygon, frame_shape):
        height, width = frame_shape[:2]
        scaled = []
        for x, y in polygon or []:
            if 0 <= x <= 1 and 0 <= y <= 1:
                scaled.append([int(round(x * width)), int(round(y * height))])
            else:
                scaled.append([int(round(x)), int(round(y))])
        return scaled

    def _scale_polygon_for_base_size(self, polygon):
        """Scale normalized ROI for detector construction before first frame.

        The detector ROI is updated with exact frame dimensions once the first
        frame arrives, so normalized coordinates can be passed through here.
        """
        if not polygon:
            return None
        if all(0 <= x <= 1 and 0 <= y <= 1 for x, y in polygon):
            return polygon
        return polygon

    def start_processing(self, device_id, stream_url):
        if device_id in self.active_streams:
            print(f"设备 {device_id} 已在处理中")
            return False

        stop_event = threading.Event()
        self.stop_flags[device_id] = stop_event
        self._get_or_create_runtime_state(device_id)

        thread = threading.Thread(
            target=self._process_stream,
            args=(device_id, stream_url, stop_event),
            daemon=True,
        )
        thread.start()
        self.active_streams[device_id] = thread

        print(f"开始处理设备 {device_id} 的视频流: {stream_url}")
        return True

    def stop_processing(self, device_id):
        if device_id not in self.active_streams:
            print(f"设备 {device_id} 未在处理中")
            return False

        self.stop_flags[device_id].set()
        self.active_streams[device_id].join(timeout=5)

        del self.active_streams[device_id]
        del self.stop_flags[device_id]
        self.runtime_state.pop(device_id, None)
        self.plate_cache.pop(device_id, None)

        print(f"停止处理设备 {device_id} 的视频流")
        return True

    def update_plate_number(self, device_id, bbox, plate_number):
        """
        更新车牌号缓存（由plate_recognition_processor调用）

        Args:
            device_id: 设备ID
            bbox: 车牌框 [x1, y1, x2, y2]
            plate_number: 识别出的车牌号
        """
        if device_id not in self.plate_cache:
            self.plate_cache[device_id] = []

        current_time = time.time()
        # 添加新识别结果
        self.plate_cache[device_id].append((bbox, plate_number, current_time))

        # 清理超过30秒的旧缓存
        self.plate_cache[device_id] = [
            (b, p, t) for b, p, t in self.plate_cache[device_id]
            if current_time - t < 30
        ]

        # 最多保留50条
        if len(self.plate_cache[device_id]) > 50:
            self.plate_cache[device_id] = self.plate_cache[device_id][-50:]

    def _match_plate_number(self, device_id, bbox):
        """
        根据bbox匹配最近识别的车牌号

        Args:
            device_id: 设备ID
            bbox: 车牌框 [x1, y1, x2, y2]

        Returns:
            str: 车牌号，如果没有匹配则返回空字符串
        """
        if device_id not in self.plate_cache or not self.plate_cache[device_id]:
            return ""

        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        # 找最近的匹配（IoU > 0.3 或中心点距离很近）
        best_match = None
        best_score = 0

        for cached_bbox, plate_number, timestamp in self.plate_cache[device_id]:
            bx1, by1, bx2, by2 = cached_bbox
            bcx, bcy = (bx1 + bx2) / 2, (by1 + by2) / 2

            # 计算IoU
            inter_x1 = max(x1, bx1)
            inter_y1 = max(y1, by1)
            inter_x2 = min(x2, bx2)
            inter_y2 = min(y2, by2)

            if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                bbox_area = (x2 - x1) * (y2 - y1)
                cached_area = (bx2 - bx1) * (by2 - by1)
                iou = inter_area / (bbox_area + cached_area - inter_area + 1e-6)
            else:
                iou = 0

            # 计算中心点距离
            distance = ((cx - bcx) ** 2 + (cy - bcy) ** 2) ** 0.5
            bbox_size = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            normalized_distance = distance / (bbox_size + 1e-6)

            # 综合评分：IoU权重更高
            score = iou * 0.7 + (1.0 - min(normalized_distance, 1.0)) * 0.3

            if score > best_score and score > 0.3:
                best_score = score
                best_match = plate_number

        return best_match or ""

    def _process_stream(self, device_id, stream_url, stop_event):
        cap = None
        frame_count = 0
        is_local_file = os.path.exists(stream_url)
        consecutive_read_failures = 0

        try:
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
                    consecutive_read_failures += 1
                    if is_local_file and consecutive_read_failures >= 3:
                        print(f"本地视频已读取结束: {stream_url}")
                        break
                    print(f"视频流 {device_id} 读取失败")
                    time.sleep(0.1)
                    continue

                consecutive_read_failures = 0
                frame_count += 1
                if frame_count % self.frame_skip != 0:
                    continue

                self._analyze_frame(device_id, frame, frame_count)
                time.sleep(0.1)

        except Exception as e:
            print(f"视频流处理异常 {device_id}: {str(e)}")
            self._send_error(device_id, str(e))

        finally:
            if cap:
                cap.release()
            print(f"视频流处理结束: {device_id}")

    def _analyze_frame(self, device_id, frame, frame_count):
        timestamp = datetime.now().isoformat()
        state = self._get_or_create_runtime_state(device_id, frame.shape)
        state["processed_frames"] += 1
        active_scene = state.get("active_scene", "vehicle_detection")

        if not self.vehicle_detector:
            if active_scene != 'road_anomaly' or not self.anomaly_processor:
                if self.enable_mock_fallback and frame_count % 10 == 0:
                    event_type = self._get_event_type(frame_count)
                    result = self._generate_mock_result(device_id, timestamp, event_type)
                    self._send_result(result)
                return
            vehicles = []
            tracked_vehicles = []
            vehicle_bboxes = []
        else:
            vehicles = self.vehicle_detector.detect(frame)
            tracked_vehicles = state["tracker"].update(vehicles)
            # 使用tracked_vehicles而非vehicles构建掩膜，确保数据一致性
            # 同时保持高置信度过滤，避免低置信度车辆被误报为道路异常
            vehicle_bboxes = [
                tracked["bbox"]
                for tracked in tracked_vehicles
                if tracked.get("confidence", 0) >= self.vehicle_mask_min_conf
            ]

        plate_events = []
        if self.plate_detector:
            detected_plates = self.plate_detector.detect(frame)
            for plate in detected_plates:
                bbox = plate["bbox"]
                plate_number = ""

                # 如果有LPRNet，立即识别车牌号
                if self.plate_recognizer:
                    x1, y1, x2, y2 = bbox
                    # 确保坐标在图像范围内
                    h, w = frame.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)

                    if x2 > x1 and y2 > y1:
                        plate_img = frame[y1:y2, x1:x2]
                        if plate_img.size > 0:
                            try:
                                recognized = self.plate_recognizer.recognize(plate_img)
                                # 如果识别成功，更新缓存
                                if recognized and len(recognized.strip()) >= 4:
                                    plate_number = recognized
                                    self.update_plate_number(device_id, bbox, plate_number)
                            except Exception as e:
                                # 记录所有OCR错误（不只是每30帧），便于诊断模型问题
                                print(f"⚠️  车牌OCR失败 (frame {frame_count}): {str(e)}")

                # 如果没有识别出来，尝试从缓存匹配
                if not plate_number:
                    plate_number = self._match_plate_number(device_id, bbox)

                plate_events.append({
                    "event_type": "plate_recognition",
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "bbox": bbox,
                    "status": "normal",
                    "data": {
                        "plate_number": plate_number,
                        "confidence": plate["confidence"],
                        "track_id": None,
                        "is_in_whitelist": False,
                        "decision": "unknown",
                    },
                })

        # 将车牌识别结果发送到前端（仅在相关场景下发送，保持与其他事件的一致性）
        if active_scene in ['vehicle_detection', 'plate_recognition']:
            for plate_event in plate_events:
                self._send_result(plate_event)
                if frame_count % 30 == 0:
                    print(f"车牌识别: {plate_event['data'].get('plate_number', '未识别')} conf={plate_event['data']['confidence']:.2f}")

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
                f"车牌检测 {len(plate_events)} 个，"
                f"用于掩膜 {len(vehicle_bboxes)} 个 {vehicle_debug}"
            )

        if self.emit_vehicle_events or active_scene == 'vehicle_detection':
            # 建立车辆与车牌的空间关联映射（使用最佳匹配算法，优先选择IoU最大的车辆）
            vehicle_plate_map = {}
            for plate_event in plate_events:
                plate_bbox = plate_event["bbox"]
                px1, py1, px2, py2 = plate_bbox
                plate_area = (px2 - px1) * (py2 - py1)

                best_match_idx = -1
                best_overlap_ratio = 0.0

                for idx, tracked in enumerate(tracked_vehicles):
                    vehicle_bbox = tracked["bbox"]
                    vx1, vy1, vx2, vy2 = vehicle_bbox

                    # 检查车牌是否在车辆框内（车牌通常在车辆框内）
                    if px1 >= vx1 and py1 >= vy1 and px2 <= vx2 and py2 <= vy2:
                        # 计算重叠比例（车牌面积占车辆面积的比例）
                        vehicle_area = (vx2 - vx1) * (vy2 - vy1)
                        overlap_ratio = plate_area / vehicle_area if vehicle_area > 0 else 0

                        if overlap_ratio > best_overlap_ratio:
                            best_overlap_ratio = overlap_ratio
                            best_match_idx = idx

                if best_match_idx >= 0:
                    vehicle_plate_map[best_match_idx] = plate_event["data"]["plate_number"]

            # 使用tracked_vehicles而不是vehicles，确保包含track_id
            for idx, tracked in enumerate(tracked_vehicles):
                plate_number = vehicle_plate_map.get(idx, "")
                self._send_result({
                    "event_type": "vehicle_detection",
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "data": {
                        "vehicle_id": tracked.get("track_id", idx + 1),  # 使用跟踪ID，确保跨帧一致性
                        "vehicle_type": tracked["class_name"],
                        "confidence": tracked["confidence"],
                        "plate_number": plate_number,  # 关联的车牌号
                    },
                    "bbox": tracked["bbox"],
                    "status": "detected",
                })

        # 热力图事件：基于同一份YOLO检测结果，与车辆检测保持数据一致性
        # 在vehicle_detection和traffic_density场景下都发送，确保前端数据同步
        traffic_event = self._build_traffic_density_event(device_id, state, tracked_vehicles, timestamp)
        if traffic_event is not None and active_scene in ['traffic_density', 'vehicle_detection']:
            self._send_result(traffic_event)

        parking_events = state["parking_monitor"].update(device_id, tracked_vehicles, timestamp)
        if active_scene == 'illegal_parking':
            for event in parking_events:
                self._send_result(event)
                print(
                    f"违停告警: track_id={event['data'].get('track_id')} "
                    f"stay_time={event['data'].get('stay_time')}s bbox={event.get('bbox')}"
                )

        anomaly_events = []
        if self.anomaly_processor and active_scene == 'road_anomaly':
            anomaly_mode = state.get("anomaly_mode", "detecting")
            if anomaly_mode == "background_learning":
                road_mask = self.anomaly_processor.predict_road_mask(frame)
                learned = self.anomaly_processor.update_background(
                    frame,
                    road_mask=road_mask,
                    vehicle_bboxes=vehicle_bboxes,
                )
                if learned:
                    state["anomaly_background_frames"] = state.get("anomaly_background_frames", 0) + 1
                else:
                    state["anomaly_background_skipped_frames"] = state.get("anomaly_background_skipped_frames", 0) + 1

                background_frames = state.get("anomaly_background_frames", 0)
                skipped_frames = state.get("anomaly_background_skipped_frames", 0)
                should_report = (
                    background_frames == 1
                    or (learned and background_frames % 10 == 0)
                    or (not learned and skipped_frames % 5 == 0)
                )
                if should_report:
                    self._send_result({
                        "event_type": "anomaly_calibration",
                        "timestamp": timestamp,
                        "device_id": device_id,
                        "status": "learning" if learned else "skipped",
                        "data": {
                            "mode": "background_learning",
                            "background_frames": background_frames,
                            "skipped_frames": skipped_frames,
                            "vehicle_masks": len(vehicle_bboxes),
                            "reason": None if learned else "vehicle_mask_too_large_or_invalid_frame",
                        },
                    })
                    print(
                        f"道路异常背景学习中: device={device_id} "
                        f"frames={background_frames} skipped={skipped_frames} "
                        f"vehicle_masks={len(vehicle_bboxes)}"
                    )
            else:
                anomaly_events = self.anomaly_processor.process_frame(
                    device_id=device_id,
                    frame=frame,
                    vehicle_bboxes=vehicle_bboxes,
                    timestamp=timestamp,
                )
                for event in anomaly_events:
                    self._send_result(event)
                    print(
                        f"道路异常告警: bbox={event.get('bbox')} "
                        f"area={event.get('data', {}).get('area')} "
                        f"duration={event.get('duration_frames')}"
                    )

                if frame_count % 90 == 0:
                    print(
                        f"帧 {frame_count}: 道路异常检测完成，"
                        f"车辆掩膜 {len(vehicle_bboxes)} 个，告警 {len(anomaly_events)} 条"
                    )
                    self._save_debug_frame(frame, frame_count, vehicle_bboxes, anomaly_events)
                    self._save_road_mask_debug(frame, frame_count)

        overlay = self._build_video_overlay(
            device_id=device_id,
            timestamp=timestamp,
            frame=frame,
            state=state,
            active_scene=active_scene,
            tracked_vehicles=tracked_vehicles,
            parking_events=parking_events,
            anomaly_events=anomaly_events,
            plate_events=plate_events,
        )
        print(
            f"帧 {frame_count}: video_overlay vehicles={len(overlay['data']['vehicles'])} "
            f"plates={len(overlay['data']['plates'])} illegal={len(overlay['data']['illegal_parking'])} "
            f"anomalies={len(overlay['data']['road_anomalies'])}"
        )
        self._send_result(overlay)

    def _build_traffic_density_event(self, device_id, state, tracked_vehicles, timestamp):
        emit_every = max(1, int(state.get("density_emit_every_processed_frames", 3)))
        if state["processed_frames"] % emit_every != 0:
            return None

        # 获取视频分辨率
        frame_shape = state.get("frame_shape")
        if frame_shape is None:
            return None

        height, width = frame_shape[:2]

        # 网格配置（可通过state配置覆盖）
        grid_cols = state.get("density_grid_cols", 20)
        grid_rows = state.get("density_grid_rows", 15)

        # 计算每个网格的宽高
        cell_width = width / grid_cols
        cell_height = height / grid_rows

        # 初始化网格计数器
        grid_counts = {}

        # 统计每辆车所在的网格
        for tracked in tracked_vehicles:
            anchor = self._bottom_center(tracked["bbox"])
            x, y = anchor

            # 计算车辆所在网格索引
            col = int(x / cell_width)
            row = int(y / cell_height)

            # 边界检查
            if 0 <= col < grid_cols and 0 <= row < grid_rows:
                grid_key = (row, col)
                grid_counts[grid_key] = grid_counts.get(grid_key, 0) + 1

        # 只发送有车辆的网格（减少数据量）
        if not grid_counts:
            return None

        thresholds = state.get("traffic_thresholds", {"smooth_max": 2, "slow_max": 5})
        smooth_max = thresholds.get("smooth_max", 2)
        slow_max = thresholds.get("slow_max", 5)

        regions = []
        for (row, col), count in grid_counts.items():
            # 计算网格的四个角坐标
            x1 = col * cell_width
            y1 = row * cell_height
            x2 = x1 + cell_width
            y2 = y1 + cell_height

            polygon = [
                [x1, y1],
                [x2, y1],
                [x2, y2],
                [x1, y2]
            ]

            # 判断拥堵状态
            if count <= smooth_max:
                status = "smooth"
                color = "green"
            elif count <= slow_max:
                status = "slow"
                color = "yellow"
            else:
                status = "congested"
                color = "red"

            regions.append({
                "region_id": f"grid_{row}_{col}",
                "name": f"区域{row}-{col}",
                "vehicle_count": count,
                "status": status,
                "color": color,
                "polygon": polygon,
            })

        summary = f"共{len(regions)}个网格有车辆，总计{sum(grid_counts.values())}辆"
        print(f"traffic_density: {summary}")

        return {
            "event_type": "traffic_density",
            "timestamp": timestamp,
            "device_id": device_id,
            "status": "normal",
            "data": {
                "regions": regions,
            },
        }

    def set_active_scene(self, scene_id, device_id=None):
        if device_id and device_id in self.runtime_state:
            self.runtime_state[device_id]["active_scene"] = scene_id
        else:
            self.runtime_defaults["active_scene"] = scene_id
            for state in self.runtime_state.values():
                state["active_scene"] = scene_id
        print(f"已切换场景: {scene_id}")

    def start_anomaly_background_learning(self, device_id=None, reset=True):
        if not self.anomaly_processor:
            return {"status": "error", "message": "道路异常检测器未启用"}

        if reset:
            self.anomaly_processor.reset()

        targets = self._target_states(device_id)
        for state in targets:
            state["active_scene"] = "road_anomaly"
            state["anomaly_mode"] = "background_learning"
            state["anomaly_background_frames"] = 0
            state["anomaly_background_skipped_frames"] = 0

        self.runtime_defaults["active_scene"] = "road_anomaly"
        self.runtime_defaults["anomaly_mode"] = "background_learning"
        print("道路异常背景学习已开始")
        return {"status": "success", "mode": "background_learning", "reset": reset, "background_frames": 0, "skipped_frames": 0}

    def start_anomaly_detection(self, device_id=None):
        if not self.anomaly_processor:
            return {"status": "error", "message": "道路异常检测器未启用"}

        targets = self._target_states(device_id)
        background_frames = 0
        min_background_frames = int(self.runtime_defaults.get("anomaly_min_background_frames", 8))
        for state in targets:
            background_frames = max(background_frames, state.get("anomaly_background_frames", 0))

        if targets and background_frames < min_background_frames:
            print(f"道路异常检测未启动，背景帧不足: {background_frames}/{min_background_frames}")
            return {
                "status": "error",
                "mode": "background_learning",
                "message": f"背景学习帧数不足，请至少学习 {min_background_frames} 帧",
                "background_frames": background_frames,
                "min_background_frames": min_background_frames,
            }

        for state in targets:
            state["active_scene"] = "road_anomaly"
            state["anomaly_mode"] = "detecting"

        self.runtime_defaults["active_scene"] = "road_anomaly"
        self.runtime_defaults["anomaly_mode"] = "detecting"
        print(f"道路异常检测已开始，背景帧数: {background_frames}")
        return {"status": "success", "mode": "detecting", "background_frames": background_frames, "min_background_frames": min_background_frames}

    def reset_anomaly_background(self, device_id=None):
        if not self.anomaly_processor:
            return {"status": "error", "message": "道路异常检测器未启用"}

        self.anomaly_processor.reset()
        for state in self._target_states(device_id):
            state["active_scene"] = "road_anomaly"
            state["anomaly_mode"] = "background_learning"
            state["anomaly_background_frames"] = 0
            state["anomaly_background_skipped_frames"] = 0
        self.runtime_defaults["active_scene"] = "road_anomaly"
        self.runtime_defaults["anomaly_mode"] = "background_learning"
        print("道路异常背景已重置，已进入背景学习模式")
        return {"status": "success", "mode": "background_learning", "background_frames": 0, "skipped_frames": 0}

    def get_anomaly_status(self, device_id=None):
        if device_id and device_id in self.runtime_state:
            state = self.runtime_state[device_id]
            return {
                "status": "success",
                "device_id": device_id,
                "mode": state.get("anomaly_mode", "detecting"),
                "background_frames": state.get("anomaly_background_frames", 0),
                "skipped_frames": state.get("anomaly_background_skipped_frames", 0),
                "min_background_frames": int(self.runtime_defaults.get("anomaly_min_background_frames", 8)),
                "active_scene": state.get("active_scene"),
                "enabled": self.anomaly_processor is not None,
            }

        return {
            "status": "success",
            "device_id": device_id,
            "mode": self.runtime_defaults.get("anomaly_mode", "detecting"),
            "background_frames": max(
                [state.get("anomaly_background_frames", 0) for state in self.runtime_state.values()] or [0]
            ),
            "skipped_frames": sum(
                state.get("anomaly_background_skipped_frames", 0) for state in self.runtime_state.values()
            ),
            "min_background_frames": int(self.runtime_defaults.get("anomaly_min_background_frames", 8)),
            "active_scene": self.runtime_defaults.get("active_scene"),
            "enabled": self.anomaly_processor is not None,
        }

    def _target_states(self, device_id=None):
        if device_id:
            return [self._get_or_create_runtime_state(device_id)]
        return list(self.runtime_state.values())

    def set_parking_threshold(self, threshold_seconds, device_id=None):
        threshold_seconds = float(threshold_seconds)
        self.runtime_defaults.setdefault("no_parking_zones", [])
        for zone in self.runtime_defaults.get("no_parking_zones", []):
            zone["threshold_seconds"] = threshold_seconds
        targets = [self.runtime_state[device_id]] if device_id and device_id in self.runtime_state else self.runtime_state.values()
        for state in targets:
            for zone in state.get("no_parking_zones", []):
                zone["threshold_seconds"] = threshold_seconds
            state["parking_monitor"].zones = state.get("no_parking_zones", [])
        print(f"已更新违停阈值: {threshold_seconds}s")

    def set_vehicle_confidence(self, confidence):
        confidence = float(confidence)
        self.vehicle_conf = confidence
        if self.vehicle_detector:
            self.vehicle_detector.conf_threshold = confidence
        print(f"已更新车辆检测置信度阈值: {confidence}")

    @staticmethod
    def _bottom_center(bbox):
        x1, y1, x2, y2 = bbox
        return int((x1 + x2) / 2), int(y2)

    @staticmethod
    def _point_in_polygon(point, polygon):
        if len(polygon) < 3:
            return False
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _build_video_overlay(self, device_id, timestamp, frame, state, active_scene, tracked_vehicles, parking_events, anomaly_events, plate_events):
        overlay = {
            'event_type': 'video_overlay',
            'timestamp': timestamp,
            'device_id': device_id,
            'status': 'normal',
            'active_scene': active_scene,
            'stream_size': {
                'width': int(frame.shape[1]),
                'height': int(frame.shape[0]),
            },
            'data': {
                'vehicles': [],
                'plates': [],
                'traffic_regions': [],
                'no_parking_zones': [],
                'illegal_parking': [],
                'road_anomalies': [],
            },
        }

        for tracked in tracked_vehicles:
            overlay['data']['vehicles'].append({
                'track_id': tracked.get('track_id'),
                'bbox': [int(v) for v in tracked.get('bbox', [])],
                'label': f"{tracked.get('class_name', 'vehicle')} {tracked.get('confidence', 0):.2f}",
                'confidence': tracked.get('confidence', 0),
            })

        for event in plate_events:
            bbox = [int(v) for v in event.get('bbox', [])]
            plate_number = event.get('data', {}).get('plate_number')
            confidence = event.get('data', {}).get('confidence', 0)
            overlay['data']['plates'].append({
                'bbox': bbox,
                'label': plate_number or f"plate {confidence:.2f}",
                'confidence': confidence,
                'track_id': event.get('data', {}).get('track_id'),
            })

        for region in state.get('traffic_regions', []):
            polygon = region.get('polygon', [])
            if len(polygon) < 3:
                continue
            overlay['data']['traffic_regions'].append({
                'region_id': region.get('region_id', 'road'),
                'name': region.get('name', region.get('region_id', 'road')),
                'polygon': [[int(x), int(y)] for x, y in polygon],
                'label': region.get('name', region.get('region_id', 'road')),
            })

        for event in parking_events:
            bbox = [int(v) for v in event.get('bbox', [])]
            overlay['data']['illegal_parking'].append({
                'bbox': bbox,
                'track_id': event.get('data', {}).get('track_id'),
                'stay_time': event.get('data', {}).get('stay_time', 0),
                'threshold': event.get('data', {}).get('threshold', 0),
                'status': event.get('status', 'warning'),
                'label': f"track {event.get('data', {}).get('track_id', '-') } {event.get('data', {}).get('stay_time', 0)}s",
            })

        for zone in state.get('no_parking_zones', []):
            polygon = zone.get('polygon', [])
            if len(polygon) < 3:
                continue
            overlay['data']['no_parking_zones'].append({
                'zone_id': zone.get('zone_id', 'no_parking'),
                'name': zone.get('name', '禁停区'),
                'polygon': [[int(x), int(y)] for x, y in polygon],
                'threshold': zone.get('threshold_seconds', 0),
                'label': zone.get('name', '禁停区'),
            })

        for event in anomaly_events:
            bbox = [int(v) for v in event.get('bbox', [])]
            overlay['data']['road_anomalies'].append({
                'bbox': bbox,
                'label': event.get('data', {}).get('anomaly_type', 'anomaly'),
                'status': event.get('status', 'warning'),
                'affected_lane': event.get('data', {}).get('affected_lane'),
                'duration_frames': event.get('data', {}).get('duration_frames', 0),
            })

        return overlay

    def _save_debug_frame(self, frame, frame_count, vehicle_bboxes, events):
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
        types = ['plate_recognition', 'traffic_density', 'illegal_parking', 'road_anomaly']
        return types[(frame_count // 10) % len(types)]

    def _generate_mock_result(self, device_id, timestamp, event_type):
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
        try:
            event_type = result['event_type']
            self.socketio.emit('analysis_result', result)
            print(f"推送结果: {event_type}")

            scene_id = None
            device = self.device_manager.get_device(result.get('device_id')) if result.get('device_id') else None
            if device:
                scene_id = device.scene_id

            # video_overlay / connection-like transient messages 不入库
            if event_type not in {'video_overlay', 'anomaly_calibration', 'video_segment_uploaded'}:
                mysql_client.insert_recognition_event(event_type, result.get('device_id'), result, scene_id=scene_id)
            if event_type in {'illegal_parking', 'road_anomaly'} and result.get('status') == 'warning':
                mysql_client.insert_alarm_record(event_type, result.get('device_id'), result, scene_id=scene_id)
        except Exception as e:
            print(f"推送结果失败: {str(e)}")

    def _send_error(self, device_id, error_message):
        try:
            self.socketio.emit('error', {
                'device_id': device_id,
                'message': error_message,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"发送错误信息失败: {str(e)}")

    def get_active_streams(self):
        return list(self.active_streams.keys())


if __name__ == '__main__':
    from device_manager import DeviceManager

    class MockSocketIO:
        def emit(self, event, data):
            print(f"[SocketIO] {event}: {data}")

    device_manager = DeviceManager()
    socketio = MockSocketIO()

    processor = VideoProcessor(device_manager, socketio)
    device_manager.register_device(
        device_id="test_001",
        stream_url="rtmp://localhost:1935/live/test_001",
        resolution="1280x720",
        fps=15,
        scene_id="test_scene"
    )

    print("\n视频处理引擎测试完成")
