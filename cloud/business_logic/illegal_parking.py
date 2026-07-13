"""
违停跟踪与告警业务逻辑
基于车辆跟踪结果、禁停区域和停留时间规则生成 illegal_parking 事件。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import math


Point = Tuple[int, int]
BBox = List[int]


@dataclass
class TrackParkingState:
    track_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_bbox: BBox
    anchor_history: List[Point] = field(default_factory=list)
    current_zone_id: Optional[str] = None
    current_zone_name: Optional[str] = None
    current_threshold: float = 0.0
    zone_entered_at: Optional[datetime] = None
    has_warned: bool = False
    last_warned_at: Optional[datetime] = None
    missed_frames: int = 0


class IllegalParkingMonitor:
    """根据 ByteTrack 轨迹结果判断违停。"""

    def __init__(
        self,
        zones: Optional[List[dict]] = None,
        stationary_pixel_threshold: float = 18,
        release_grace_frames: int = 3,
        min_history: int = 3,
        alert_dedupe_seconds: float = 12,
        alert_dedupe_iou: float = 0.5,
        alert_dedupe_center_distance: float = 80,
        handoff_max_seconds: float = 3,
        handoff_iou: float = 0.15,
        handoff_center_distance: float = 120,
    ):
        self.zones = zones or []
        self.stationary_pixel_threshold = stationary_pixel_threshold
        self.release_grace_frames = release_grace_frames
        self.min_history = min_history
        self.alert_dedupe_seconds = alert_dedupe_seconds
        self.alert_dedupe_iou = alert_dedupe_iou
        self.alert_dedupe_center_distance = alert_dedupe_center_distance
        self.handoff_max_seconds = handoff_max_seconds
        self.handoff_iou = handoff_iou
        self.handoff_center_distance = handoff_center_distance
        self.track_states: Dict[int, TrackParkingState] = {}
        self.recent_alerts: List[dict] = []

    def update(self, device_id: str, tracked_vehicles: List[dict], timestamp_iso: str) -> List[dict]:
        now = self._parse_iso_time(timestamp_iso)
        seen_track_ids = set()
        events = []

        # 调试信息：首次调用时（无论有无车辆）记录禁停区配置
        if not hasattr(self, '_debug_logged'):
            if len(self.zones) == 0:
                print(f"❌ 违停监控错误: 未配置禁停区！zones={self.zones}")
            else:
                print(f"✅ 违停监控初始化: 配置了 {len(self.zones)} 个禁停区")
                for zone in self.zones:
                    zone_name = zone.get('name', zone.get('zone_id'))
                    polygon = zone.get('polygon', [])
                    threshold = zone.get('threshold_seconds', 30)
                    print(f"   - {zone_name}: 阈值={threshold}秒, polygon={len(polygon)}个顶点")
                    if polygon and len(polygon) > 0:
                        # 显示多边形范围
                        xs = [p[0] for p in polygon]
                        ys = [p[1] for p in polygon]
                        print(f"     范围: X[{min(xs):.0f}-{max(xs):.0f}] Y[{min(ys):.0f}-{max(ys):.0f}]")
                print(f"   - 静止阈值: {self.stationary_pixel_threshold} 像素")
                print(f"   - 最小历史: {self.min_history} 帧")
            self._debug_logged = True

        # 无条件输出：每次调用都记录（便于诊断）
        if not hasattr(self, '_update_call_count'):
            self._update_call_count = 0
        self._update_call_count += 1
        if self._update_call_count % 30 == 0:
            print(f"🚨 illegal_parking.update() 第{self._update_call_count}次调用, 收到 {len(tracked_vehicles)} 辆跟踪车辆, 配置了 {len(self.zones)} 个禁停区")

        for tracked in tracked_vehicles:
            track_id = tracked['track_id']
            bbox = [int(v) for v in tracked['bbox']]
            anchor = self._bottom_center(bbox)
            seen_track_ids.add(track_id)

            state = self.track_states.get(track_id)
            is_new_track = state is None
            if is_new_track:
                state = TrackParkingState(
                    track_id=track_id,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_bbox=bbox,
                )
                self.track_states[track_id] = state

            state.last_seen_at = now
            state.last_bbox = bbox
            state.missed_frames = 0
            state.anchor_history.append(anchor)
            if len(state.anchor_history) > 10:
                state.anchor_history = state.anchor_history[-10:]

            zone = self._find_zone(anchor)

            # 调试：如果有车辆但找不到禁停区，输出位置信息（每30帧输出一次）
            if zone is None and not hasattr(self, '_no_zone_logged_count'):
                self._no_zone_logged_count = 0
            if zone is None:
                self._no_zone_logged_count += 1
                if self._no_zone_logged_count == 1 or self._no_zone_logged_count % 30 == 0:
                    print(f"🚨 track_id={track_id} 不在任何禁停区内, 位置={anchor}, bbox={bbox}")
                self._handle_zone_exit(state)
                continue

            # 重置计数器
            if hasattr(self, '_no_zone_logged_count'):
                self._no_zone_logged_count = 0

            zone_id = zone['zone_id']
            zone_name = zone.get('name', zone_id)
            threshold = float(zone.get('threshold_seconds', 30))

            # 调试信息：车辆进入禁停区
            if state.current_zone_id != zone_id:
                print(f"🚨 track_id={track_id} 进入禁停区 [{zone_name}], 阈值={threshold}秒, 位置={anchor}")

            if state.current_zone_id != zone_id:
                inherited = is_new_track and self._inherit_active_track_state(
                    state, zone_id, zone_name, threshold, bbox, now
                )
                if not inherited:
                    state.current_zone_id = zone_id
                    state.current_zone_name = zone_name
                    state.current_threshold = threshold
                    state.zone_entered_at = now
                    state.has_warned = False
                    state.last_warned_at = None

            self._inherit_recent_alert_state(state, zone_id, bbox, now)

            stay_time = (now - state.zone_entered_at).total_seconds() if state.zone_entered_at else 0
            is_stationary = self._is_stationary(state)

            # 调试信息：监控停留状态（每秒输出一次）
            if stay_time > 0 and len(state.anchor_history) >= self.min_history:
                history = state.anchor_history
                xs = [p[0] for p in history]
                ys = [p[1] for p in history]
                span_x = max(xs) - min(xs)
                span_y = max(ys) - min(ys)
                displacement = (span_x ** 2 + span_y ** 2) ** 0.5

                # 使用整数部分判断，每秒输出一次
                if int(stay_time) != int(stay_time - 0.1):  # 秒数变化时输出
                    status_icon = "✅" if is_stationary else "❌"
                    print(f"🚨 {status_icon} track_id={track_id} 在 [{zone_name}]: "
                          f"停留 {stay_time:.1f}s / {threshold}s, "
                          f"静止={is_stationary} (位移={displacement:.1f}px, 阈值≤{self.stationary_pixel_threshold}px), "
                          f"历史={len(history)}帧")

            if stay_time >= threshold and is_stationary:
                if not state.has_warned:
                    state.has_warned = True
                    state.last_warned_at = now
                    candidate_event = {
                        'event_type': 'illegal_parking',
                        'timestamp': timestamp_iso,
                        'device_id': device_id,
                        'bbox': bbox,
                        'status': 'warning',
                        'track_id': track_id,
                        'data': {
                            'track_id': track_id,
                            'stay_time': round(stay_time, 1),
                            'threshold': threshold,
                            'zone_id': zone_id,
                            'zone_name': zone_name,
                            'is_stationary': True,
                            'vehicle_type': tracked.get('class_name', 'vehicle'),
                            'confidence': tracked.get('confidence', 0),
                        },
                    }
                    if not self._is_duplicate_alert(candidate_event, now):
                        self.recent_alerts.append({
                            'timestamp': now,
                            'zone_id': zone_id,
                            'bbox': bbox,
                            'track_id': track_id,
                        })
                        self._prune_recent_alerts(now)
                        events.append(candidate_event)
                        print(f"🚨🚨🚨 违停告警触发！track_id={track_id}, 停留{stay_time:.1f}秒 ≥ {threshold}秒")

        self._age_unseen_tracks(seen_track_ids)
        return events

    def get_active_statuses(self, timestamp_iso: Optional[str] = None) -> List[dict]:
        """Return current in-zone progress so the UI can explain why an alert has or has not fired."""
        now = self._parse_iso_time(timestamp_iso) if timestamp_iso else datetime.now()
        statuses = []
        for state in self.track_states.values():
            if (
                state.current_zone_id is None
                or state.zone_entered_at is None
                or state.missed_frames > 0
            ):
                continue

            stay_time = max(0.0, (now - state.zone_entered_at).total_seconds())
            statuses.append({
                'track_id': state.track_id,
                'bbox': [int(v) for v in state.last_bbox],
                'stay_time': round(stay_time, 1),
                'threshold': float(state.current_threshold),
                'zone_id': state.current_zone_id,
                'zone_name': state.current_zone_name,
                'is_stationary': self._is_stationary(state),
                'has_warned': state.has_warned,
                'status': 'warning' if state.has_warned else 'monitoring',
            })
        return statuses

    def _age_unseen_tracks(self, seen_track_ids: set):
        stale_track_ids = []
        for track_id, state in self.track_states.items():
            if track_id in seen_track_ids:
                continue
            state.missed_frames += 1
            if state.missed_frames > self.release_grace_frames:
                stale_track_ids.append(track_id)
        for track_id in stale_track_ids:
            self.track_states.pop(track_id, None)

    def _handle_zone_exit(self, state: TrackParkingState):
        state.current_zone_id = None
        state.current_zone_name = None
        state.zone_entered_at = None
        state.has_warned = False
        state.last_warned_at = None

    def _find_zone(self, point: Point) -> Optional[dict]:
        for zone in self.zones:
            polygon = zone.get('polygon') or []
            if self._point_in_polygon(point, polygon):
                return zone
        return None

    def _is_stationary(self, state: TrackParkingState) -> bool:
        history = state.anchor_history
        if len(history) < self.min_history:
            return False
        xs = [p[0] for p in history]
        ys = [p[1] for p in history]
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)
        displacement = math.hypot(span_x, span_y)
        return displacement <= self.stationary_pixel_threshold

    @staticmethod
    def _bottom_center(bbox: BBox) -> Point:
        x1, y1, x2, y2 = bbox
        return int((x1 + x2) / 2), int(y2)

    @staticmethod
    def _point_in_polygon(point: Point, polygon: List[List[int]]) -> bool:
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

    def _prune_recent_alerts(self, now: datetime):
        self.recent_alerts = [
            item for item in self.recent_alerts
            if (now - item['timestamp']).total_seconds() <= self.alert_dedupe_seconds
        ]

    def _inherit_recent_alert_state(self, state: TrackParkingState, zone_id: str, bbox: BBox, now: datetime):
        """如果刚生成了新的 track_id，但其实还是同一辆车，则继承已告警状态。"""
        self._prune_recent_alerts(now)
        center = self._bottom_center(bbox)
        for item in self.recent_alerts:
            if item['zone_id'] != zone_id:
                continue
            existing_center = self._bottom_center(item['bbox'])
            if (
                self._bbox_iou(bbox, item['bbox']) >= self.alert_dedupe_iou
                or self._center_distance(center, existing_center) <= self.alert_dedupe_center_distance
            ):
                state.has_warned = True
                state.last_warned_at = item['timestamp']
                if state.zone_entered_at is None or state.zone_entered_at > item['timestamp']:
                    state.zone_entered_at = item['timestamp']
                return

    def _inherit_active_track_state(
        self,
        state: TrackParkingState,
        zone_id: str,
        zone_name: str,
        threshold: float,
        bbox: BBox,
        now: datetime,
    ) -> bool:
        """Carry the parking timer across a short tracker-ID change before an alert is emitted."""
        center = self._bottom_center(bbox)
        best_match = None
        best_score = -1.0

        for other_track_id, other in self.track_states.items():
            if other_track_id == state.track_id or other.current_zone_id != zone_id:
                continue

            unseen_seconds = (now - other.last_seen_at).total_seconds()
            if unseen_seconds <= 0 or unseen_seconds > self.handoff_max_seconds:
                continue

            iou = self._bbox_iou(bbox, other.last_bbox)
            distance = self._center_distance(center, self._bottom_center(other.last_bbox))
            if iou < self.handoff_iou and distance > self.handoff_center_distance:
                continue

            score = iou + max(0.0, 1.0 - distance / max(1.0, self.handoff_center_distance))
            if score > best_score:
                best_score = score
                best_match = other

        if best_match is None:
            return False

        state.first_seen_at = min(state.first_seen_at, best_match.first_seen_at)
        state.current_zone_id = zone_id
        state.current_zone_name = zone_name
        state.current_threshold = threshold
        state.zone_entered_at = best_match.zone_entered_at or now
        state.has_warned = best_match.has_warned
        state.last_warned_at = best_match.last_warned_at
        state.anchor_history = (best_match.anchor_history + state.anchor_history)[-10:]
        self.track_states.pop(best_match.track_id, None)
        return True

    def _is_duplicate_alert(self, event: dict, now: datetime) -> bool:
        self._prune_recent_alerts(now)
        zone_id = event['data'].get('zone_id')
        bbox = event['bbox']
        center = self._bottom_center(bbox)

        for item in self.recent_alerts:
            if item['zone_id'] != zone_id:
                continue
            existing_center = self._bottom_center(item['bbox'])
            if self._bbox_iou(bbox, item['bbox']) >= self.alert_dedupe_iou:
                return True
            if self._center_distance(center, existing_center) <= self.alert_dedupe_center_distance:
                return True
        return False

    @staticmethod
    def _bbox_iou(bbox1: BBox, bbox2: BBox) -> float:
        x1_min, y1_min, x1_max, y1_max = bbox1
        x2_min, y2_min, x2_max, y2_max = bbox2

        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)

        if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
            return 0.0

        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
        area1 = (x1_max - x1_min) * (y1_max - y1_min)
        area2 = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = area1 + area2 - inter_area
        return inter_area / union_area if union_area > 0 else 0.0

    @staticmethod
    def _center_distance(p1: Point, p2: Point) -> float:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    @staticmethod
    def _parse_iso_time(timestamp_iso: str) -> datetime:
        try:
            return datetime.fromisoformat(timestamp_iso)
        except ValueError:
            # 兼容以 Z 结尾的时间戳
            return datetime.fromisoformat(timestamp_iso.replace('Z', '+00:00'))
