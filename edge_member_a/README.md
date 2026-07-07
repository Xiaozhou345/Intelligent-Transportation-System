# 成员A：边端采集与传输模块

本目录是成员A的独立开发目录，严格对应需求分析文档和系统设计报告中的“边端采集与传输层”。

## 职责范围

- 使用平板/手机摄像头采集交通沙盘或道路画面。
- 通过 RTMP 将实时视频推送到云端。
- 向云端上报设备编号、视频流地址、分辨率、帧率、编码格式、场景编号和时间戳。
- 推流期间定期发送心跳，辅助云端判断设备在线状态。
- RTMP 不稳定时，保留 HTTP 视频段上传作为备用方案。

边端不负责车牌识别、车辆检测、违停跟踪或道路异常检测，这些由云端成员B负责。

## 目录结构

```text
edge_member_a/
├── config.example.json          # 边端配置样例
├── edge_client.py               # 设备注册、心跳、注销客户端
├── stream_monitor.py            # 拉流验证与视频传输状态监控
├── segment_upload.py            # HTTP视频段备用上传客户端
├── docs/
│   ├── tablet_rtmp_setup.md     # 平板RTMP推流配置说明
│   └── ffmpeg_push_example.md   # 电脑模拟推流说明
└── README.md
```

## 第一次使用

复制配置样例：

```powershell
Copy-Item edge_member_a\config.example.json edge_member_a\config.json
```

修改 `edge_member_a/config.json`：

- `cloud_api_base`：成员B云端 API 地址，例如 `http://192.168.1.100:5000`
- `rtmp_server`：成员B RTMP 服务器 IP，例如 `192.168.1.100`
- `device_id`：设备编号，例如 `mobile_001`
- `scene_id`：场景编号，例如 `scene_704_sandbox`

查看最终推流配置：

```powershell
python edge_member_a\edge_client.py --config edge_member_a\config.json print-config
```

## 推荐联调流程

1. 成员B启动云端 HTTP API 服务。
2. 成员B启动 RTMP 接收服务，确认 1935 端口可访问。
3. 成员A在平板 RTMP 推流软件中填入：

   ```text
   rtmp://<云端IP>:1935/live/mobile_001
   ```

4. 成员A注册设备：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json register
   ```

5. 平板开始推流。
6. 成员A开启心跳：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json watch
   ```

7. 成员B在云端查看设备状态：

   ```text
   GET http://<云端IP>:5000/api/devices
   ```

8. 停止推流后注销设备：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json unregister
   ```

## 拉流与传输状态监控

老师要求验证“拉流”和“视频传输状态监控”时，先确保：

1. 云端 API 已启动；
2. MediaMTX / RTMP 服务已启动；
3. 平板 Larix 已开始推流；
4. `config.json` 中的 `cloud_api_base` 和 `rtmp_server` 指向同一台云端电脑。

单次检查：

```powershell
python edge_member_a\stream_monitor.py --config edge_member_a\config.json
```

持续监控：

```powershell
python edge_member_a\stream_monitor.py --config edge_member_a\config.json --watch
```

该脚本会检查：

- 云端 `/api/health` 是否可访问；
- 当前设备是否已注册；
- RTMP 端口 `1935` 是否连通；
- 是否能从 `rtmp://<云端IP>:1935/live/mobile_001` 真正读取视频帧；
- 读取到的帧数、分辨率和粗略 FPS。

如果输出：

```text
[OK] rtmp frame pulling
```

说明云端已经可以拉取并解码平板推送的视频流。

## 接口对接

当前仓库中成员B已实现的接口为：

| 功能 | 方法 | 路径 |
| --- | --- | --- |
| 设备注册 | POST | `/api/register_device` |
| 心跳上报 | POST | `/api/heartbeat` |
| 设备注销 | POST | `/api/unregister_device` |
| 获取设备列表 | GET | `/api/devices` |

注册请求体字段与系统设计报告保持一致：

```json
{
  "device_id": "mobile_001",
  "device_type": "huawei_tablet",
  "stream_url": "rtmp://192.168.1.100:1935/live/mobile_001",
  "scene_id": "scene_704_sandbox",
  "resolution": "1280x720",
  "fps": 15,
  "codec": "H.264",
  "bitrate": "2Mbps",
  "timestamp": "2026-07-06 13:00:00"
}
```

## 备用视频段上传

设计报告要求 RTMP 失败时支持 HTTP 视频段上传。客户端已提供：

```powershell
python edge_member_a\segment_upload.py --config edge_member_a\config.json .\sample.mp4
```

注意：当前云端代码暂未实现 `/api/video/upload`，需要成员B补充接口后才能完整联调。
