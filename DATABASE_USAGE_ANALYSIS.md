# 数据库使用情况完整分析报告

## 📅 分析时间
2026-07-12

## 🎯 分析目标
梳理项目中数据库的使用情况，包括：
- 数据库类型和连接方式
- 哪些模块使用了数据库
- 什么时候读取数据
- 什么时候写入数据
- 数据表结构

---

## 📊 数据库概览

### 数据库类型
- **类型**: MySQL
- **库名**: `intelligent_transportation_system`
- **字符集**: utf8mb4 (支持中文)
- **连接方式**: PyMySQL

### 连接配置

**文件**: `cloud/database/mysql_client.py:16-26`

```python
DB_SETTINGS = {
    'host': os.getenv('ITS_DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('ITS_DB_PORT', '3306')),
    'user': os.getenv('ITS_DB_USER', 'root'),
    'password': os.getenv('ITS_DB_PASSWORD', ''),
    'database': os.getenv('ITS_DB_NAME', 'intelligent_transportation_system'),
    'charset': 'utf8mb4',
    'cursorclass': DictCursor,
    'autocommit': True,
}
```

**配置说明**:
- 优先从环境变量读取
- 默认本地 MySQL (127.0.0.1:3306)
- 默认无密码（本地开发）
- 自动提交事务

---

## 🗄️ 数据表结构

### 1. edge_device (设备信息表)

**用途**: 存储边端设备信息

**字段**:
- `id`: 主键
- `device_id`: 设备编号（业务唯一）
- `device_type`: 设备类型
- `stream_url`: 视频流地址
- `scene_id`: 当前场景编号
- `status`: 在线状态 (online/offline)
- `resolution`: 分辨率
- `location_name`: 位置名称
- `config_json`: 设备配置（JSON）
- `created_at`: 创建时间
- `updated_at`: 更新时间

### 2. recognition_event (识别事件表)

**用途**: 存储所有识别事件（车辆检测、车牌识别等）

**字段**:
- `id`: 主键
- `event_type`: 事件类型 (vehicle_detection, plate_recognition, traffic_density 等)
- `device_id`: 设备编号
- `scene_id`: 场景编号
- `plate_number`: 车牌号
- `vehicle_type`: 车辆类型
- `confidence`: 置信度
- `bbox`: 检测框（JSON）
- `detail_json`: 完整详情（JSON）
- `created_at`: 创建时间

**索引**:
- `idx_device_time`: (device_id, created_at) - 按设备查询历史
- `idx_plate_time`: (plate_number, created_at) - 按车牌查询历史
- `idx_event_type`: (event_type) - 按事件类型查询

### 3. alarm_record (告警记录表)

**用途**: 存储告警事件（违停、道路异常）

**字段**:
- `id`: 主键
- `alarm_type`: 告警类型 (illegal_parking, road_anomaly)
- `device_id`: 设备编号
- `scene_id`: 场景编号
- `target_type`: 目标类型 (vehicle, anomaly)
- `target_id`: 目标ID
- `plate_number`: 车牌号
- `description`: 描述
- `bbox`: 检测框（JSON）
- `status`: 状态 (warning, acknowledged, resolved)
- `detail_json`: 完整详情（JSON）
- `created_at`: 创建时间
- `resolved_at`: 解决时间
- `operator`: 操作员

**索引**:
- `idx_device_status`: (device_id, status, created_at) - 按设备查询未处理告警
- `idx_alarm_type`: (alarm_type, status) - 按类型查询告警
- `idx_created_at`: (created_at) - 按时间查询

### 4. plate_whitelist (车牌白名单表)

**用途**: 存储允许通行的车牌

**字段**:
- `id`: 主键
- `plate_number`: 车牌号（唯一）
- `owner_name`: 车主姓名
- `owner_phone`: 车主电话
- `notes`: 备注
- `status`: 状态 (active, inactive)
- `created_at`: 创建时间
- `updated_at`: 更新时间

**索引**:
- `UNIQUE KEY`: (plate_number) - 车牌号唯一

### 5. system_config (系统配置表)

**用途**: 存储系统配置（阈值、禁停区等）

**字段**:
- `config_key`: 配置键（主键）
- `config_value`: 配置值（JSON）
- `description`: 配置说明
- `updated_at`: 更新时间

**示例配置**:
```json
{
  "traffic_thresholds": {"smooth_max": 2, "slow_max": 5},
  "no_parking_zone_default": [
    {
      "zone_id": "no_parking_A",
      "name": "禁停区A",
      "polygon": [[0.0736, 0.4300], ...],
      "threshold_seconds": 2
    }
  ]
}
```

---

## 🔌 数据库使用模块

### 使用数据库的模块

1. **cloud/database/mysql_client.py** - 数据库访问层
2. **cloud/stream_receiver/main_server.py** - 主服务器
3. **cloud/stream_receiver/video_processor.py** - 视频处理引擎
4. **cloud/stream_receiver/plate_recognition_processor.py** - 车牌识别处理器
5. **cloud/stream_receiver/device_manager.py** - 设备管理器
6. **tools/*.py** - 各种工具脚本

---

## 📖 数据库读取场景

### 1. 系统启动时 - 加载配置

**位置**: `cloud/stream_receiver/main_server.py:169`

```python
db_config = mysql_client.load_system_config()
```

**读取内容**:
- 禁停区配置 (no_parking_zone_default)
- 拥堵阈值 (traffic_thresholds)
- 其他系统配置

**时机**: 服务器启动时一次性加载

**用途**: 初始化系统参数

### 2. 车牌识别时 - 查询白名单

**位置**: `cloud/stream_receiver/plate_recognition_processor.py:311`

```python
row = mysql_client.get_whitelist_entry(plate_number)
```

**读取内容**:
- 查询车牌是否在白名单
- 获取车主信息

**时机**: 每次识别到车牌时

**用途**: 判断是否允许通行

**逻辑**:
```python
if row and row['status'] == 'active':
    decision = 'allow'
    decision_reason = f"白名单车辆 - {row.get('owner_name', '未知车主')}"
else:
    decision = 'deny'
    decision_reason = '非白名单车辆'
```

### 3. 系统状态检查 - 检查数据库连接

**位置**: `cloud/stream_receiver/main_server.py:377`

```python
db_ok = mysql_client.check_connection()
```

**读取内容**:
- 测试数据库连接是否正常

**时机**: 系统状态查询时

**用途**: 监控数据库健康状态

---

## 📝 数据库写入场景

### 1. 识别事件记录 - 持久化所有识别结果

**位置**: `cloud/stream_receiver/video_processor.py:2372`

```python
mysql_client.insert_recognition_event(event_type, result.get('device_id'), result, scene_id=scene_id)
```

**写入时机**: 
- ✅ 车辆检测事件 (`vehicle_detection`)
- ✅ 车牌识别事件 (`plate_recognition`)
- ✅ 流量密度事件 (`traffic_density`)
- ❌ video_overlay 事件（不写入数据库）

**写入内容**:
```python
{
    'event_type': 'plate_recognition',
    'device_id': 'edge_device_001',
    'plate_number': '京A12345',
    'confidence': 0.95,
    'bbox': [x1, y1, x2, y2],
    'detail_json': {...},  # 完整事件数据
    'created_at': '2026-07-12 10:30:00'
}
```

**用途**:
- 历史查询
- 数据分析
- 审计追溯

### 2. 告警记录 - 持久化告警事件

**位置**: `cloud/stream_receiver/video_processor.py:2374`

```python
if event_type in {'illegal_parking', 'road_anomaly'} and result.get('status') == 'warning':
    mysql_client.insert_alarm_record(event_type, result.get('device_id'), result, scene_id=scene_id)
```

**写入时机**:
- ✅ 违停告警 (`illegal_parking`)
- ✅ 道路异常告警 (`road_anomaly`)
- ✅ 且状态为 `warning`

**写入内容**:
```python
{
    'alarm_type': 'illegal_parking',
    'device_id': 'edge_device_001',
    'target_id': 5,  # track_id
    'plate_number': '京A12345',
    'description': '车辆5 停留180秒',
    'bbox': [x1, y1, x2, y2],
    'status': 'warning',
    'detail_json': {...},
    'created_at': '2026-0712 10:30:00'
}
```

**用途**:
- 告警管理
- 处置跟踪
- 统计分析

### 3. 车牌识别处理器 - 独立写入

**位置**: `cloud/stream_receiver/plate_recognition_processor.py:287`

```python
mysql_client.insert_recognition_event('plate_recognition', device_id, result, scene_id=scene_id)
```

**说明**: 车牌识别处理器也会独立写入识别事件

---

## 🔄 数据库访问流程

### 完整流程图

```
系统启动
    ↓
加载系统配置 (load_system_config)
    ↓
    ├─ 禁停区配置
    ├─ 拥堵阈值
    └─ 其他参数
    ↓
┌─────────────────────────────────┐
│     视频处理循环（每一帧）        │
└─────────────────────────────────┘
    ↓
AI 分析（车辆检测、车牌识别等）
    ↓
    ├─ 车牌识别成功？
    │   ↓ 是
    │   查询白名单 (get_whitelist_entry) ← 📖 读取数据库
    │   ↓
    │   判断通行权限
    │   ↓
    │   写入识别事件 (insert_recognition_event) ← 📝 写入数据库
    │
    ├─ 检测到违停？
    │   ↓ 是
    │   写入识别事件 (insert_recognition_event) ← 📝 写入数据库
    │   写入告警记录 (insert_alarm_record) ← 📝 写入数据库
    │
    ├─ 检测到道路异常？
    │   ↓ 是
    │   写入告警记录 (insert_alarm_record) ← 📝 写入数据库
    │
    └─ 其他事件
        ↓
        写入识别事件 (insert_recognition_event) ← 📝 写入数据库
```

### 数据库操作频率

| 操作类型 | 频率 | 说明 |
|---------|------|------|
| **load_system_config** | 启动时 1 次 | 加载系统配置 |
| **get_whitelist_entry** | 每次识别车牌 | 查询白名单 |
| **check_connection** | 状态查询时 | 健康检查 |
| **insert_recognition_event** | 每个事件 | 写入识别记录 |
| **insert_alarm_record** | 每个告警 | 写入告警记录 |

---

## ⚙️ 数据库配置方式

### 环境变量配置

```bash
# 数据库连接配置
export ITS_DB_HOST=127.0.0.1
export ITS_DB_PORT=3306
export ITS_DB_USER=root
export ITS_DB_PASSWORD=your_password
export ITS_DB_NAME=intelligent_transportation_system
```

### 数据库初始化

**SQL 脚本**: `cloud/database/mysql_schema.sql`

```bash
# 创建数据库和表
mysql -u root -p < cloud/database/mysql_schema.sql
```

---

## 🔍 数据库可用性检查

### 检查机制

**位置**: `cloud/database/mysql_client.py:31-50`

```python
def check_connection() -> bool:
    """检查数据库连接是否可用"""
    global _db_available_cache, _db_error_cache
    
    if _db_available_cache is not None:
        return _db_available_cache
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        _db_available_cache = True
        return True
    except Exception as e:
        _db_available_cache = False
        _db_error_cache = str(e)
        print(f"⚠️  数据库连接失败: {e}")
        print("   系统将继续运行，但不会记录历史数据")
        return False
```

### 容错机制

**特点**:
- ✅ 数据库不可用时系统继续运行
- ✅ 实时功能不受影响（WebSocket 推送正常）
- ⚠️ 不记录历史数据
- ⚠️ 不查询白名单（所有车辆默认拒绝）

**错误处理**:
```python
try:
    mysql_client.insert_recognition_event(...)
except Exception as e:
    print(f"数据库写入失败: {e}")
    # 继续运行，不影响实时处理
```

---

## 📊 数据库使用总结

### 读取操作（3种场景）

| 场景 | 频率 | 函数 | 用途 |
|------|------|------|------|
| 加载配置 | 启动时 1 次 | `load_system_config()` | 初始化参数 |
| 查询白名单 | 每次识别车牌 | `get_whitelist_entry(plate_number)` | 判断通行权限 |
| 健康检查 | 状态查询时 | `check_connection()` | 监控数据库 |

### 写入操作（2种场景）

| 场景 | 频率 | 函数 | 用途 |
|------|------|------|------|
| 识别事件 | 每个事件 | `insert_recognition_event()` | 记录所有识别结果 |
| 告警记录 | 每个告警 | `insert_alarm_record()` | 记录告警事件 |

### 不使用数据库的功能

✅ **以下功能不依赖数据库，实时运行**:
- 视频流接收和显示
- AI 模型推理（车辆检测、车牌识别）
- 实时检测框绘制
- WebSocket 推送到前端
- 事件流显示（EventStream.vue）
- 实时统计面板

⚠️ **以下功能需要数据库**:
- 历史查询（HistoryQuery.vue）
- 车牌白名单验证
- 告警管理和处置
- 数据导出（CSV/JSON）
- 长期数据分析

### 数据流向

```
实时数据流（不经过数据库）:
边端 → AI处理 → WebSocket → 前端实时显示

历史数据流（经过数据库）:
边端 → AI处理 → 写入MySQL → 历史查询 → 前端表格显示

白名单验证流程:
识别车牌 → 查询MySQL白名单 → 返回通行决策
```

---

## 🎯 关键发现

### 1. 数据库是可选的

✅ **数据库不可用时**:
- 实时功能正常（视频显示、检测框、事件流）
- WebSocket 推送正常
- 系统不会崩溃

⚠️ **受影响的功能**:
- 无法记录历史数据
- 无法查询历史
- 白名单功能失效

### 2. 数据库写入是异步的

```python
# 写入失败不影响实时处理
try:
    mysql_client.insert_recognition_event(...)
except Exception as e:
    print(f"数据库写入失败: {e}")
    # 继续处理下一帧
```

### 3. 白名单查询是同步的

```python
# 车牌识别时会等待数据库查询
row = mysql_client.get_whitelist_entry(plate_number)
if row and row['status'] == 'active':
    decision = 'allow'
```

**潜在问题**: 如果数据库查询慢，会影响车牌识别性能

---

## 📝 建议

### 1. 性能优化

**建议**: 缓存白名单到内存

```python
# 启动时加载白名单到内存
whitelist_cache = mysql_client.load_all_whitelist()

# 查询时从内存读取
if plate_number in whitelist_cache:
    decision = 'allow'
```

**效果**:
- ✅ 减少数据库查询
- ✅ 提高响应速度
- ✅ 降低数据库负载

### 2. 批量写入

**建议**: 批量写入识别事件

```python
# 每 10 秒或 100 条记录批量写入
event_buffer = []
if len(event_buffer) >= 100 or time.time() - last_flush > 10:
    mysql_client.insert_recognition_events_batch(event_buffer)
    event_buffer.clear()
```

**效果**:
- ✅ 减少数据库连接次数
- ✅ 提高写入效率
- ✅ 降低数据库负载

### 3. 监控数据库健康

**建议**: 定期检查数据库连接

```python
# 每 5 分钟检查一次
if not mysql_client.check_connection():
    send_alert("数据库连接失败")
```

---

**分析完成时间**: 2026-07-12  
**分析结论**: 数据库用于历史记录和白名单，实时功能不依赖数据库
