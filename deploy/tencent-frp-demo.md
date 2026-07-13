# 腾讯云 frp 演示部署方案

> 低延迟演示现在优先使用 [cloud-mediamtx-demo.md](./cloud-mediamtx-demo.md)：MediaMTX 直接运行在腾讯云，本地 frp 只转发 API 和前端。本文保留为旧方案参考。

本方案用于“本地电脑负责 AI 推理，腾讯云轻量服务器只做公网转发”的演示部署。

## 端口规划

| 用途 | 外部访问地址 | 转发到本地 AI 电脑 |
| --- | --- | --- |
| frp 控制连接 | `106.54.10.11:7000` | `frps` 本机 |
| 后端 API / Socket.IO | `http://106.54.10.11:15000` | `127.0.0.1:5001` |
| 前端开发服务 | `http://106.54.10.11:15173` | `127.0.0.1:5173` |
| 手机 WebRTC/WHIP 推流 | `http://106.54.10.11:18889/live/mobile_001/whip` | `127.0.0.1:8889` |
| 手机 RTMP 推流兜底 | `rtmp://106.54.10.11:1935/live/mobile_001` | `127.0.0.1:1935` |
| 前端 HLS 播放 | `http://106.54.10.11:18888/live/mobile_001/index.m3u8` | `127.0.0.1:8888` |
| 前端 WebRTC 信令 | `http://106.54.10.11:18889/live/mobile_001/whep` | `127.0.0.1:8889` |
| 前端 WebRTC 媒体 | `106.54.10.11:8189/udp` | `127.0.0.1:8189/udp` |

如果腾讯云公网 IP 变化，把所有 `106.54.10.11` 替换成新的公网 IP。

## 1. 腾讯云服务器

在腾讯云防火墙/安全组放行：

```text
7000
15000
15173
1935
18888
18889
8189/UDP
```

把 `deploy/frp/frps.toml` 上传到腾讯云服务器，并确认 `auth.token` 和本地 `deploy/frp/frpc.local-ai.toml` 一致。

启动：

```bash
cd ~/frp_0.69.1_linux_amd64
./frps -c frps.toml
```

如果提示 `./frps: No such file or directory`，说明当前目录不对，先用 `ls -lah` 找到 `frp_0.69.1_linux_amd64` 再进入该目录。

## 2. 本地 AI 电脑

本地电脑继续启动原来的服务：

```text
后端 API / Socket.IO: 127.0.0.1:5001
前端开发服务: 127.0.0.1:5173
RTMP 兼容接收服务: 127.0.0.1:1935
Low-Latency HLS 服务: 127.0.0.1:8888
WebRTC WHIP/WHEP 服务: 127.0.0.1:8889
WebRTC UDP 媒体端口: 127.0.0.1:8189
```

把 `deploy/frp/frpc.local-ai.toml` 中的 token 改成和服务器一致，然后启动：

```bash
./frpc -c frpc.local-ai.toml
```

启动后，公网访问 `106.54.10.11:15000/15173/1935/18888/18889` 会转发到本地 AI 电脑。

## 3. 手机推流

推荐使用前端内置的手机发布页。未配置 HTTPS 时，可以临时访问：

```text
http://106.54.10.11:15173/?mode=publisher
```

发布页会通过 WHIP 推流到：

```text
http://106.54.10.11:18889/live/mobile_001/whip
```

手机浏览器调用摄像头通常要求 HTTPS；公网正式演示时，前端页面和 WHIP/WHEP 地址建议都配置 HTTPS。若暂时来不及配证书，可继续使用 RTMP 或“手机当电脑摄像头 + 电脑 FFmpeg 低延迟推流”作为兜底。

HTTPS 正式配置见 [https-webrtc-demo.md](./https-webrtc-demo.md)。

RTMP 兜底地址：

```text
rtmp://106.54.10.11:1935/live/mobile_001
```

## 4. 边端注册脚本

复制配置：

```powershell
Copy-Item edge_member_a\config.tencent_frp.example.json edge_member_a\config.json
```

注册设备：

```powershell
python edge_member_a\edge_client.py --config edge_member_a\config.json register
```

保持心跳：

```powershell
python edge_member_a\edge_client.py --config edge_member_a\config.json watch
```

## 5. 前端

复制前端环境变量：

```powershell
Copy-Item ui\.env.tencent-frp.example ui\.env
```

然后重新启动前端开发服务，或者重新构建前端。

## 6. 快速验证

在任意能上网的电脑上访问：

```text
http://106.54.10.11:15000/api/health
http://106.54.10.11:18889/live/mobile_001/whip
http://106.54.10.11:18889/live/mobile_001/whep
http://106.54.10.11:18888/live/mobile_001/index.m3u8
```

如果 API 能打开，说明 `5001` 转发正常。
如果手机发布页开始推流后前端 WebRTC 有画面，说明 `8889` 和 `8189/UDP` 链路正常。
如果 WebRTC 不通但 HLS 地址能播放，说明兜底链路可用，但延迟会更高。

说明：浏览器前端当前优先播放 WebRTC，不再优先播放 HLS。`cloud/stream_receiver/start_rtmp_server.sh` 仍保留 RTMP 和 Low-Latency HLS 作为兜底。
