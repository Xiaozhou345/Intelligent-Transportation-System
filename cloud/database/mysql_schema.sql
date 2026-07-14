-- 智慧交通系统 MySQL 建表脚本
-- 说明：
-- 1. 使用 utf8mb4 兼容中文车牌；
-- 2. event / alarm 详情使用 JSON，便于后续扩展不同业务场景字段；
-- 3. 本脚本只负责建表，不直接改动当前 Python 运行逻辑。

CREATE DATABASE IF NOT EXISTS intelligent_transportation_system
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE intelligent_transportation_system;

-- 设备信息表
CREATE TABLE IF NOT EXISTS edge_device (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  device_id VARCHAR(64) NOT NULL COMMENT '设备编号，业务唯一标识',
  device_type VARCHAR(64) NOT NULL DEFAULT 'unknown' COMMENT '设备类型',
  stream_url VARCHAR(512) NOT NULL COMMENT '视频流地址',
  scene_id VARCHAR(64) NOT NULL DEFAULT 'default' COMMENT '当前场景编号',
  status ENUM('online', 'offline') NOT NULL DEFAULT 'online' COMMENT '在线状态',
  resolution VARCHAR(32) NULL COMMENT '分辨率，例如 1280x720',
  fps INT NULL COMMENT '帧率',
  codec VARCHAR(32) NULL COMMENT '编码格式',
  bitrate VARCHAR(32) NULL COMMENT '码率',
  register_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  last_heartbeat DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近心跳时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_edge_device_device_id (device_id),
  KEY idx_edge_device_status (status),
  KEY idx_edge_device_scene_id (scene_id),
  KEY idx_edge_device_last_heartbeat (last_heartbeat)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='边端设备信息表';

-- 白名单车辆表
CREATE TABLE IF NOT EXISTS vehicle_whitelist (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  plate_number VARCHAR(32) NOT NULL COMMENT '车牌号',
  vehicle_type VARCHAR(64) NULL COMMENT '车辆类型',
  permission_status TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否允许通行：1允许，0禁止',
  remark TEXT NULL COMMENT '备注',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_vehicle_whitelist_plate_number (plate_number),
  KEY idx_vehicle_whitelist_permission_status (permission_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='白名单车辆表';

-- 识别/分析事件表
CREATE TABLE IF NOT EXISTS recognition_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  event_type VARCHAR(64) NOT NULL COMMENT '事件类型：plate_recognition / vehicle_detection / traffic_density / road_anomaly / illegal_parking 等',
  device_id VARCHAR(64) NOT NULL COMMENT '设备编号',
  scene_id VARCHAR(64) NULL COMMENT '场景编号',
  plate_number VARCHAR(32) NULL COMMENT '车牌号，可为空',
  bbox JSON NULL COMMENT '目标框坐标，格式 [x1,y1,x2,y2]',
  result_json JSON NOT NULL COMMENT '完整识别结果 JSON',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '事件时间',
  PRIMARY KEY (id),
  KEY idx_recognition_event_event_type (event_type),
  KEY idx_recognition_event_device_id (device_id),
  KEY idx_recognition_event_scene_id (scene_id),
  KEY idx_recognition_event_plate_number (plate_number),
  KEY idx_recognition_event_created_at (created_at),
  CONSTRAINT fk_recognition_event_device_id
    FOREIGN KEY (device_id) REFERENCES edge_device(device_id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='识别与分析事件表';

-- 告警记录表
CREATE TABLE IF NOT EXISTS alarm_record (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  alarm_type VARCHAR(64) NOT NULL COMMENT '告警类型：illegal_parking / road_anomaly 等',
  device_id VARCHAR(64) NOT NULL COMMENT '设备编号',
  scene_id VARCHAR(64) NULL COMMENT '场景编号',
  target_type VARCHAR(64) NULL COMMENT '目标类型：vehicle / object / plate 等',
  target_id VARCHAR(64) NULL COMMENT '目标 ID，例如 track_id 或 anomaly_id',
  plate_number VARCHAR(32) NULL COMMENT '涉及的车牌号（如有）',
  alarm_key VARCHAR(191) NULL COMMENT '前后端统一告警键',
  description TEXT NULL COMMENT '告警描述',
  bbox JSON NULL COMMENT '告警目标位置',
  status ENUM('warning', 'acknowledged', 'resolved') NOT NULL DEFAULT 'warning' COMMENT '告警状态',
  detail_json JSON NULL COMMENT '完整告警数据 JSON',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '告警时间',
  resolved_at DATETIME NULL COMMENT '解除时间',
  disposed_by VARCHAR(64) NULL COMMENT '处置人用户名',
  disposition_note TEXT NULL COMMENT '处置备注',
  disposed_at DATETIME NULL COMMENT '处置时间',
  PRIMARY KEY (id),
  KEY idx_alarm_record_alarm_type (alarm_type),
  KEY idx_alarm_record_device_id (device_id),
  KEY idx_alarm_record_scene_id (scene_id),
  KEY idx_alarm_record_target_id (target_id),
  KEY idx_alarm_record_alarm_key (alarm_key),
  KEY idx_alarm_record_plate_number (plate_number),
  KEY idx_alarm_record_status (status),
  KEY idx_alarm_record_created_at (created_at),
  KEY idx_alarm_record_disposed_by (disposed_by),
  KEY idx_alarm_record_disposed_at (disposed_at),
  CONSTRAINT fk_alarm_record_device_id
    FOREIGN KEY (device_id) REFERENCES edge_device(device_id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='告警记录表';

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
  config_key VARCHAR(128) NOT NULL COMMENT '配置项名称',
  config_value JSON NOT NULL COMMENT '配置项值，统一使用 JSON 便于扩展',
  description TEXT NULL COMMENT '配置说明',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统配置表';

-- 用户表
CREATE TABLE IF NOT EXISTS system_user (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  username VARCHAR(64) NOT NULL COMMENT '用户名',
  email VARCHAR(128) NULL COMMENT '绑定邮箱',
  password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希（bcrypt）',
  role ENUM('admin', 'user') NOT NULL DEFAULT 'user' COMMENT '角色：admin管理员，user普通用户',
  status TINYINT(1) NOT NULL DEFAULT 1 COMMENT '状态：1启用，0禁用',
  last_login DATETIME NULL COMMENT '最后登录时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_system_user_username (username),
  UNIQUE KEY uk_system_user_email (email),
  KEY idx_system_user_role (role),
  KEY idx_system_user_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统用户表';

-- 密码找回验证码表
CREATE TABLE IF NOT EXISTS password_reset_code (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_id BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
  email VARCHAR(128) NOT NULL COMMENT '接收验证码邮箱',
  code_hash VARCHAR(255) NOT NULL COMMENT '验证码哈希',
  expires_at DATETIME NOT NULL COMMENT '过期时间',
  used_at DATETIME NULL COMMENT '使用时间',
  attempt_count INT NOT NULL DEFAULT 0 COMMENT '校验失败次数',
  request_ip VARCHAR(64) NULL COMMENT '请求来源IP',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_password_reset_user_id (user_id),
  KEY idx_password_reset_email (email),
  KEY idx_password_reset_expires_at (expires_at),
  CONSTRAINT fk_password_reset_user_id
    FOREIGN KEY (user_id) REFERENCES system_user(id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='密码找回验证码表';

-- 插入默认管理员账号（密码：admin123）
INSERT INTO system_user (username, password_hash, role, status)
VALUES ('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYIRJz8kR/u', 'admin', 1)
ON DUPLICATE KEY UPDATE username = username;

-- 可选：写入初始配置示例
INSERT INTO system_config (config_key, config_value, description)
VALUES
  ('traffic_thresholds', JSON_OBJECT('smooth_max', 2, 'slow_max', 5), '拥堵热力图阈值'),
  ('no_parking_zone_default', JSON_ARRAY(
      JSON_OBJECT(
        'zone_id', 'no_parking_A',
        'name', '禁停区A',
        'polygon', JSON_ARRAY(
          JSON_ARRAY(0.0736, 0.4300),
          JSON_ARRAY(0.8062, 0.4300),
          JSON_ARRAY(0.8450, 0.7350),
          JSON_ARRAY(0.0698, 0.7390)
        ),
        'threshold_seconds', 2
      )
    ), '默认禁停区配置')
ON DUPLICATE KEY UPDATE
  config_value = VALUES(config_value),
  description = VALUES(description);
