"""
MySQL 存储访问层
优先从 .env.db 文件读取数据库配置；其次从环境变量；最后使用默认值。
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pymysql
from pymysql.cursors import DictCursor


def _load_db_config_from_file():
    """
    从 .env.db 文件加载数据库配置

    Returns:
        dict: 配置字典，如果文件不存在则返回空字典
    """
    # 查找 .env.db 文件位置（项目根目录）
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    env_db_path = os.path.join(project_root, '.env.db')

    config = {}

    if os.path.exists(env_db_path):
        try:
            with open(env_db_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过注释和空行
                    if not line or line.startswith('#'):
                        continue
                    # 解析 KEY=VALUE 格式
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        config[key] = value
            print(f"✅ 从 .env.db 加载数据库配置: {env_db_path}")
        except Exception as e:
            print(f"⚠️  读取 .env.db 失败: {e}")
    else:
        print(f"⚠️  未找到 .env.db 文件: {env_db_path}")
        print(f"   将使用环境变量或默认配置")

    return config


# 加载配置文件
_file_config = _load_db_config_from_file()

# 数据库配置：优先级 环境变量 > .env.db 文件 > 默认值
DB_SETTINGS = {
    'host': os.getenv('ITS_DB_HOST') or _file_config.get('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('ITS_DB_PORT') or _file_config.get('DB_PORT', '3306')),
    'user': os.getenv('ITS_DB_USER') or _file_config.get('DB_USER', 'root'),
    'password': os.getenv('ITS_DB_PASSWORD') or _file_config.get('DB_PASSWORD', ''),
    'database': os.getenv('ITS_DB_NAME') or _file_config.get('DB_NAME', 'intelligent_transportation_system'),
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


def _normalize_plate_number(plate_number: str) -> str:
    return str(plate_number or '').strip().replace('-', '').replace(' ', '').upper()


def get_whitelist_entry(plate_number: str) -> Optional[Dict[str, Any]]:
    if not check_connection():
        return None

    normalized_plate = _normalize_plate_number(plate_number)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT * FROM vehicle_whitelist WHERE plate_number=%s LIMIT 1',
                (normalized_plate,),
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


def build_alarm_key(alarm_type: str, alarm: Dict[str, Any]) -> str:
    data = alarm.get('data', {}) or {}
    timestamp = alarm.get('timestamp') or data.get('timestamp') or ''
    if alarm_type == 'illegal_parking':
        return f"{alarm_type}-{timestamp}-{data.get('track_id') or alarm.get('track_id') or ''}"
    if alarm_type == 'road_anomaly':
        return f"{alarm_type}-{timestamp}-{data.get('anomaly_type') or ''}-{data.get('affected_lane') or ''}"
    return f"{alarm_type}-{timestamp}-{json.dumps(alarm.get('bbox') or [], ensure_ascii=False)}"


def ensure_alarm_disposition_schema() -> bool:
    """Backfill alarm disposition columns for databases created from older schemas."""
    if not check_connection():
        return False

    required_columns = {
        'alarm_key': "ALTER TABLE alarm_record ADD COLUMN alarm_key VARCHAR(191) NULL COMMENT '前后端统一告警键' AFTER plate_number",
        'disposed_by': "ALTER TABLE alarm_record ADD COLUMN disposed_by VARCHAR(64) NULL COMMENT '处置人用户名' AFTER resolved_at",
        'disposition_note': "ALTER TABLE alarm_record ADD COLUMN disposition_note TEXT NULL COMMENT '处置备注' AFTER disposed_by",
        'disposed_at': "ALTER TABLE alarm_record ADD COLUMN disposed_at DATETIME NULL COMMENT '处置时间' AFTER disposition_note",
    }
    index_statements = [
        "CREATE INDEX idx_alarm_record_alarm_key ON alarm_record(alarm_key)",
        "CREATE INDEX idx_alarm_record_disposed_by ON alarm_record(disposed_by)",
        "CREATE INDEX idx_alarm_record_disposed_at ON alarm_record(disposed_at)",
    ]

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'alarm_record'
                    """,
                    (DB_SETTINGS['database'],),
                )
                existing = {row['COLUMN_NAME'] for row in cursor.fetchall()}
                for column, statement in required_columns.items():
                    if column not in existing:
                        cursor.execute(statement)

                cursor.execute(
                    """
                    SELECT INDEX_NAME
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'alarm_record'
                    """,
                    (DB_SETTINGS['database'],),
                )
                existing_indexes = {row['INDEX_NAME'] for row in cursor.fetchall()}
                for statement in index_statements:
                    index_name = statement.split()[2]
                    if index_name not in existing_indexes:
                        cursor.execute(statement)
        return True
    except Exception as exc:
        global _db_available_cache, _db_error_cache
        _db_available_cache = False
        _db_error_cache = str(exc)
        return False


def insert_alarm_record(alarm_type: str, device_id: str, alarm: Dict[str, Any], scene_id: Optional[str] = None):
    if not ensure_alarm_disposition_schema():
        return None

    data = alarm.get('data', {}) or {}
    target_id = data.get('track_id') or data.get('anomaly_id') or alarm.get('track_id')
    target_type = 'vehicle' if alarm_type == 'illegal_parking' else 'object'
    alarm_key = alarm.get('alarm_key') or build_alarm_key(alarm_type, alarm)
    description = None
    if alarm_type == 'illegal_parking':
        description = f"track_id={target_id} stay_time={data.get('stay_time')} threshold={data.get('threshold')}"
    elif alarm_type == 'road_anomaly':
        description = f"anomaly_type={data.get('anomaly_type')} lane={data.get('affected_lane')}"

    sql = """
    INSERT INTO alarm_record (
        alarm_type, device_id, scene_id, target_type, target_id,
        plate_number, alarm_key, description, bbox, status, detail_json, created_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()))
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
                alarm_key,
                description,
                _json_or_none(alarm.get('bbox')),
                alarm.get('status', 'warning'),
                _json_or_none({**alarm, 'alarm_key': alarm_key}),
                alarm.get('timestamp'),
            ))
            return cursor.lastrowid


def update_alarm_disposition(alarm_id: int, status: str, disposed_by: str, disposition_note: str = '') -> bool:
    if status not in {'acknowledged', 'resolved'}:
        return False
    if not ensure_alarm_disposition_schema():
        return False

    resolved_sql = ', resolved_at = NOW()' if status == 'resolved' else ''
    sql = f"""
    UPDATE alarm_record
    SET status = %s,
        disposed_by = %s,
        disposition_note = %s,
        disposed_at = NOW()
        {resolved_sql}
    WHERE id = %s
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (status, disposed_by, disposition_note, alarm_id))
            return cursor.rowcount == 1


def get_alarm_record(alarm_id: int) -> Optional[Dict[str, Any]]:
    if not ensure_alarm_disposition_schema():
        return None

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, alarm_type, device_id, scene_id, target_type, target_id,
                       plate_number, alarm_key, description, bbox, status, detail_json,
                       created_at, resolved_at, disposed_by, disposition_note, disposed_at
                FROM alarm_record
                WHERE id = %s
                LIMIT 1
                """,
                (alarm_id,),
            )
            return cursor.fetchone()


def list_alarm_dispositions(filters: Optional[Dict[str, Any]] = None):
    if not ensure_alarm_disposition_schema():
        return [], 0

    filters = filters or {}
    where_clauses = ['disposed_at IS NOT NULL']
    params = []

    if filters.get('disposed_by'):
        where_clauses.append('disposed_by = %s')
        params.append(filters['disposed_by'])
    if filters.get('status'):
        where_clauses.append('status = %s')
        params.append(filters['status'])
    if filters.get('alarm_type'):
        where_clauses.append('alarm_type = %s')
        params.append(filters['alarm_type'])

    limit = min(int(filters.get('limit', 50)), 500)
    offset = max(int(filters.get('offset', 0)), 0)
    where_sql = ' AND '.join(where_clauses)

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) as total FROM alarm_record WHERE {where_sql}', params)
            total = cursor.fetchone()['total']
            cursor.execute(
                f"""
                SELECT id, alarm_type, device_id, scene_id, target_type, target_id,
                       plate_number, alarm_key, description, bbox, status, detail_json,
                       created_at, resolved_at, disposed_by, disposition_note, disposed_at
                FROM alarm_record
                WHERE {where_sql}
                ORDER BY disposed_at DESC, created_at DESC
                LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            )
            return cursor.fetchall(), total
