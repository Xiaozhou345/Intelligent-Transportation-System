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
    ):
        self.zones = zones or []
        self.stationary_pixel_threshold = stationary_pixel_threshold
        self.release_grace_frames = release_grace_frames
        self.min_history = min_history
        self.track_states: Dict[int, TrackParkingState] = {}

    def update(self, device_id: str, tracked_vehicles: List[dict], timestamp_iso: str) -> List[dict]:
        now = self._parse_iso_time(timestamp_iso)
        seen_track_ids = set()
        events = []

        for tracked in tracked_vehicles:
            track_id = tracked['track_id']
            bbox = [int(v) for v in tracked['bbox']]
            anchor = self._bottom_center(bbox)
            seen_track_ids.add(track_id)

            state = self.track_states.get(track_id)
            if state is None:
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
            if zone is None:
                self._handle_zone_exit(state)
                continue

            zone_id = zone['zone_id']
            zone_name = zone.get('name', zone_id)
            threshold = float(zone.get('threshold_seconds', 30))
            cooldown = float(zone.get('cooldown_seconds', 10))

            if state.current_zone_id != zone_id:
                state.current_zone_id = zone_id
                state.current_zone_name = zone_name
                state.zone_entered_at = now
                state.has_warned = False
                state.last_warned_at = None

            stay_time = (now - state.zone_entered_at).total_seconds() if state.zone_entered_at else 0
            is_stationary = self._is_stationary(state)

            if stay_time >= threshold and is_stationary:
                should_warn = False
                if not state.has_warned:
                    should_warn = True
                elif state.last_warned_at is not None:
                    elapsed = (now - state.last_warned_at).total_seconds()
                    should_warn = elapsed >= cooldown

                if should_warn:
                    state.has_warned = True
                    state.last_warned_at = now
                    events.append({
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
                    })

        self._age_unseen_tracks(seen_track_ids)
        return events

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

    @staticmethod
    def _parse_iso_time(timestamp_iso: str) -> datetime:
        try:
            return datetime.fromisoformat(timestamp_iso)
        except ValueError:
            # 兼容以 Z 结尾的时间戳
            return datetime.fromisoformat(timestamp_iso.replace('Z', '+00:00'))
