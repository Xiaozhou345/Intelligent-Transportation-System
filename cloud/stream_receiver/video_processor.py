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
import numpy as np
import struct
import subprocess
import threading
import time
from queue import Empty, Full, Queue
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
from plate_recognition.plate_recognizer import (
    PlateRecognizer,
    crop_plate_image,
    is_ocr_candidate_crop,
    is_valid_plate_number,
    normalize_plate_number,
)
from lane_detection import LaneDetector

# 添加父目录到Python路径以支持database模块导入
CURRENT_DIR_VP = os.path.dirname(os.path.abspath(__file__))
CLOUD_DIR_VP = os.path.dirname(CURRENT_DIR_VP)
if CLOUD_DIR_VP not in sys.path:
    sys.path.insert(0, CLOUD_DIR_VP)

from database import mysql_client


FRAME_HEADER = struct.Struct("<4sIIId")
FRAME_MAGIC = b"ITSF"
MAX_CAPTURE_FRAME_BYTES = 64 * 1024 * 1024


def _read_exact(stream, size):
    """Read exactly size bytes from a subprocess pipe, or None at EOF."""
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class VideoProcessor:
    """视频流处理器"""

    def __init__(self, device_manager, socketio):
        self.device_manager = device_manager
        self.socketio = socketio
        self.active_streams = {}  # {device_id: thread}
        self.stop_flags = {}  # {device_id: stop_event}

        self.frame_skip = int(os.getenv("ITS_FRAME_SKIP", "1"))
        self.enable_mock_fallback = os.getenv("ITS_ENABLE_MOCK_FALLBACK", "true").lower() == "true"
        self.disable_vehicle_mask = os.getenv("ITS_DISABLE_VEHICLE_MASK", "false").lower() == "true"
        # The sandbox vehicle model can label small cardboard obstacles as
        # vehicles around 0.65-0.70 confidence. Keep the normal detector
        # threshold independent, but require stronger evidence before an
        # object is excluded from road-anomaly analysis.
        self.vehicle_mask_min_conf = float(os.getenv("ITS_VEHICLE_MASK_MIN_CONF", "0.75"))
        self.emit_vehicle_events = os.getenv("ITS_EMIT_VEHICLE_EVENTS", "false").lower() == "true"
        self.disable_drivable_segmenter = os.getenv("ITS_DISABLE_DRIVABLE_SEGMENTER", "true").lower() == "true"
        self.debug_output_dir = REPO_ROOT / "data" / "sandbox_anomaly" / "output"

        self.anomaly_processor = None
        self.anomaly_backend = "disabled"
        self.vehicle_detector = None
        self.plate_detector = None
        self.plate_recognizer = None
        self.vehicle_conf = float(os.getenv("ITS_VEHICLE_CONF", "0.50"))
        self.plate_conf = float(os.getenv("ITS_PLATE_CONF", "0.20"))

        # 性能优化参数
        self.plate_recognition_skip = int(os.getenv("ITS_PLATE_RECOGNITION_SKIP", "1"))  # 改为 1，每帧都检测
        self.overlay_push_skip = int(os.getenv("ITS_OVERLAY_PUSH_SKIP", "1"))
        self.plate_in_vehicle_scene = os.getenv(
            "ITS_PLATE_IN_VEHICLE_SCENE", "false"
        ).lower() == "true"
        self.frame_log_every = max(1, int(os.getenv("ITS_FRAME_LOG_EVERY", "30")))
        self.perf_log_every = max(1, int(os.getenv("ITS_PERF_LOG_EVERY", "30")))
        self.anomaly_auto_start = os.getenv(
            "ITS_ANOMALY_AUTO_START", "true"
        ).lower() == "true"

        # 车牌号缓存：{device_id: [(bbox, plate_number, timestamp), ...]}
        self.plate_cache: Dict[str, List[tuple]] = {}

        # 车牌事件去重缓存：{device_id: {plate_number: last_sent_timestamp}}
        # 用于防止同一车牌短时间内重复推送到前端
        self.sent_plates: Dict[str, Dict[str, float]] = {}
        self.plate_cooldown = float(os.getenv("ITS_PLATE_COOLDOWN", "30.0"))  # 默认30秒冷却时间

        # 车辆检测事件去重缓存：{device_id: {track_id: last_sent_timestamp}}
        # 用于防止同一辆车短时间内重复推送到前端（与车牌去重逻辑一致）
        self.sent_vehicles: Dict[str, Dict[int, float]] = {}
        self.vehicle_cooldown = float(os.getenv("ITS_VEHICLE_COOLDOWN", "30.0"))  # 默认30秒冷却时间

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
            "anomaly_min_background_frames": 20,
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

            common_detector_kwargs = dict(
                min_area=int(os.getenv("ITS_ANOMALY_MIN_AREA", "700")),
                max_area=int(os.getenv("ITS_ANOMALY_MAX_AREA", "0")) or None,
                max_area_ratio=float(os.getenv("ITS_ANOMALY_MAX_AREA_RATIO", "0.08")),
                static_frames_threshold=int(os.getenv("ITS_ANOMALY_STATIC_FRAMES", "6")),
                max_missed_frames=int(os.getenv("ITS_ANOMALY_MAX_MISSED", "4")),
                vehicle_mask_padding=int(os.getenv("ITS_VEHICLE_MASK_PADDING", "16")),
                vehicle_mask_padding_ratio=float(os.getenv("ITS_VEHICLE_MASK_PADDING_RATIO", "0.10")),
                road_roi=self._scale_polygon_for_base_size(self.runtime_defaults.get("anomaly_road_roi", [])),
                road_scope_erode=int(os.getenv("ITS_ANOMALY_ROAD_EDGE_MARGIN", "6")),
                min_road_overlap=float(os.getenv("ITS_ANOMALY_MIN_ROAD_OVERLAP", "0.85")),
                min_component_extent=float(os.getenv("ITS_ANOMALY_MIN_EXTENT", "0.16")),
                component_merge_kernel=int(os.getenv("ITS_ANOMALY_MERGE_KERNEL", "11")),
                max_candidates=int(os.getenv("ITS_ANOMALY_MAX_CANDIDATES", "3")),
                max_foreground_ratio=float(os.getenv("ITS_ANOMALY_MAX_FOREGROUND_RATIO", "0.16")),
                use_default_road_scope=os.getenv("ITS_USE_DEFAULT_ROAD_SCOPE", "true").lower() == "true",
                max_background_vehicle_ratio=float(os.getenv("ITS_BG_MAX_VEHICLE_RATIO", "0.18")),
            )

            requested_backend = os.getenv(
                "ITS_ANOMALY_BACKEND",
                "dino_reference",
            ).strip().lower()
            if requested_backend in {"dino", "dinov2", "dino_reference"}:
                try:
                    from anomaly_detection.dino_reference_detector import DinoReferenceDetector

                    dino_detector_kwargs = dict(common_detector_kwargs)
                    dino_detector_kwargs["max_candidates"] = int(
                        os.getenv("ITS_DINO_MAX_CANDIDATES", "1")
                    )
                    dino_detector_kwargs["max_background_vehicle_ratio"] = float(
                        os.getenv("ITS_DINO_MAX_BG_VEHICLE_RATIO", "0.65")
                    )
                    detector = DinoReferenceDetector(
                        model_name=os.getenv("ITS_DINO_MODEL", "dinov2_vits14_reg"),
                        image_size=int(os.getenv("ITS_DINO_IMAGE_SIZE", "518")),
                        local_radius=int(os.getenv("ITS_DINO_LOCAL_RADIUS", "1")),
                        heat_threshold=float(os.getenv("ITS_DINO_HEAT_THRESHOLD", "0.18")),
                        pixel_threshold=float(os.getenv("ITS_DINO_PIXEL_THRESHOLD", "0.14")),
                        threshold_quantile=float(os.getenv("ITS_DINO_THRESHOLD_QUANTILE", "0.99")),
                        threshold_margin=float(os.getenv("ITS_DINO_THRESHOLD_MARGIN", "1.25")),
                        top_fraction=float(os.getenv("ITS_DINO_TOP_FRACTION", "0.005")),
                        camera_change_ratio=float(os.getenv("ITS_DINO_CAMERA_CHANGE_RATIO", "0.30")),
                        camera_change_frames=int(os.getenv("ITS_DINO_CAMERA_CHANGE_FRAMES", "3")),
                        allow_background_vehicles=os.getenv(
                            "ITS_DINO_ALLOW_BG_VEHICLES",
                            "true",
                        ).lower() == "true",
                        min_thin_side=int(os.getenv("ITS_DINO_MIN_THIN_SIDE", "18")),
                        max_thin_aspect=float(os.getenv("ITS_DINO_MAX_THIN_ASPECT", "4.0")),
                        filter_lane_markings=False,
                        **dino_detector_kwargs,
                    )
                    self.anomaly_backend = "dino_reference"
                    print("✅ 道路异常后端: DINOv2固定机位参考特征")
                except Exception as dino_exc:
                    print(f"⚠️  DINOv2异常后端加载失败，回退MOG2: {dino_exc}")
                    requested_backend = "mog2"

            if requested_backend == "mog2":
                detector = AnomalyDetector(
                    warmup_frames=int(os.getenv("ITS_ANOMALY_WARMUP_FRAMES", "0")),
                    learning_rate=float(os.getenv("ITS_ANOMALY_LEARNING_RATE", "0")),
                    background_learning_rate=float(os.getenv("ITS_ANOMALY_BG_LEARNING_RATE", "-1")),
                    startup_static_check=os.getenv("ITS_STARTUP_STATIC_CHECK", "false").lower() == "true",
                    startup_static_kernel=int(os.getenv("ITS_STARTUP_STATIC_KERNEL", "55")),
                    startup_static_dilate=int(os.getenv("ITS_STARTUP_STATIC_DILATE", "7")),
                    road_surface_outlier_check=os.getenv("ITS_ROAD_SURFACE_OUTLIER", "false").lower() == "true",
                    outlier_min_area=int(os.getenv("ITS_OUTLIER_MIN_AREA", "700")),
                    outlier_color_distance=float(os.getenv("ITS_OUTLIER_COLOR_DISTANCE", "30")),
                    outlier_max_area=int(os.getenv("ITS_OUTLIER_MAX_AREA", "30000")),
                    filter_lane_markings=os.getenv("ITS_FILTER_LANE_MARKINGS", "true").lower() == "true",
                    **common_detector_kwargs,
                )
                self.anomaly_backend = "mog2"

            if self.anomaly_backend == "disabled":
                raise ValueError(f"不支持的道路异常后端: {requested_backend}")
            self.anomaly_processor = RoadAnomalyProcessor(
                detector=detector,
                drivable_model_path=drivable_model_path,
                event_cooldown_frames=int(os.getenv("ITS_ANOMALY_EVENT_COOLDOWN", "30")),
                max_current_results=int(os.getenv("ITS_ANOMALY_MAX_RESULTS", "3")),
            )
            print("✅ 沙盘道路异常检测已启用")

            # 初始化车道线检测器
            self.lane_detector = LaneDetector(
                min_line_length=int(os.getenv("ITS_LANE_MIN_LENGTH", "100")),
                max_line_gap=int(os.getenv("ITS_LANE_MAX_GAP", "50")),
                threshold=int(os.getenv("ITS_LANE_THRESHOLD", "50")),
                vertical_tolerance=float(os.getenv("ITS_LANE_VERTICAL_TOLERANCE", "15.0")),
                cache_frames=int(os.getenv("ITS_LANE_CACHE_FRAMES", "10")),
            )
            print("✅ 车道线检测器已初始化")
        except Exception as e:
            print(f"⚠️  沙盘道路异常检测初始化失败，将使用模拟降级: {str(e)}")
            self.anomaly_processor = None
            self.lane_detector = None

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
                    os.path.join(AI_MODELS_DIR, "plate_recognition", "sandbox_lprnet_best.pth"),
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
                    # track_thresh应 <= vehicle_conf，确保检测器输出能被跟踪器接受
                    # 使用稍低的阈值，允许跟踪器处理置信度略低但时序连续的检测
                    track_thresh=float(os.getenv("ITS_TRACKER_TRACK_THRESH", "0.35")),
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
                "last_plate_events": [],
                "stream_connected": False,
                "last_frame_received_at": None,
                "last_frame_analyzed_at": None,
                "stream_reconnect_count": 0,
            }
            self.runtime_state[device_id] = state

        if frame_shape is not None and state["frame_shape"] != frame_shape:
            # 检测到分辨率变化，可能是视频源切换
            old_shape = state["frame_shape"]
            is_stream_switch = old_shape is not None  # 不是首次初始化

            state["frame_shape"] = frame_shape
            state["traffic_regions"] = self._scale_regions(self.runtime_defaults.get("traffic_regions", []), frame_shape)
            state["no_parking_zones"] = self._scale_regions(self.runtime_defaults.get("no_parking_zones", []), frame_shape)
            state["anomaly_road_roi"] = self._scale_polygon(self.runtime_defaults.get("anomaly_road_roi", []), frame_shape)

            # 🔄 视频源切换：重置所有跟踪状态
            if is_stream_switch:
                print(f"🔄 检测到视频分辨率变化 {old_shape} → {frame_shape}，重置跟踪状态")

                # 1. 重置ByteTrack跟踪器
                state["tracker"].reset()

                # 2. 重置违停监控状态
                state["parking_monitor"].track_states.clear()
                state["parking_monitor"].recent_alerts.clear()
                if hasattr(state["parking_monitor"], '_debug_logged'):
                    delattr(state["parking_monitor"], '_debug_logged')
                if hasattr(state["parking_monitor"], '_no_zone_logged_count'):
                    delattr(state["parking_monitor"], '_no_zone_logged_count')

                # 3. 清空车牌去重缓存
                if device_id in self.sent_plates:
                    self.sent_plates[device_id].clear()

                # 4. 清空车辆去重缓存
                if device_id in self.sent_vehicles:
                    self.sent_vehicles[device_id].clear()

                # 5. 重置帧计数
                state["processed_frames"] = 0

                print(f"   ✅ 已清空跟踪器、违停监控、车牌/车辆去重缓存")

            # 更新违停监控的禁停区配置
            state["parking_monitor"].zones = state["no_parking_zones"]

            # 输出调试信息：禁停区配置
            print(f"🚨 违停监控配置更新 (分辨率: {frame_shape[1]}x{frame_shape[0]}):")
            print(f"   - 配置了 {len(state['no_parking_zones'])} 个禁停区")
            for zone in state["no_parking_zones"]:
                zone_name = zone.get('name', zone.get('zone_id'))
                polygon = zone.get('polygon', [])
                threshold = zone.get('threshold_seconds', 30)
                if polygon:
                    xs = [p[0] for p in polygon]
                    ys = [p[1] for p in polygon]
                    print(f"   - {zone_name}: 阈值={threshold}s, 范围=X[{min(xs)}-{max(xs)}] Y[{min(ys)}-{max(ys)}]")

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

    def _build_effective_road_mask(self, frame, state):
        """Build the exact road mask used by calibration and anomaly detection."""
        height, width = frame.shape[:2]
        manual_mask = None
        polygon = state.get("anomaly_road_roi") or []
        if len(polygon) >= 3:
            manual_mask = np.zeros((height, width), dtype=np.uint8)
            cv2.fillPoly(manual_mask, [np.asarray(polygon, dtype=np.int32)], 255)

        predicted_mask = None
        if self.anomaly_processor:
            predicted_mask = self.anomaly_processor.predict_road_mask(frame)
        if predicted_mask is not None:
            if predicted_mask.shape[:2] != (height, width):
                predicted_mask = cv2.resize(
                    predicted_mask, (width, height), interpolation=cv2.INTER_NEAREST
                )
            predicted_mask = np.where(predicted_mask > 0, 255, 0).astype(np.uint8)
            coverage = cv2.countNonZero(predicted_mask) / float(max(1, width * height))
            # An empty or nearly full segmentation is not a usable road scope.
            if coverage < 0.03 or coverage > 0.90:
                predicted_mask = None

        if manual_mask is not None and predicted_mask is not None:
            combined = cv2.bitwise_and(manual_mask, predicted_mask)
            manual_area = max(1, cv2.countNonZero(manual_mask))
            if cv2.countNonZero(combined) / float(manual_area) >= 0.20:
                return combined
            return manual_mask
        return manual_mask if manual_mask is not None else predicted_mask

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
            existing_thread = self.active_streams[device_id]
            if existing_thread.is_alive():
                print(f"设备 {device_id} 已在处理中")
                return False
            self.active_streams.pop(device_id, None)
            self.stop_flags.pop(device_id, None)
            print(f"设备 {device_id} 的旧处理线程已退出，正在重新启动")

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

        # 设置停止标志，通知处理线程退出
        self.stop_flags[device_id].set()
        self.active_streams[device_id].join(timeout=5)

        # 清理线程资源
        del self.active_streams[device_id]
        del self.stop_flags[device_id]

        # 清理运行时状态（包含ByteTrack跟踪器）
        state = self.runtime_state.pop(device_id, None)
        if state and "tracker" in state:
            # ByteTrack跟踪器可能有内部缓存，确保清理
            # 避免设备重新注册时track_id冲突
            del state["tracker"]
            print(f"已清理设备 {device_id} 的跟踪器状态（防止track_id冲突）")

        # 清理车牌缓存
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
        plate_number = normalize_plate_number(plate_number)
        if not is_valid_plate_number(plate_number):
            return

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
        candidate_scores = {}

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

            if score > 0.3:
                age = max(0.0, time.time() - timestamp)
                recency_weight = max(0.2, 1.0 - age / 30.0)
                candidate_scores[plate_number] = candidate_scores.get(plate_number, 0.0) + score * recency_weight

        if not candidate_scores:
            return ""
        return max(candidate_scores.items(), key=lambda item: item[1])[0]

    def _process_stream(self, device_id, stream_url, stop_event):
        if not os.path.exists(stream_url):
            return self._process_live_stream(device_id, stream_url, stop_event)

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

            # 缓冲区清理策略：高频检查并跳过积压的旧帧，确保读取最新帧
            # 这对于实时流（RTSP/RTMP）至关重要，可大幅降低延迟
            last_buffer_clear_time = time.time()
            buffer_clear_interval = 0.5  # 每0.5秒清理一次缓冲区（从2秒大幅降低）

            # 性能监控：视频流读取统计
            stream_perf = {
                'buffer_clear_count': 0,
                'buffer_clear_total_time': 0,
                'frame_read_count': 0,
                'frame_read_total_time': 0,
                'frame_decode_count': 0,
                'last_report_time': time.time()
            }

            while not stop_event.is_set():
                loop_start = time.time()

                # 对于实时流：高频清空缓冲区，只处理最新帧
                if not is_local_file:
                    current_time = time.time()
                    if current_time - last_buffer_clear_time >= buffer_clear_interval:
                        # 性能监控：缓冲区清理耗时
                        clear_start = time.time()

                        # 快速抓取并丢弃缓冲区中的旧帧（不解码）
                        # 注意：OpenCV的缓冲区大小通常是5-10帧
                        buffer_size = int(cap.get(cv2.CAP_PROP_BUFFERSIZE)) if cap.get(cv2.CAP_PROP_BUFFERSIZE) > 0 else 5
                        for _ in range(buffer_size - 1):
                            cap.grab()  # 只抓取不解码，非常快

                        clear_time = (time.time() - clear_start) * 1000
                        stream_perf['buffer_clear_count'] += 1
                        stream_perf['buffer_clear_total_time'] += clear_time
                        last_buffer_clear_time = current_time

                # 性能监控：读帧耗时
                read_start = time.time()
                ret, frame = cap.read()
                read_time = (time.time() - read_start) * 1000
                stream_perf['frame_read_total_time'] += read_time
                stream_perf['frame_read_count'] += 1

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

                # 统计解码帧数（实际用于AI分析的帧）
                stream_perf['frame_decode_count'] += 1

                # 每30秒输出一次视频流性能统计
                current_time = time.time()
                if current_time - stream_perf['last_report_time'] >= 30:
                    avg_read_time = stream_perf['frame_read_total_time'] / stream_perf['frame_read_count'] if stream_perf['frame_read_count'] > 0 else 0
                    avg_clear_time = stream_perf['buffer_clear_total_time'] / stream_perf['buffer_clear_count'] if stream_perf['buffer_clear_count'] > 0 else 0
                    fps = stream_perf['frame_read_count'] / 30.0
                    decode_fps = stream_perf['frame_decode_count'] / 30.0

                    print(f"\n{'='*80}")
                    print(f"📹 视频流性能统计 - {device_id}")
                    print(f"{'='*80}")
                    print(f"🎥 视频源: {stream_url}")
                    print(f"📊 读取帧率: {fps:.2f} fps  (原始)")
                    print(f"📊 处理帧率: {decode_fps:.2f} fps  (经过frame_skip={self.frame_skip})")
                    print(f"⏱️  平均读帧耗时: {avg_read_time:.2f} ms")
                    print(f"⏱️  平均缓冲清理耗时: {avg_clear_time:.2f} ms")
                    print(f"🧹 缓冲清理次数: {stream_perf['buffer_clear_count']} 次/30秒")
                    print(f"{'='*80}\n")

                    # 重置统计
                    stream_perf['buffer_clear_count'] = 0
                    stream_perf['buffer_clear_total_time'] = 0
                    stream_perf['frame_read_count'] = 0
                    stream_perf['frame_read_total_time'] = 0
                    stream_perf['frame_decode_count'] = 0
                    stream_perf['last_report_time'] = current_time

                self._analyze_frame(device_id, frame, frame_count)
                # 删除了 time.sleep(0.1)，让处理循环以最快速度运行
                # AI处理本身已经有足够的耗时，不需要额外sleep

        except Exception as e:
            print(f"视频流处理异常 {device_id}: {str(e)}")
            self._send_error(device_id, str(e))

        finally:
            if cap:
                cap.release()
            print(f"视频流处理结束: {device_id}")

    def _start_capture_worker(self, stream_url, failures_before_reconnect):
        """Start the isolated OpenCV process that owns the RTSP connection."""
        worker_path = Path(__file__).with_name("rtsp_capture_worker.py")
        command = [
            sys.executable,
            "-u",
            str(worker_path),
            stream_url,
            "--open-timeout-ms",
            os.getenv("ITS_STREAM_OPEN_TIMEOUT_MS", "5000"),
            "--read-timeout-ms",
            os.getenv("ITS_STREAM_READ_TIMEOUT_MS", "5000"),
            "--read-failures",
            str(failures_before_reconnect),
            "--failure-grace-seconds",
            os.getenv("ITS_STREAM_FAILURE_GRACE", "6"),
            "--send-every",
            os.getenv("ITS_CAPTURE_FRAME_SKIP", "2"),
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creationflags,
        )

    def _process_live_stream(self, device_id, stream_url, stop_event):
        """
        拉流与 AI 推理解耦。采集线程始终覆盖一格队列中的旧帧，
        推理慢时丢弃过期帧，不会累积成数秒延迟。读取连续失败时重建连接。
        """
        latest_frame = Queue(maxsize=1)
        failures_before_reconnect = max(1, int(os.getenv("ITS_STREAM_READ_FAILURES", "5")))
        reconnect_delay = max(0.2, float(os.getenv("ITS_STREAM_RECONNECT_DELAY", "1")))
        stall_timeout = max(3.0, float(os.getenv("ITS_STREAM_STALL_TIMEOUT", "10")))

        def publish_latest(item):
            try:
                latest_frame.put_nowait(item)
            except Full:
                try:
                    latest_frame.get_nowait()
                except Empty:
                    pass
                try:
                    latest_frame.put_nowait(item)
                except Full:
                    pass

        def capture_loop():
            sequence = 0
            attempt = 0
            connected_once = False
            state = self._get_or_create_runtime_state(device_id)

            while not stop_event.is_set():
                process = self._start_capture_worker(stream_url, failures_before_reconnect)
                reader_done = threading.Event()
                first_frame = threading.Event()
                last_frame_time = {"value": time.monotonic()}
                session_error = {"value": "采集进程已结束"}

                def read_worker_frames():
                    nonlocal sequence, connected_once, attempt
                    try:
                        while not stop_event.is_set():
                            header_data = _read_exact(process.stdout, FRAME_HEADER.size)
                            if header_data is None:
                                break
                            magic, width, height, channels, captured_at = FRAME_HEADER.unpack(header_data)
                            payload_size = int(width) * int(height) * int(channels)
                            if (
                                magic != FRAME_MAGIC
                                or width <= 0
                                or height <= 0
                                or channels not in (1, 3, 4)
                                or payload_size > MAX_CAPTURE_FRAME_BYTES
                            ):
                                session_error["value"] = "采集进程返回了无效帧"
                                break

                            payload = _read_exact(process.stdout, payload_size)
                            if payload is None:
                                session_error["value"] = "采集进程输出中断"
                                break

                            if not first_frame.is_set():
                                if connected_once:
                                    print(f"视频流已重连: {device_id}")
                                    # 标记流重连，下一帧处理时将重置跟踪状态
                                    state["stream_reconnected"] = True
                                else:
                                    print(f"成功连接视频流: {device_id}")
                                connected_once = True
                                attempt = 0
                                first_frame.set()

                            frame = np.frombuffer(payload, dtype=np.uint8)
                            if channels == 1:
                                frame = frame.reshape((height, width))
                            else:
                                frame = frame.reshape((height, width, channels))

                            received_at = time.monotonic()
                            last_frame_time["value"] = received_at
                            state["stream_connected"] = True
                            state["last_frame_received_at"] = time.time()
                            sequence += 1
                            publish_latest((sequence, frame, captured_at))
                    except Exception as exc:
                        session_error["value"] = f"采集管道异常: {exc}"
                    finally:
                        reader_done.set()

                session_reader = threading.Thread(
                    target=read_worker_frames,
                    name=f"video-pipe-{device_id}",
                    daemon=True,
                )
                session_reader.start()

                while not stop_event.is_set():
                    if reader_done.wait(timeout=0.25):
                        return_code = process.poll()
                        session_error["value"] = f"采集进程退出 (code={return_code})"
                        break
                    stalled_for = time.monotonic() - last_frame_time["value"]
                    if stalled_for >= stall_timeout:
                        session_error["value"] = f"{stalled_for:.1f} 秒未收到新帧"
                        break

                state["stream_connected"] = False
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)

                session_reader.join(timeout=2)
                stderr_text = ""
                try:
                    stderr_text = process.stderr.read().decode("utf-8", errors="replace").strip()
                except (AttributeError, OSError):
                    pass
                finally:
                    for pipe in (process.stdout, process.stderr):
                        try:
                            pipe.close()
                        except (AttributeError, OSError):
                            pass

                if not stop_event.is_set():
                    attempt += 1
                    state["stream_reconnect_count"] = state.get("stream_reconnect_count", 0) + 1
                    detail = session_error["value"]
                    if stderr_text:
                        detail = f"{detail}; {stderr_text.splitlines()[-1]}"
                    if first_frame.is_set() or attempt == 1 or attempt % 5 == 0:
                        print(f"视频流 {device_id} 停滞 ({detail})，正在重建采集进程")
                    stop_event.wait(reconnect_delay)


        reader = threading.Thread(
            target=capture_loop,
            name=f"video-capture-{device_id}",
            daemon=True,
        )
        reader.start()

        last_sequence = 0
        analyzed_count = 0
        try:
            while not stop_event.is_set():
                try:
                    sequence, frame, captured_at = latest_frame.get(timeout=1.0)
                except Empty:
                    continue
                if sequence <= last_sequence:
                    continue
                last_sequence = sequence
                if sequence % max(1, self.frame_skip) != 0:
                    continue

                analyzed_count += 1
                state = self._get_or_create_runtime_state(device_id, frame.shape)
                state["capture_to_analysis_ms"] = round((time.monotonic() - captured_at) * 1000, 1)
                try:
                    self._analyze_frame(device_id, frame, sequence)
                    state["last_frame_analyzed_at"] = time.time()
                except Exception as frame_exc:
                    print(f"单帧分析异常 {device_id}: {frame_exc}，继续处理后续帧")
                    self._send_error(device_id, str(frame_exc))
        except Exception as exc:
            print(f"视频流处理异常 {device_id}: {exc}")
            self._send_error(device_id, str(exc))
        finally:
            stop_event.set()
            reader.join(timeout=6)
            print(f"视频流处理结束: {device_id}，已分析 {analyzed_count} 帧")

    def _analyze_frame(self, device_id, frame, frame_count):
        # 防御性检查：确保frame有效（虽然上层已检查ret，但额外保护避免异常）
        if frame is None or frame.size == 0:
            print(f"⚠️  帧 {frame_count} 无效（frame为空或size=0），跳过分析")
            return

        # 🔄 检测并处理流重连（即使分辨率相同也要重置跟踪）
        state = self.runtime_state.get(device_id)
        if state and state.get("stream_reconnected"):
            print(f"🔄 处理流重连事件 {device_id}，重置跟踪状态")

            # 1. 重置ByteTrack跟踪器
            state["tracker"].reset()

            # 2. 重置违停监控状态
            state["parking_monitor"].track_states.clear()
            state["parking_monitor"].recent_alerts.clear()
            if hasattr(state["parking_monitor"], '_debug_logged'):
                delattr(state["parking_monitor"], '_debug_logged')
            if hasattr(state["parking_monitor"], '_no_zone_logged_count'):
                delattr(state["parking_monitor"], '_no_zone_logged_count')
            if hasattr(state["parking_monitor"], '_update_call_count'):
                delattr(state["parking_monitor"], '_update_call_count')

            # 3. 清空车牌去重缓存
            if device_id in self.sent_plates:
                self.sent_plates[device_id].clear()

            # 4. 清空车辆去重缓存
            if device_id in self.sent_vehicles:
                self.sent_vehicles[device_id].clear()

            # 5. 流重连后固定机位参考可能已失效，重新标定道路背景
            if self.anomaly_processor:
                self.anomaly_processor.reset()
                state["anomaly_mode"] = "background_learning"
                state["anomaly_background_frames"] = 0
                state["anomaly_background_skipped_frames"] = 0

            # 6. 重置帧计数
            state["processed_frames"] = 0

            # 7. 清除重连标记
            state["stream_reconnected"] = False

            print(f"   ✅ 已清空跟踪器、违停监控、车牌/车辆去重缓存")

        # ============ 性能监控：记录总耗时 ============
        frame_start_time = time.time()
        perf_timings = {}  # 记录各步骤耗时

        timestamp = datetime.now().isoformat()
        state = self._get_or_create_runtime_state(device_id, frame.shape)
        state["processed_frames"] += 1
        state["current_frame"] = frame  # 保存当前帧供车道检测使用
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
            # ============ 步骤1：车辆检测 ============
            step_start = time.time()
            vehicles = self.vehicle_detector.detect(frame)
            perf_timings['vehicle_detection'] = (time.time() - step_start) * 1000  # 转为毫秒

            # ============ 步骤2：车辆跟踪 ============
            step_start = time.time()
            tracked_vehicles = state["tracker"].update(vehicles)
            perf_timings['vehicle_tracking'] = (time.time() - step_start) * 1000

            # 如果检测结果为空，记录日志（可能是夜间、镜头遮挡、空旷路段）
            if not vehicles and frame_count % 90 == 0:
                print(f"⚠️  帧 {frame_count}: 车辆检测结果为空（可能原因：夜间、遮挡、空旷路段）")

            # ============ 步骤3：车辆掩膜计算 ============
            step_start = time.time()
            # 使用tracked_vehicles而非vehicles构建掩膜，确保数据一致性
            # 同时保持高置信度过滤，避免低置信度车辆被误报为道路异常
            vehicle_bboxes = [
                tracked["bbox"]
                for tracked in tracked_vehicles
                if tracked.get("confidence", 0) >= self.vehicle_mask_min_conf
            ]
            perf_timings['vehicle_mask'] = (time.time() - step_start) * 1000

        # ============ 步骤4：车牌检测+识别 ============
        plate_events = []
        plates_refreshed = False
        plate_scene_enabled = (
            active_scene == 'plate_recognition'
            or (active_scene == 'vehicle_detection' and self.plate_in_vehicle_scene)
        )

        # 调试日志：记录车牌检测条件
        if frame_count % 30 == 0:  # 每30帧打印一次
            print(f"🔍 车牌检测条件检查:")
            print(f"   active_scene: {active_scene}")
            print(f"   plate_scene_enabled: {plate_scene_enabled}")
            print(f"   self.plate_detector: {self.plate_detector is not None}")
            print(f"   processed_frames: {state['processed_frames']}")
            print(f"   skip_check: {state['processed_frames'] % self.plate_recognition_skip == 0}")

        if (
            plate_scene_enabled
            and self.plate_detector
            and state["processed_frames"] % self.plate_recognition_skip == 0
        ):
            step_start = time.time()
            # 车牌识别性能优化：不需要每帧都识别，降低频率（默认每3帧识别一次）
            # 因为车牌识别（LPRNet）是最耗时的操作之一（50-100ms/车牌）
            detected_plates = self.plate_detector.detect(frame)
            perf_timings['plate_detection'] = (time.time() - step_start) * 1000

            # 车牌识别（LPRNet）
            step_start = time.time()
            plate_recognition_count = 0
            for plate in detected_plates:
                bbox = plate["bbox"]
                plate_number = ""

                # 如果有LPRNet，立即识别车牌号
                if self.plate_recognizer:
                    plate_img = crop_plate_image(frame, bbox)
                    if is_ocr_candidate_crop(plate_img):
                        try:
                            plate_recognition_count += 1
                            plate_number = self.plate_recognizer.recognize_best(plate_img)
                            # 如果识别成功，更新缓存
                            if is_valid_plate_number(plate_number):
                                self.update_plate_number(device_id, bbox, plate_number)
                            else:
                                plate_number = ""
                        except Exception as e:
                            print(f"⚠️  车牌OCR失败 (frame {frame_count}): {str(e)}")

                # 如果没有识别出来，尝试从缓存匹配
                if not plate_number:
                    plate_number = self._match_plate_number(device_id, bbox)

                # 构建plate_recognition事件（独立事件，用于车牌记录表）
                # 注意：此事件与video_overlay.plates和vehicle_detection.plate_number用途不同：
                # - plate_recognition：独立的车牌识别记录，发送到PlateRecognitionPanel
                # - video_overlay.plates：视频画面叠加显示，包含bbox和label
                # - vehicle_detection.plate_number：车辆记录中的关联字段
                plate_events.append({
                    "event_type": "plate_recognition",
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "bbox": bbox,
                    "status": "normal",
                    "data": {
                        "plate_number": plate_number,
                        "confidence": plate["confidence"],
                        # 未来扩展字段（当前未实现白名单和决策逻辑）
                        # "is_in_whitelist": False,
                        # "decision": "unknown",
                    },
                })

            state["last_plate_events"] = plate_events
            plates_refreshed = True

            if plate_recognition_count > 0:
                perf_timings['plate_recognition'] = (time.time() - step_start) * 1000
                perf_timings['plate_recognition_per_plate'] = perf_timings['plate_recognition'] / plate_recognition_count
        elif plate_scene_enabled:
            # Reuse the most recent boxes between inference passes so overlays do not blink.
            plate_events = list(state.get("last_plate_events", []))
        else:
            state["last_plate_events"] = []
            perf_timings['plate_detection'] = 0
            perf_timings['plate_recognition'] = 0

        # 将车牌识别结果发送到前端（仅在相关场景下发送，保持与其他事件的一致性）
        # 添加去重逻辑：同一车牌在冷却时间内只发送一次
        if plates_refreshed and active_scene in ['vehicle_detection', 'plate_recognition']:
            current_time = time.time()

            # 初始化设备的车牌记录
            if device_id not in self.sent_plates:
                self.sent_plates[device_id] = {}

            # 清理过期记录（保留最近60秒的记录，避免内存泄漏）
            expired_plates = [
                plate_num for plate_num, last_time in self.sent_plates[device_id].items()
                if current_time - last_time > 60.0
            ]
            for plate_num in expired_plates:
                del self.sent_plates[device_id][plate_num]

            for plate_event in plate_events:
                plate_number = plate_event['data'].get('plate_number', '')

                # 如果车牌号有效，检查是否在冷却时间内
                if plate_number:
                    last_sent_time = self.sent_plates[device_id].get(plate_number, 0)
                    time_since_last_sent = current_time - last_sent_time

                    # 如果在冷却时间内，跳过发送
                    if time_since_last_sent < self.plate_cooldown:
                        if frame_count % 30 == 0:
                            print(f"⏭️  车牌 {plate_number} 在冷却期内 ({time_since_last_sent:.1f}s < {self.plate_cooldown}s)，跳过推送")
                        continue

                    # 更新最后发送时间
                    self.sent_plates[device_id][plate_number] = current_time

                # 发送事件
                self._send_result(plate_event)
                if frame_count % 30 == 0:
                    print(f"📤 车牌识别推送: {plate_number or '未识别'} conf={plate_event['data']['confidence']:.2f}")

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

            # 初始化设备的车辆去重缓存
            if device_id not in self.sent_vehicles:
                self.sent_vehicles[device_id] = {}

            current_time = time.time()

            # 使用tracked_vehicles而不是vehicles，确保包含track_id，并应用去重逻辑
            for idx, tracked in enumerate(tracked_vehicles):
                track_id = tracked.get("track_id")
                if track_id is None:
                    # 没有track_id的车辆跳过（不应该发生，但防御性编程）
                    continue

                # 检查是否在冷却期内（与车牌去重逻辑一致）
                last_sent_time = self.sent_vehicles[device_id].get(track_id, 0)
                if current_time - last_sent_time < self.vehicle_cooldown:
                    # 在冷却期内，跳过该车辆
                    continue

                # 更新最后发送时间
                self.sent_vehicles[device_id][track_id] = current_time

                plate_number = vehicle_plate_map.get(idx, "")
                self._send_result({
                    "event_type": "vehicle_detection",
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "data": {
                        "vehicle_id": track_id,  # 使用跟踪ID，确保跨帧一致性
                        "vehicle_type": tracked["class_name"],
                        "confidence": tracked["confidence"],
                        "plate_number": plate_number,  # 关联的车牌号
                    },
                    "bbox": tracked["bbox"],
                    "status": "detected",
                })

            # 清理过期的车辆记录（超过冷却时间的2倍）
            expired_track_ids = [
                track_id for track_id, last_time in self.sent_vehicles[device_id].items()
                if current_time - last_time > self.vehicle_cooldown * 2
            ]
            for track_id in expired_track_ids:
                del self.sent_vehicles[device_id][track_id]

        # ============ 步骤5：热力图计算 ============
        step_start = time.time()
        # 热力图事件：基于同一份YOLO检测结果，与车辆检测保持数据一致性
        # 在vehicle_detection和traffic_density场景下都发送，确保前端数据同步
        traffic_event = self._build_traffic_density_event(device_id, state, tracked_vehicles, timestamp)
        if traffic_event is not None and active_scene in ['traffic_density', 'vehicle_detection']:
            self._send_result(traffic_event)
        perf_timings['traffic_density'] = (time.time() - step_start) * 1000

        # ============ 步骤6：违停监控 ============
        step_start = time.time()
        # 违停监控始终运行（维护状态），但只在 illegal_parking 场景下推送事件

        # 增强调试：每帧都输出场景和车辆数（仅在 illegal_parking 场景下）
        if active_scene == 'illegal_parking':
            yolo_count = len(vehicles) if 'vehicles' in locals() else 0
            tracked_count = len(tracked_vehicles)
            print(f"🚨 [Frame {state['processed_frames']}] 违停场景 - YOLO检测: {yolo_count}辆, ByteTrack跟踪: {tracked_count}辆")

        parking_events = state["parking_monitor"].update(device_id, tracked_vehicles, timestamp)
        parking_statuses = state["parking_monitor"].get_active_statuses(timestamp)

        # 输出违停监控调试信息
        if active_scene == 'illegal_parking' and state["processed_frames"] % 30 == 0:
            active_tracks = len([s for s in parking_statuses if s.get('status') in ['monitoring', 'warning']])
            print(f"🚨 违停监控状态: {active_tracks} 辆车在禁停区, 共 {len(tracked_vehicles)} 辆车被跟踪")

        if active_scene == 'illegal_parking':
            for event in parking_events:
                self._send_result(event)
                print(
                    f"🚨🚨🚨 违停告警触发: track_id={event['data'].get('track_id')} "
                    f"stay_time={event['data'].get('stay_time')}s zone={event['data'].get('zone_name')} bbox={event.get('bbox')}"
                )
        perf_timings['illegal_parking'] = (time.time() - step_start) * 1000

        # ============ 步骤7：道路异常检测 ============
        anomaly_events = []
        anomaly_overlay_events = []
        if self.anomaly_processor and active_scene == 'road_anomaly':
            step_start = time.time()
            anomaly_mode = state.get("anomaly_mode", "detecting")
            road_mask = self._build_effective_road_mask(frame, state)
            if anomaly_mode == "background_learning":
                learned = self.anomaly_processor.update_background(
                    frame,
                    road_mask=road_mask,
                    vehicle_bboxes=vehicle_bboxes,
                )

                # 使用anomaly_processor内部的真实计数器，确保统计与实际检测后端一致
                actual_background_frames = self.anomaly_processor.background_frames

                if learned:
                    # state中的计数器仅用于跳过帧统计
                    state["anomaly_background_frames"] = actual_background_frames
                else:
                    state["anomaly_background_skipped_frames"] = state.get("anomaly_background_skipped_frames", 0) + 1

                skipped_frames = state.get("anomaly_background_skipped_frames", 0)
                should_report = (
                    actual_background_frames == 1
                    or (learned and actual_background_frames % 10 == 0)
                    or (not learned and skipped_frames % 5 == 0)
                )
                if should_report:
                    self._send_result({
                        "event_type": "anomaly_calibration",
                        "timestamp": timestamp,
                        "device_id": device_id,
                        "status": "learning" if learned else "skipped",
                        "data": {
                            "background_frames": actual_background_frames,
                            "skipped_frames": skipped_frames,
                            "total_processed": actual_background_frames + skipped_frames,
                            "skip_reason": getattr(
                                self.anomaly_processor.detector,
                                "last_background_skip_reason",
                                None,
                            ),
                            "reason": getattr(
                                self.anomaly_processor.detector,
                                "last_background_skip_reason",
                                None,
                            ),
                            "vehicle_mask_ratio": round(
                                float(getattr(
                                    self.anomaly_processor.detector,
                                    "last_background_vehicle_ratio",
                                    0.0,
                                )),
                                4,
                            ),
                            "valid_road_ratio": round(
                                float(getattr(
                                    self.anomaly_processor.detector,
                                    "last_background_valid_ratio",
                                    0.0,
                                )),
                                4,
                            ),
                        },
                    })
                    print(
                        f"道路异常背景学习中: device={device_id} "
                        f"frames={actual_background_frames} skipped={skipped_frames} "
                        f"vehicle_masks={len(vehicle_bboxes)}"
                    )

                min_background_frames = int(
                    self.runtime_defaults.get("anomaly_min_background_frames", 8)
                )
                if self.anomaly_auto_start and actual_background_frames >= min_background_frames:
                    state["anomaly_mode"] = "detecting"
                    self.runtime_defaults["anomaly_mode"] = "detecting"
                    self._send_result({
                        "event_type": "anomaly_mode_updated",
                        "timestamp": timestamp,
                        "device_id": device_id,
                        "status": "success",
                        "data": {
                            "mode": "detecting",
                            "active_scene": "road_anomaly",
                            "background_frames": actual_background_frames,
                            "min_background_frames": min_background_frames,
                            "message": "background_ready",
                        },
                    })
                    print(
                        f"道路异常背景学习完成，自动进入检测模式: "
                        f"{actual_background_frames}/{min_background_frames}"
                    )
            else:
                anomaly_events = self.anomaly_processor.process_frame(
                    device_id=device_id,
                    frame=frame,
                    vehicle_bboxes=vehicle_bboxes,
                    timestamp=timestamp,
                    road_mask=road_mask,
                )
                detector = self.anomaly_processor.detector
                if getattr(detector, "needs_recalibration", False):
                    self.anomaly_processor.reset()
                    state["anomaly_mode"] = "background_learning"
                    state["anomaly_background_frames"] = 0
                    state["anomaly_background_skipped_frames"] = 0
                    anomaly_events = []
                    anomaly_overlay_events = []
                    self._send_result({
                        "event_type": "anomaly_mode_updated",
                        "timestamp": timestamp,
                        "device_id": device_id,
                        "status": "warning",
                        "data": {
                            "mode": "background_learning",
                            "active_scene": "road_anomaly",
                            "message": "camera_changed_recalibration_started",
                        },
                    })
                    print("检测到镜头位置整体变化，已停止告警并重新标定道路背景")
                else:
                    anomaly_overlay_events = self.anomaly_processor.get_current_results()
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
                    self._save_road_mask_debug(road_mask, frame_count)

            perf_timings['road_anomaly'] = (time.time() - step_start) * 1000
        else:
            perf_timings['road_anomaly'] = 0

        # ============ 步骤8：构建video_overlay ============
        step_start = time.time()
        overlay = self._build_video_overlay(
            device_id=device_id,
            timestamp=timestamp,
            frame=frame,
            state=state,
            active_scene=active_scene,
            tracked_vehicles=tracked_vehicles,
            parking_events=parking_events,
            parking_statuses=parking_statuses,
            anomaly_events=anomaly_overlay_events,
            plate_events=plate_events,
        )
        perf_timings['build_overlay'] = (time.time() - step_start) * 1000
        overlay['analysis_latency_ms'] = round(
            float(state.get("capture_to_analysis_ms", 0))
            + (time.time() - frame_start_time) * 1000,
            1,
        )
        overlay['sequence'] = int(frame_count)

        # ============ 步骤9：在帧上绘制检测框并推送 ============
        step_start = time.time()
        # 新方案：后端直接在视频帧上绘制检测框，然后推送完整画面给前端
        # 这样可以保证视频内容和检测框完全同步，避免WebRTC视频流和WebSocket overlay的时间差
        if state["processed_frames"] % self.overlay_push_skip == 0:
            # 步骤9.1：在帧上绘制检测框
            draw_start = time.time()
            annotated_frame = self._draw_overlay_on_frame(
                frame=frame.copy(),  # 复制一份，避免修改原始帧
                overlay=overlay,
                active_scene=active_scene,
            )
            perf_timings['draw_boxes'] = (time.time() - draw_start) * 1000

            # 步骤9.2：编码为JPEG（质量85，平衡画质与性能）
            # 质量说明：65=偏低画质，85=高画质，95=极高画质（文件更大）
            encode_start = time.time()
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            _, buffer = cv2.imencode('.jpg', annotated_frame, encode_param)
            perf_timings['jpeg_encode'] = (time.time() - encode_start) * 1000

            # 步骤9.3：转换为base64编码（比hex更高效）
            b64_start = time.time()
            import base64
            image_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')
            perf_timings['base64_encode'] = (time.time() - b64_start) * 1000
            perf_timings['frame_size_kb'] = len(image_base64) / 1024

            # 步骤9.4：推送绘制好的帧（通过WebSocket发送图像数据）
            push_start = time.time()
            self._send_result({
                'event_type': 'video_frame',
                'timestamp': timestamp,
                'device_id': device_id,
                'status': 'normal',
                'sequence': int(frame_count),
                'analysis_latency_ms': round(
                    float(state.get("capture_to_analysis_ms", 0))
                    + (time.time() - frame_start_time) * 1000,
                    1,
                ),
                'stream_size': {
                    'width': int(frame.shape[1]),
                    'height': int(frame.shape[0]),
                },
                'active_scene': active_scene,
                'data': {
                    'image': image_base64,  # base64编码的JPEG图像
                    'encoding': 'jpeg',
                },
            })

            # 🔥 关键修复：推送完整的 overlay 数据
            # EventStream.vue 和 HistoryQuery.vue 需要完整的 bbox 数据来显示统计
            # 前端会使用 skipDraw=true 来避免重复绘制
            self._send_result(overlay)

            perf_timings['websocket_send'] = (time.time() - push_start) * 1000

            perf_timings['push_overlay'] = (time.time() - step_start) * 1000
        else:
            perf_timings['push_overlay'] = 0  # 跳过推送

        # ============ 性能监控：输出总耗时 ============
        total_time = (time.time() - frame_start_time) * 1000
        perf_timings['total'] = total_time

        # 限流性能日志，避免控制台 I/O 拖慢实时推理。
        if state["processed_frames"] % self.perf_log_every == 0:
            print(f"\n{'='*80}")
            print(f"🔍 性能监控报告 - 帧 {frame_count} (处理帧 {state['processed_frames']})")
            print(f"{'='*80}")
            print(f"📌 场景: {active_scene}")
            print(f"📌 车辆数: {len(tracked_vehicles)}  车牌数: {len(plate_events)}")
            print(f"\n⏱️  各步骤耗时详情:")
            print(f"  1️⃣  车辆检测 (YOLO):       {perf_timings.get('vehicle_detection', 0):7.2f} ms")
            print(f"  2️⃣  车辆跟踪 (ByteTrack):   {perf_timings.get('vehicle_tracking', 0):7.2f} ms")
            print(f"  3️⃣  车辆掩膜计算:           {perf_timings.get('vehicle_mask', 0):7.2f} ms")
            print(f"  4️⃣  车牌检测 (YOLO):       {perf_timings.get('plate_detection', 0):7.2f} ms")
            if perf_timings.get('plate_recognition', 0) > 0:
                print(f"  5️⃣  车牌识别 (LPRNet):     {perf_timings.get('plate_recognition', 0):7.2f} ms  (单个: {perf_timings.get('plate_recognition_per_plate', 0):.2f} ms)")
            else:
                print(f"  5️⃣  车牌识别 (跳过本帧)")
            print(f"  6️⃣  热力图计算:             {perf_timings.get('traffic_density', 0):7.2f} ms")
            print(f"  7️⃣  违停监控:               {perf_timings.get('illegal_parking', 0):7.2f} ms")
            print(f"  8️⃣  道路异常检测:           {perf_timings.get('road_anomaly', 0):7.2f} ms")
            print(f"  9️⃣  构建overlay:            {perf_timings.get('build_overlay', 0):7.2f} ms")
            print(f"  🔟 推送overlay:            {perf_timings.get('push_overlay', 0):7.2f} ms")
            if perf_timings.get('push_overlay', 0) > 0:
                print(f"      ├─ 绘制检测框:         {perf_timings.get('draw_boxes', 0):7.2f} ms")
                print(f"      ├─ JPEG编码:           {perf_timings.get('jpeg_encode', 0):7.2f} ms")
                print(f"      ├─ Base64编码:         {perf_timings.get('base64_encode', 0):7.2f} ms")
                print(f"      ├─ WebSocket推送:      {perf_timings.get('websocket_send', 0):7.2f} ms")
                print(f"      └─ 帧大小:             {perf_timings.get('frame_size_kb', 0):7.2f} KB")
            print(f"\n  {'🎯 总耗时:':<25} {total_time:7.2f} ms")
            print(f"{'='*80}\n")
        elif state["processed_frames"] % self.frame_log_every == 0:
            print(
                f"帧 {frame_count}: video_overlay vehicles={len(overlay['data']['vehicles'])} "
                f"plates={len(overlay['data']['plates'])} illegal={len(overlay['data']['illegal_parking'])} "
                f"anomalies={len(overlay['data']['road_anomalies'])} "
                f"no_parking_zones={len(overlay['data']['no_parking_zones'])} | "
                f"总耗时: {total_time:.2f}ms"
            )

    def _build_traffic_density_event(self, device_id, state, tracked_vehicles, timestamp):
        """
        构建基于车道的交通流量热力图事件

        新方案：
        1. 检测画面中的车道分隔线（白色标线）
        2. 根据车道线将画面划分为多个车道
        3. 统计每个车道的车辆数量
        4. 拥堵等级：1辆=绿色，2-3辆=橙色，>3辆=红色
        """
        emit_every = max(1, int(state.get("density_emit_every_processed_frames", 3)))
        if state["processed_frames"] % emit_every != 0:
            return None

        # 获取视频分辨率
        frame_shape = state.get("frame_shape")
        if frame_shape is None:
            return None

        height, width = frame_shape[:2]

        # 获取当前帧（用于车道线检测）
        current_frame = state.get("current_frame")
        if current_frame is None or not hasattr(self, 'lane_detector') or self.lane_detector is None:
            # 降级方案：车道检测器未初始化或当前帧为空，使用整个画面作为单一区域
            # 统计所有车辆
            total_count = len(tracked_vehicles)

            # 如果没有车辆，返回空热力图
            if total_count == 0:
                return {
                    "event_type": "traffic_density",
                    "timestamp": timestamp,
                    "device_id": device_id,
                    "status": "normal",
                    "data": {
                        "regions": [],
                        "lane_lines": [],
                    },
                }

            # 判断整体拥堵等级
            if total_count <= 2:
                status = "smooth"
                color = "green"
            elif 3 <= total_count <= 5:
                status = "slow"
                color = "orange"
            else:  # total_count > 5
                status = "congested"
                color = "red"

            # 整个画面作为一个区域
            polygon = [
                [0, 0],          # 左上角
                [width, 0],      # 右上角
                [width, height], # 右下角
                [0, height]      # 左下角
            ]

            return {
                "event_type": "traffic_density",
                "timestamp": timestamp,
                "device_id": device_id,
                "status": "normal",
                "data": {
                    "regions": [{
                        "region_id": "lane_0",
                        "name": "整体通畅",
                        "vehicle_count": total_count,
                        "status": status,
                        "color": color,
                        "polygon": polygon,
                    }],
                    "lane_lines": [],  # 无车道线
                },
            }

        # ============ 步骤1：检测车道分隔线 ============
        lane_lines = self.lane_detector.detect_lane_lines(current_frame)

        # ============ 步骤2：划分车道区域 ============
        lanes = self.lane_detector.divide_lanes(width, lane_lines)

        # ============ 步骤3：统计每个车道的车辆数量 ============
        lane_counts = {lane_id: 0 for lane_id, _, _ in lanes}

        invalid_bbox_count = 0
        for tracked in tracked_vehicles:
            bbox = tracked.get("bbox")
            if not bbox or len(bbox) != 4:
                invalid_bbox_count += 1
                continue

            # 验证bbox格式：[x1, y1, x2, y2]，确保x2>x1且y2>y1
            x1, y1, x2, y2 = bbox
            if x2 <= x1 or y2 <= y1:
                invalid_bbox_count += 1
                continue

            # 验证bbox坐标在视频分辨率范围内
            if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
                # 边界外的车辆（可能是跟踪器预测位置），跳过统计
                continue

            # 计算车辆底部中心点
            anchor = self._bottom_center(bbox)
            vehicle_x, vehicle_y = anchor

            # 判断车辆属于哪个车道
            lane_id = self.lane_detector.assign_vehicle_to_lane(vehicle_x, lanes)
            lane_counts[lane_id] = lane_counts.get(lane_id, 0) + 1

        if invalid_bbox_count > 0:
            print(f"⚠️  跳过 {invalid_bbox_count} 个无效bbox（格式错误或坐标异常）")

        # ============ 步骤4：构建车道热力图数据 ============
        regions = []

        for lane_id, x_start, x_end in lanes:
            count = lane_counts.get(lane_id, 0)

            # 修复：显示所有车道，包括空车道（改善用户体验，让用户看到完整的车道划分）
            # 判断拥堵等级
            if count == 0:
                # 空车道也显示，使用透明的绿色或不显示（取决于前端实现）
                status = "smooth"
                color = "green"
            elif count == 1:
                status = "smooth"
                color = "green"
            elif 2 <= count <= 3:
                status = "slow"
                color = "orange"  # 橙色
            else:  # count > 3
                status = "congested"
                color = "red"

            # 车道区域多边形（覆盖整个画面高度）
            polygon = [
                [int(x_start), 0],          # 左上角
                [int(x_end), 0],            # 右上角
                [int(x_end), int(height)],  # 右下角
                [int(x_start), int(height)] # 左下角
            ]

            regions.append({
                "region_id": f"lane_{lane_id}",
                "name": f"车道{lane_id}",
                "vehicle_count": count,
                "status": status,
                "color": color,
                "polygon": polygon,
            })

        # ============ 步骤5：构建车道分隔线数据（供前端绘制竖线） ============
        lane_line_data = []
        for x in lane_lines:
            lane_line_data.append({
                "x": int(x),
                "y_start": 0,
                "y_end": int(height),
            })

        if state["processed_frames"] % self.frame_log_every == 0:
            if len(lane_lines) == 0:
                summary = f"未检测到车道线，使用单一区域（共{sum(lane_counts.values())}辆车）"
            else:
                summary = (
                    f"检测到{len(lanes)}个车道，{len(lane_lines)}条分隔线，"
                    f"共{sum(lane_counts.values())}辆车 - 车道分布: {dict(lane_counts)}"
                )
            print(f"🚦 traffic_density (车道模式): {summary}")

        return {
            "event_type": "traffic_density",
            "timestamp": timestamp,
            "device_id": device_id,
            "status": "normal",
            "data": {
                "regions": regions,
                "lane_lines": lane_line_data,  # 新增：车道分隔线数据
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

    def _anomaly_backend_status(self):
        payload = {"backend": self.anomaly_backend}
        if not self.anomaly_processor:
            return payload
        detector = self.anomaly_processor.detector
        for field in (
            "heat_threshold",
            "pixel_threshold",
            "last_heat_score",
            "last_foreground_ratio",
            "needs_recalibration",
            "last_background_vehicle_ratio",
            "last_background_valid_ratio",
            "last_background_skip_reason",
        ):
            if hasattr(detector, field):
                value = getattr(detector, field)
                payload[field] = round(value, 5) if isinstance(value, float) else value
        return payload

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
                **self._anomaly_backend_status(),
            }

        # 单设备演示未显式传 device_id 时，优先返回真实运行状态，避免
        # 前端刷新后使用 runtime_defaults 中的旧场景。
        if self.runtime_state:
            first_device_id, state = next(iter(self.runtime_state.items()))
            return {
                "status": "success",
                "device_id": first_device_id,
                "mode": state.get("anomaly_mode", "detecting"),
                "background_frames": state.get("anomaly_background_frames", 0),
                "skipped_frames": state.get("anomaly_background_skipped_frames", 0),
                "min_background_frames": int(self.runtime_defaults.get("anomaly_min_background_frames", 8)),
                "active_scene": state.get("active_scene"),
                "enabled": self.anomaly_processor is not None,
                **self._anomaly_backend_status(),
            }

        # 使用anomaly_processor内部的真实计数器，确保准确性
        actual_background_frames = self.anomaly_processor.background_frames if self.anomaly_processor else 0

        return {
            "status": "success",
            "device_id": device_id,
            "mode": self.runtime_defaults.get("anomaly_mode", "detecting"),
            "background_frames": actual_background_frames,
            "skipped_frames": sum(
                state.get("anomaly_background_skipped_frames", 0) for state in self.runtime_state.values()
            ),
            "min_background_frames": int(self.runtime_defaults.get("anomaly_min_background_frames", 8)),
            "active_scene": self.runtime_defaults.get("active_scene"),
            "enabled": self.anomaly_processor is not None,
            **self._anomaly_backend_status(),
        }

    def _target_states(self, device_id=None):
        if device_id:
            return [self._get_or_create_runtime_state(device_id)]
        return list(self.runtime_state.values())

    def _draw_overlay_on_frame(self, frame, overlay, active_scene):
        """
        在视频帧上直接绘制检测框和标签

        Args:
            frame: 原始帧（BGR格式）
            overlay: overlay数据结构
            active_scene: 当前场景

        Returns:
            绘制后的帧
        """
        # 定义颜色（BGR格式）
        COLOR_VEHICLE = (0, 255, 0)      # 绿色 - 车辆
        COLOR_PLATE = (255, 255, 0)      # 青色 - 车牌
        COLOR_ILLEGAL = (0, 0, 255)      # 红色 - 违停
        COLOR_PARKING = (0, 165, 255)    # 橙色 - 监控中
        COLOR_ZONE = (0, 255, 255)       # 黄色 - 禁停区
        COLOR_ANOMALY = (255, 0, 255)    # 紫色 - 道路异常
        COLOR_REGION_GREEN = (0, 255, 0)    # 绿色 - 通畅
        COLOR_REGION_ORANGE = (0, 165, 255) # 橙色 - 缓慢
        COLOR_REGION_RED = (0, 0, 255)      # 红色 - 拥堵

        # 1. 绘制交通密度区域（半透明多边形）- 已禁用，只使用 AI 车道识别
        # 注释掉固定的红色A/B/C/D区域框，避免与 AI 车道识别冲突
        # if active_scene == 'traffic_density':
        #     overlay_img = frame.copy()
        #     for region in overlay['data'].get('traffic_regions', []):
        #         ... (已禁用绘制固定区域)
        pass  # 不绘制固定区域

        # 2. 绘制禁停区（半透明多边形）
        if active_scene == 'illegal_parking':
            overlay_img = frame.copy()
            for zone in overlay['data'].get('no_parking_zones', []):
                polygon = zone.get('polygon', [])
                if len(polygon) < 3:
                    continue

                pts = np.array(polygon, dtype=np.int32)
                cv2.fillPoly(overlay_img, [pts], COLOR_ZONE)
                cv2.polylines(frame, [pts], True, COLOR_ZONE, 2)

                # 添加标签
                label = zone.get('label', '禁停区')
                if label:
                    M = cv2.moments(pts)
                    if M['m00'] != 0:
                        cx = int(M['m10'] / M['m00'])
                        cy = int(M['m01'] / M['m00'])
                        (text_width, text_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                        )
                        cv2.rectangle(
                            frame,
                            (cx - 5, cy - text_height - 5),
                            (cx + text_width + 5, cy + 5),
                            (0, 0, 0),
                            -1
                        )
                        cv2.putText(
                            frame, label, (cx, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
                        )

            cv2.addWeighted(overlay_img, 0.2, frame, 0.8, 0, frame)

        # 3. 绘制车辆检测框
        for vehicle in overlay['data'].get('vehicles', []):
            bbox = vehicle.get('bbox', [])
            if len(bbox) != 4:
                continue

            x1, y1, x2, y2 = bbox
            label = vehicle.get('label', 'vehicle')

            # 绘制矩形框
            cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_VEHICLE, 2)

            # 绘制标签背景
            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                frame,
                (x1, y1 - text_height - 8),
                (x1 + text_width + 6, y1),
                COLOR_VEHICLE,
                -1
            )

            # 绘制文本
            cv2.putText(
                frame, label, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
            )

        # 4. 绘制车牌检测框
        for plate in overlay['data'].get('plates', []):
            bbox = plate.get('bbox', [])
            if len(bbox) != 4:
                continue

            x1, y1, x2, y2 = bbox
            label = plate.get('label', 'plate')

            cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_PLATE, 2)

            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            cv2.rectangle(
                frame,
                (x1, y1 - text_height - 8),
                (x1 + text_width + 6, y1),
                COLOR_PLATE,
                -1
            )
            cv2.putText(
                frame, label, (x1 + 3, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
            )

        # 5. 绘制违停状态
        if active_scene == 'illegal_parking':
            # 绘制违停告警（红色）
            for illegal in overlay['data'].get('illegal_parking', []):
                bbox = illegal.get('bbox', [])
                if len(bbox) != 4:
                    continue

                x1, y1, x2, y2 = bbox
                label = illegal.get('label', 'illegal')

                cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_ILLEGAL, 3)

                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                )
                cv2.rectangle(
                    frame,
                    (x1, y1 - text_height - 10),
                    (x1 + text_width + 8, y1),
                    COLOR_ILLEGAL,
                    -1
                )
                cv2.putText(
                    frame, label, (x1 + 4, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
                )

            # 绘制停车监控状态（橙色）
            for status in overlay['data'].get('parking_statuses', []):
                if status.get('has_warned'):
                    continue  # 已告警的不重复绘制

                bbox = status.get('bbox', [])
                if len(bbox) != 4:
                    continue

                x1, y1, x2, y2 = bbox
                label = status.get('label', 'parking')

                cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_PARKING, 2)

                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                cv2.rectangle(
                    frame,
                    (x1, y1 - text_height - 8),
                    (x1 + text_width + 6, y1),
                    COLOR_PARKING,
                    -1
                )
                cv2.putText(
                    frame, label, (x1 + 3, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
                )

        # 6. 绘制道路异常
        if active_scene == 'road_anomaly':
            for anomaly in overlay['data'].get('road_anomalies', []):
                bbox = anomaly.get('bbox', [])
                if len(bbox) != 4:
                    continue

                x1, y1, x2, y2 = bbox
                label = anomaly.get('label', 'anomaly')

                cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_ANOMALY, 2)

                (text_width, text_height), baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                cv2.rectangle(
                    frame,
                    (x1, y1 - text_height - 8),
                    (x1 + text_width + 6, y1),
                    COLOR_ANOMALY,
                    -1
                )
                cv2.putText(
                    frame, label, (x1 + 3, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
                )

        return frame

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
    @staticmethod
    def _bottom_center(bbox):
        """
        计算bbox底部中心点坐标（用于网格统计）

        Args:
            bbox: [x1, y1, x2, y2] 格式的边界框

        Returns:
            (center_x, bottom_y) 整数坐标元组
        """
        if not bbox or len(bbox) != 4:
            raise ValueError(f"Invalid bbox format: {bbox}, expected [x1, y1, x2, y2]")

        x1, y1, x2, y2 = bbox

        # 验证坐标顺序（x2应大于x1，y2应大于y1）
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid bbox coordinates: x2({x2}) <= x1({x1}) or y2({y2}) <= y1({y1})")

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

    def _build_video_overlay(
        self,
        device_id,
        timestamp,
        frame,
        state,
        active_scene,
        tracked_vehicles,
        parking_events,
        parking_statuses,
        anomaly_events,
        plate_events,
    ):
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
                'parking_statuses': [],
                'anomaly_road_roi': [],
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

        if active_scene == 'illegal_parking':
            for status in parking_statuses:
                stay_time = float(status.get('stay_time', 0))
                threshold = float(status.get('threshold', 0))
                is_stationary = bool(status.get('is_stationary'))
                has_warned = bool(status.get('has_warned'))
                if has_warned:
                    label = f"illegal {stay_time:.1f}s"
                elif is_stationary:
                    label = f"parking {stay_time:.1f}/{threshold:.1f}s"
                else:
                    label = "vehicle moving"
                overlay['data']['parking_statuses'].append({
                    **status,
                    'bbox': [int(v) for v in status.get('bbox', [])],
                    'label': label,
                })

        if active_scene == 'illegal_parking':
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

        if active_scene == 'road_anomaly':
            polygon = state.get('anomaly_road_roi', [])
            if len(polygon) >= 3:
                overlay['data']['anomaly_road_roi'].append({
                    'polygon': [[int(x), int(y)] for x, y in polygon],
                    'label': '异物检测区',
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

    def _save_road_mask_debug(self, road_mask, frame_count):
        try:
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
        return [
            device_id
            for device_id, thread in self.active_streams.items()
            if thread.is_alive()
        ]


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
