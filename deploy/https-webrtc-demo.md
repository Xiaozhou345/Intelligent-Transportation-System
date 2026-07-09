# HTTPS + WebRTC 公网演示方案

本方案用于手机和电脑不在同一网络时的低延迟演示：

```text
手机浏览器 HTTPS 页面
  -> HTTPS WHIP 信令
  -> 腾讯云 frp
  -> 本地 AI 电脑 MediaMTX
  -> 前端 HTTPS WHEP 播放
```

## 前提

1. 有一个域名，并把 DNS A 记录指向腾讯云公网 IP：

```text
106.54.10.11
```

2. 腾讯云安全组放行：

```text
80
443
7000
15000
15173
18888
18889
8189/UDP
```

`8189/UDP` 是 WebRTC 媒体端口，不能只开 TCP。

## 本地 AI 电脑

启动 MediaMTX：

```powershell
cd D:\mediamtx\mediamtx_v1.19.2_windows_amd64
.\mediamtx.exe
```

启动前端，注意必须允许局域网/本机外部访问，frp 才能转发：

```powershell
cd D:\大二下小学期\Intelligent-Transportation-System\ui
npm run dev -- --host 0.0.0.0
```

启动 frpc：

```powershell
cd D:\大二下小学期\Intelligent-Transportation-System
.\frpc.exe -c deploy\frp\frpc.local-ai.toml
```

`deploy/frp/frpc.local-ai.toml` 会把本地端口转成：

```text
本地前端 5173 -> 云服务器 15173
本地后端 5000 -> 云服务器 15000
MediaMTX HTTP/WebRTC 8889 -> 云服务器 18889
MediaMTX UDP/ICE 8189 -> 云服务器 8189/UDP
```

## 腾讯云服务器

启动 frps：

```bash
cd ~/frp_0.69.1_linux_amd64
./frps -c frps.toml
```

安装 Caddy 后，创建或编辑 `/etc/caddy/Caddyfile`。

把 `its.example.com` 换成你的真实域名：

```caddyfile
its.example.com {
    reverse_proxy /live/* 127.0.0.1:18889
    reverse_proxy /api/* 127.0.0.1:15000
    reverse_proxy /socket.io/* 127.0.0.1:15000
    reverse_proxy 127.0.0.1:15173
}
```

重载 Caddy：

```bash
sudo systemctl reload caddy
```

Caddy 会自动申请 HTTPS 证书。证书申请要求域名已经解析到服务器，并且 80/443 已放行。

## 前端环境变量

公网 HTTPS 演示时，`ui/.env` 推荐写成：

```text
VITE_CLOUD_SERVER_URL=https://its.example.com
VITE_LIVE_VIDEO_URL=https://its.example.com/live/mobile_001/index.m3u8
VITE_LIVE_WEBRTC_URL=https://its.example.com/live/mobile_001/whep
VITE_LIVE_WHIP_URL=https://its.example.com/live/mobile_001/whip
VITE_SIMULATION_MODE=false
```

修改后重启前端：

```powershell
cd D:\大二下小学期\Intelligent-Transportation-System\ui
npm run dev -- --host 0.0.0.0
```

## 使用地址

手机推流页：

```text
https://its.example.com/?mode=publisher
```

前端大屏页：

```text
https://its.example.com/
```

MediaMTX 日志中看到 `WHIP` 发布、`WebRTC` 读取，并且前端有画面，就说明公网不同网络链路跑通。

## 常见问题

- 手机推流页打不开摄像头：确认访问地址是 `https://`，不是 `http://`。
- 前端有页面但无视频：确认 Caddy 的 `/live/*` 反代到 `127.0.0.1:18889`。
- WebRTC 建连失败：确认腾讯云安全组和系统防火墙都放行 `8189/UDP`。
- Caddy 证书申请失败：确认域名 DNS 已经指向 `106.54.10.11`，并且 80/443 没被其他程序占用。
