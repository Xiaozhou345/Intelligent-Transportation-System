# FFmpeg 模拟边端推流

如果平板暂时不方便测试，可以用电脑上的视频文件模拟边端推流。

## 前置条件

- 成员B已经启动 RTMP 服务器。
- 本机安装 FFmpeg。
- `config.json` 中的 `rtmp_server` 已改成云端电脑A的 IP。

## 使用本地视频模拟推流

```powershell
ffmpeg -re -i .\sample.mp4 -c:v libx264 -preset veryfast -tune zerolatency -r 15 -s 1280x720 -b:v 2M -c:a aac -f flv rtmp://<云端IP>:1935/live/mobile_001
```

## 使用摄像头模拟推流

Windows 摄像头设备名称需要先用 FFmpeg 查询：

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

然后推流：

```powershell
ffmpeg -f dshow -i video="<摄像头名称>" -c:v libx264 -preset veryfast -tune zerolatency -r 15 -s 1280x720 -b:v 2M -f flv rtmp://<云端IP>:1935/live/mobile_001
```

## 联调顺序

1. 注册设备：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json register
   ```

2. 开始 FFmpeg 推流。
3. 开启心跳：

   ```powershell
   python edge_member_a\edge_client.py --config edge_member_a\config.json watch
   ```

4. 成员B确认云端能读取视频帧。
