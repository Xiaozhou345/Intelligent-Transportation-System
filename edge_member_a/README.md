# 成员A：边端采集与传输模块

本目录是成员A的独立开发目录，严格对应需求分析文档和系统设计报告中的“边端采集与传输层”。

## 职责范围

- 使用平板/手机摄像头采集交通沙盘或道路画面。
- 通过 SRT 将实时视频推送到云端 MediaMTX，RTMP 作为兜底。
- 向云端上报设备编号、视频流地址、分辨率、帧率、编码格式、场景编号和时间戳。
- 推流期间定期发送心跳，辅助云端判断设备在线状态。
- 实时推流不稳定时，保留 HTTP 视频段上传作为备用方案。

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

- `cloud_api_base`：本地 AI 后端经 frp 暴露的 API 地址，例如 `http://106.54.10.11:15000`
- `stream_url`：本地 AI 要拉取的云端 MediaMTX RTSP 地址，例如 `rtsp://106.54.10.11:8554/live/mobile_001`
- `srt_push_url`：手机推流 App 使用的 SRT 地址，例如 `srt://106.54.10.11:8890?streamid=publish:live/mobile_001&latency=200`
- `rtmp_server`：云端 MediaMTX 的公网 IP，用于 RTMP 兜底推流
- `device_id`：设备编号，例如 `mobile_001`
- `scene_id`：场景编号，例如 `scene_704_sandbox`

查看最终推流配置：

```powershell
python edge_member_a\edge_client.py --config edge_member_a\config.json print-config
```

## 推荐联调流程

1. 腾讯云服务器启动 MediaMTX，并确认 SRT/RTMP/RTSP/WHEP/HLS 相关端口已放行。
2. 本地 AI 电脑启动后端 API，并通过 frp 暴露到公网 `15000`。
3. 成员A优先在手机/平板 SRT 推流 App 中填入：

   ```text
   srt://<云端IP>:8890?streamid=publish:live/mobile_001&latency=200
   ```

   如果 App 只支持 RTMP，则使用兜底地址：

   ```text
   rtmp://<云端IP>:1935/live/mobile_001
   ```

4. 成员A注册设备。注册时的 `stream_url` 应填写本地 AI 要拉取的云端 RTSP 地址：

   ```text
   rtsp://<云端IP>:8554/live/mobile_001
   ```

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json register
   ```

5. 平板开始推流。
6. 成员A开启心跳：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json watch
   ```

7. 成员B在本地后端或公网 frp 地址查看设备状态：

   ```text
   GET http://<云端IP>:15000/api/devices
   ```

8. 停止推流后注销设备：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json unregister
   ```

## 拉流与传输状态监控

老师要求验证“拉流”和“视频传输状态监控”时，先确保：

1. 本地 AI 后端 API 已启动，并且 frp 公网转发可访问；
2. 腾讯云 MediaMTX 已启动；
3. 手机/平板 SRT 或 RTMP 推流已开始；
4. `config.json` 中的 `cloud_api_base` 指向 frp 暴露的本地后端 API，`stream_url` 指向云端 MediaMTX 的 RTSP 拉流地址。

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
- RTMP 端口 `1935` 是否连通（兜底推流）；
- 是否能从 `stream_url` 指向的 RTSP/RTMP 地址真正读取视频帧；
- 读取到的帧数、分辨率和粗略 FPS。

如果输出：

```text
[OK] stream frame pulling
```

说明本地 AI 已经可以从云端 MediaMTX 拉取并解码平板推送的视频流。

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
  "stream_url": "rtsp://106.54.10.11:8554/live/mobile_001",
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

云端主服务提供 `/api/video/upload` 作为最小备用接收接口，用于保存视频段并返回文件信息；实时分析仍以云端 MediaMTX 的 RTSP 拉流为主。
