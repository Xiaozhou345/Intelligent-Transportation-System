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
BUSINESS_LOGIC_DIR = os.path.join(os.path.dirname(CURRENT_DIR), "business_logic")
REPO_ROOT = Path(CURRENT_DIR).parents[1]
if AI_MODELS_DIR not in sys.path:
    sys.path.append(AI_MODELS_DIR)
if VEHICLE_DETECTION_DIR not in sys.path:
    sys.path.append(VEHICLE_DETECTION_DIR)
if VEHICLE_TRACKING_DIR not in sys.path:
    sys.path.append(VEHICLE_TRACKING_DIR)
if BUSINESS_LOGIC_DIR not in sys.path:
    sys.path.append(BUSINESS_LOGIC_DIR)

from detector import VehicleDetector
from vehicle_tracker import VehicleTracker
from illegal_parking import IllegalParkingMonitor


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
        self.vehicle_conf = float(os.getenv("ITS_VEHICLE_CONF", "0.45"))

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
        }
        if not config_path.exists():
            print("⚠️  未找到 illegal_parking_config.json，将使用内置默认配置")
            return defaults

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            file_defaults = data.get("default", {})
            defaults.update(file_defaults)
            print(f"✅ 已加载违停/热力图配置: {config_path}")
        except Exception as exc:
            print(f"⚠️  违停配置加载失败，将使用内置默认配置: {exc}")
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
        except Exception as e:
            print(f"⚠️  车辆检测初始化失败，道路异常检测将继续运行: {str(e)}")
            self.vehicle_detector = None

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
                "traffic_thresholds": dict(self.runtime_defaults.get("traffic_thresholds", {"smooth_max": 2, "slow_max": 5})),
                "density_emit_every_processed_frames": int(self.runtime_defaults.get("density_emit_every_processed_frames", 3)),
                "processed_frames": 0,
                "active_scene": self._resolve_scene_for_device(device_id),
            }
            self.runtime_state[device_id] = state

        if frame_shape is not None and state["frame_shape"] != frame_shape:
            state["frame_shape"] = frame_shape
            state["traffic_regions"] = self._scale_regions(self.runtime_defaults.get("traffic_regions", []), frame_shape)
            state["no_parking_zones"] = self._scale_regions(self.runtime_defaults.get("no_parking_zones", []), frame_shape)
            state["parking_monitor"].zones = state["no_parking_zones"]
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

        print(f"停止处理设备 {device_id} 的视频流")
        return True

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
            if self.enable_mock_fallback and frame_count % 10 == 0:
                event_type = self._get_event_type(frame_count)
                result = self._generate_mock_result(device_id, timestamp, event_type)
                self._send_result(result)
            return

        vehicles = self.vehicle_detector.detect(frame)
        tracked_vehicles = state["tracker"].update(vehicles)
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

        if self.emit_vehicle_events or active_scene == 'vehicle_detection':
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

        traffic_event = self._build_traffic_density_event(device_id, state, tracked_vehicles, timestamp)
        if traffic_event is not None and active_scene == 'traffic_density':
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
            tracked_vehicles=tracked_vehicles,
            parking_events=parking_events,
            anomaly_events=anomaly_events,
            plate_events=[],
        )
        self._send_result(overlay)

    def _build_traffic_density_event(self, device_id, state, tracked_vehicles, timestamp):
        emit_every = max(1, int(state.get("density_emit_every_processed_frames", 3)))
        if state["processed_frames"] % emit_every != 0:
            return None

        thresholds = state.get("traffic_thresholds", {"smooth_max": 2, "slow_max": 5})
        smooth_max = thresholds.get("smooth_max", 2)
        slow_max = thresholds.get("slow_max", 5)

        regions = []
        for region in state.get("traffic_regions", []):
            count = 0
            for tracked in tracked_vehicles:
                anchor = self._bottom_center(tracked["bbox"])
                if self._point_in_polygon(anchor, region.get("polygon", [])):
                    count += 1

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
                "region_id": region.get("region_id", "road"),
                "vehicle_count": count,
                "status": status,
                "color": color,
            })

        if not regions:
            return None

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

    def _build_video_overlay(self, device_id, timestamp, frame, tracked_vehicles, parking_events, anomaly_events, plate_events):
        overlay = {
            'event_type': 'video_overlay',
            'timestamp': timestamp,
            'device_id': device_id,
            'status': 'normal',
            'stream_size': {
                'width': int(frame.shape[1]),
                'height': int(frame.shape[0]),
            },
            'data': {
                'vehicles': [],
                'plates': [],
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
            overlay['data']['plates'].append({
                'bbox': bbox,
                'label': event.get('data', {}).get('plate_number', 'plate'),
                'confidence': event.get('data', {}).get('confidence', 0),
                'track_id': event.get('data', {}).get('track_id'),
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
            self.socketio.emit('analysis_result', result)
            print(f"推送结果: {result['event_type']}")
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
