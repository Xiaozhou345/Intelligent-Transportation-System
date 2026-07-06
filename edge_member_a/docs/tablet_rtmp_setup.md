# 平板 RTMP 推流配置说明

本说明用于成员A现场使用平板完成边端采集与传输。

## 推荐参数

| 参数 | 推荐值 |
| --- | --- |
| 协议 | RTMP |
| 推流地址 | `rtmp://<云端IP>:1935/live/mobile_001` |
| 分辨率 | `1280x720` |
| 帧率 | `15fps` |
| 编码格式 | `H.264` |
| 码率 | `1.5Mbps - 3Mbps`，优先使用 `2Mbps` |
| 场景编号 | `scene_704_sandbox` |
| 设备编号 | `mobile_001` |

## 操作步骤

1. 将平板固定在支架上，对准 704 智慧交通沙盘或道路区域。
2. 确认平板能访问云端电脑A的网络地址。
3. 打开支持 RTMP 的摄像头推流软件。
4. 填写推流地址：

   ```text
   rtmp://<云端IP>:1935/live/mobile_001
   ```

5. 设置视频参数：

   ```text
   1280x720
   15fps
   H.264
   2Mbps
   ```

6. 在电脑上执行设备注册：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json register
   ```

7. 平板点击开始推流。
8. 开启心跳：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json watch
   ```

9. 让成员B确认云端能看到设备在线，并能拉取 RTMP 视频流。

## 网络检查

在电脑上检查云端 API：

```powershell
Invoke-WebRequest http://<云端IP>:5000/api/health
```

检查云端设备列表：

```powershell
Invoke-WebRequest http://<云端IP>:5000/api/devices
```

## 降级策略

如果推流卡顿或断流，按顺序调整：

1. 码率从 `2Mbps` 降到 `1.5Mbps`。
2. 分辨率从 `1280x720` 降到 `854x480` 或 `640x480`。
3. 帧率从 `15fps` 降到 `10fps`。
4. 若 RTMP 持续失败，录制短视频段，使用 `segment_upload.py` 走 HTTP 上传备用方案。

## 需要提供给成员B的信息

- 设备编号：`mobile_001`
- 推流地址：`rtmp://<云端IP>:1935/live/mobile_001`
- 分辨率：`1280x720`
- 帧率：`15fps`
- 编码：`H.264`
- 码率：`2Mbps`
- 场景编号：`scene_704_sandbox`
