# 视频流接收模块

## 模块说明

本模块负责接收边端设备推送的视频流，并提供设备管理功能。

## 文件结构

```
stream_receiver/
├── device_manager.py   # 设备管理器
├── api_server.py       # HTTP API服务
└── test_api.py         # API测试脚本
```

## HTTP API接口

### 1. 设备注册

**接口地址**：`POST /api/register_device`

**请求体**：
```json
{
  "device_id": "mobile_001",
  "device_type": "huawei_tablet",
  "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
  "resolution": "1280x720",
  "fps": 15,
  "scene_id": "scene_704_sandbox",
  "codec": "H.264",
  "bitrate": "2Mbps",
  "timestamp": "2026-07-06 13:00:00"
}
```

**响应**：
```json
{
  "status": "success",
  "message": "设备注册成功",
  "device_id": "mobile_001"
}
```

---

### 2. 设备注销

**接口地址**：`POST /api/unregister_device`

**请求体**：
```json
{
  "device_id": "mobile_001"
}
```

**响应**：
```json
{
  "status": "success",
  "message": "设备注销成功"
}
```

---

### 3. 心跳上报（可选）

**接口地址**：`POST /api/heartbeat`

**请求体**：
```json
{
  "device_id": "mobile_001",
  "timestamp": "2026-07-06 13:00:00"
}
```

**响应**：
```json
{
  "status": "success",
  "message": "心跳更新成功"
}
```

---

### 4. 获取所有设备

**接口地址**：`GET /api/devices`

**响应**：
```json
{
  "status": "success",
  "count": 1,
  "devices": [
    {
      "device_id": "mobile_001",
      "device_type": "huawei_tablet",
      "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
      "resolution": "1280x720",
      "fps": 15,
      "scene_id": "scene_704_sandbox",
      "codec": "H.264",
      "bitrate": "2Mbps",
      "register_time": "2026-07-06 13:00:00",
      "last_heartbeat": "2026-07-06 13:00:00",
      "status": "online"
    }
  ]
}
```

---

### 5. 获取单个设备信息

**接口地址**：`GET /api/device/<device_id>`

**示例**：`GET /api/device/mobile_001`

**响应**：
```json
{
  "status": "success",
  "device": {
    "device_id": "mobile_001",
    "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
    ...
  }
}
```

---

### 6. 健康检查

**接口地址**：`GET /api/health`

**响应**：
```json
{
  "status": "ok",
  "message": "云端服务运行正常"
}
```

---

## 使用方法

### 启动API服务

```bash
cd cloud/stream_receiver
python3 api_server.py
```

服务将在 `http://0.0.0.0:5000` 启动。

### 测试API

在另一个终端运行：
```bash
python3 test_api.py
```

---

## 给边端（成员A）的对接信息

### 你需要提供给A的信息：

1. **HTTP接口地址**：
   - 设备注册：`POST http://你的电脑IP:5000/api/register_device`
   - 例如：`POST http://192.168.1.100:5000/api/register_device`

2. **RTMP推流地址**（明天搭建RTMP服务器后提供）：
   - 格式：`rtmp://你的电脑IP:1935/live/stream_001`
   - 例如：`rtmp://192.168.1.100:1935/live/stream_001`

3. **推荐视频参数**：
   - 分辨率：1280×720
   - 帧率：15fps
   - 编码：H.264
   - 码率：2Mbps

### A需要提供给你的信息：

1. 设备ID：`mobile_001`（可以你们约定）
2. 场景ID：`scene_704_sandbox`（可以你们约定）
3. 测试时间：待确定

---

## 边端调用示例（Python）

```python
import requests

# 1. 注册设备
response = requests.post(
    "http://192.168.1.100:5000/api/register_device",
    json={
        "device_id": "mobile_001",
        "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
        "resolution": "1280x720",
        "fps": 15,
        "scene_id": "scene_704_sandbox",
        "codec": "H.264",
        "bitrate": "2Mbps"
    }
)
print(response.json())

# 2. 开始推流（使用推流软件推送到stream_url）

# 3. 定期心跳（可选）
response = requests.post(
    "http://192.168.1.100:5000/api/heartbeat",
    json={"device_id": "mobile_001"}
)
print(response.json())
```

---

## 边端调用示例（curl命令）

```bash
# 注册设备
curl -X POST http://192.168.1.100:5000/api/register_device \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "mobile_001",
    "stream_url": "rtmp://192.168.1.100:1935/live/stream_001",
    "resolution": "1280x720",
    "fps": 15,
    "scene_id": "scene_704_sandbox"
  }'

# 查看所有设备
curl http://192.168.1.100:5000/api/devices
```

---

## 后续工作

- [ ] 搭建RTMP服务器（nginx-rtmp或SRS）
- [ ] 实现视频流接收和解帧
- [ ] 将视频帧送入AI模型处理
- [ ] 与前端WebSocket对接
