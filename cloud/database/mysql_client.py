"""
MySQL 存储访问层
优先从环境变量读取数据库配置；默认尝试本机 127.0.0.1:3306。
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pymysql
from pymysql.cursors import DictCursor


DB_SETTINGS = {
    'host': os.getenv('ITS_DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('ITS_DB_PORT', '3306')),
    'user': os.getenv('ITS_DB_USER', 'root'),
    'password': os.getenv('ITS_DB_PASSWORD', 'mysql2026'),
    'database': os.getenv('ITS_DB_NAME', 'intelligent_transportation_system'),
    'charset': 'utf8mb4',
    'cursorclass': DictCursor,
    'autocommit': True,
}

_db_available_cache: Optional[bool] = None
_db_error_cache: Optional[str] = None


@contextmanager
def get_connection():
    conn = pymysql.connect(**DB_SETTINGS)
    try:
        yield conn
    finally:
        conn.close()


def check_connection(force: bool = False) -> bool:
    global _db_available_cache, _db_error_cache
    if _db_available_cache is not None and not force:
        return _db_available_cache

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        _db_available_cache = True
        _db_error_cache = None
        return True
    except Exception as exc:
        _db_available_cache = False
        _db_error_cache = str(exc)
        return False


def get_last_error() -> Optional[str]:
    return _db_error_cache


def _json_or_none(value: Any):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def load_system_config() -> Dict[str, Any]:
    if not check_connection():
        return {}

    config = {}
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT config_key, config_value FROM system_config')
            for row in cursor.fetchall():
                value = row['config_value']
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                config[row['config_key']] = value
    return config


def upsert_device(device: Any):
    if not check_connection():
        return False

    sql = """
    INSERT INTO edge_device (
        device_id, device_type, stream_url, scene_id, status,
        resolution, fps, codec, bitrate, register_time, last_heartbeat
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        device_type = VALUES(device_type),
        stream_url = VALUES(stream_url),
        scene_id = VALUES(scene_id),
        status = VALUES(status),
        resolution = VALUES(resolution),
        fps = VALUES(fps),
        codec = VALUES(codec),
        bitrate = VALUES(bitrate),
        last_heartbeat = VALUES(last_heartbeat)
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                device.device_id,
                device.device_type,
                device.stream_url,
                device.scene_id,
                device.status,
                device.resolution,
                device.fps,
                device.codec,
                device.bitrate,
                device.register_time,
                device.last_heartbeat,
            ))
    return True


def set_device_status(device_id: str, status: str, last_heartbeat=None):
    if not check_connection():
        return False

    if last_heartbeat is None:
        sql = 'UPDATE edge_device SET status=%s WHERE device_id=%s'
        params = (status, device_id)
    else:
        sql = 'UPDATE edge_device SET status=%s, last_heartbeat=%s WHERE device_id=%s'
        params = (status, last_heartbeat, device_id)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
    return True


def get_whitelist_entry(plate_number: str) -> Optional[Dict[str, Any]]:
    if not check_connection():
        return None

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT * FROM vehicle_whitelist WHERE plate_number=%s LIMIT 1',
                (plate_number,),
            )
            return cursor.fetchone()


def insert_recognition_event(event_type: str, device_id: str, result: Dict[str, Any], scene_id: Optional[str] = None):
    if not check_connection():
        return False

    plate_number = result.get('data', {}).get('plate_number') or result.get('plate_number')
    bbox = result.get('bbox')
    timestamp = result.get('timestamp')

    sql = """
    INSERT INTO recognition_event (
        event_type, device_id, scene_id, plate_number, bbox, result_json, created_at
    ) VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()))
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                event_type,
                device_id,
                scene_id,
                plate_number,
                _json_or_none(bbox),
                _json_or_none(result),
                timestamp,
            ))
    return True


def insert_alarm_record(alarm_type: str, device_id: str, alarm: Dict[str, Any], scene_id: Optional[str] = None):
    if not check_connection():
        return False

    data = alarm.get('data', {})
    target_id = data.get('track_id') or data.get('anomaly_id') or alarm.get('track_id')
    target_type = 'vehicle' if alarm_type == 'illegal_parking' else 'object'
    description = None
    if alarm_type == 'illegal_parking':
        description = f"track_id={target_id} stay_time={data.get('stay_time')} threshold={data.get('threshold')}"
    elif alarm_type == 'road_anomaly':
        description = f"anomaly_type={data.get('anomaly_type')} lane={data.get('affected_lane')}"

    sql = """
    INSERT INTO alarm_record (
        alarm_type, device_id, scene_id, target_type, target_id,
        plate_number, description, bbox, status, detail_json, created_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()))
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                alarm_type,
                device_id,
                scene_id,
                target_type,
                str(target_id) if target_id is not None else None,
                data.get('plate_number'),
                description,
                _json_or_none(alarm.get('bbox')),
                alarm.get('status', 'warning'),
                _json_or_none(alarm),
                alarm.get('timestamp'),
            ))
    return True
