# 云端 MediaMTX 低延迟演示方案

本方案用于当前网络限制：手机和电脑不在同一热点、没有域名、RTMP 手机 App 延迟偏高。核心调整是把 MediaMTX 放到腾讯云，云端只做流媒体中转，本地电脑继续跑后端和 AI。

## 链路

```text
手机 SRT/RTMP 推流 App
  -> 腾讯云 MediaMTX
  -> 前端 WebRTC/WHEP 播放
  -> 本地 AI 电脑从云端 RTSP 拉流取帧
```

## 端口

腾讯云安全组和系统防火墙放行：

```text
1935/TCP   RTMP 兜底推流
8890/UDP   SRT 推荐推流
8889/TCP   WHEP/WebRTC 信令
8189/UDP   WebRTC 媒体
8554/TCP   本地 AI 拉 RTSP
8888/TCP   HLS 兜底播放
7000/TCP   frp 控制连接
15000/TCP  本地后端 API / Socket.IO
15173/TCP  本地前端开发服务
```

## 1. 腾讯云启动 MediaMTX

把 [deploy/mediamtx/cloud-mediamtx.yml](./mediamtx/cloud-mediamtx.yml) 上传到服务器。如果公网 IP 不是 `106.54.10.11`，先把配置里的 `webrtcAdditionalHosts` 改成你的公网 IP。

启动示例：

```bash
./mediamtx ./cloud-mediamtx.yml
```

也可以把整个 `deploy/mediamtx/` 目录上传到服务器，然后运行：

```bash
chmod +x ./start-cloud-mediamtx.sh
PUBLIC_IP=106.54.10.11 ./start-cloud-mediamtx.sh
```

云端 MediaMTX 地址：

```text
SRT 推流:  srt://106.54.10.11:8890?streamid=publish:live/mobile_001&latency=200
RTMP 兜底: rtmp://106.54.10.11:1935/live/mobile_001
WHEP 播放: http://106.54.10.11:8889/live/mobile_001/whep
HLS 兜底:  http://106.54.10.11:8888/live/mobile_001/index.m3u8
RTSP 拉流: rtsp://106.54.10.11:8554/live/mobile_001
```

### 1.1 配置开机自启和异常重启

不要把 MediaMTX 和 frps 长期留在 SSH 前台窗口中运行。确认二进制目录分别为
`/home/ubuntu/mediamtx` 和 `/home/ubuntu/frp_0.69.1_linux_amd64` 后，将仓库中的服务文件安装到 systemd：

```bash
sudo cp deploy/mediamtx/its-mediamtx.service /etc/systemd/system/
sudo cp deploy/frp/its-frps.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now its-mediamtx its-frps
```

检查服务和端口：

```bash
systemctl --no-pager --full status its-mediamtx its-frps
ss -lntup | grep -E ':(7000|8554|8888|8889|8890|8189)\\b'
```

实时查看日志：

```bash
journalctl -u its-mediamtx -u its-frps -f
```

如果实际安装目录不同，先修改两个 `.service` 文件中的 `WorkingDirectory` 和
`ExecStart`，再执行 `daemon-reload` 与 `restart`。

## 2.1 本地启动后端 AI 服务

你的电脑仍然负责：

- 后端 HTTP API / Socket.IO
- AI 模型推理（车辆检测、违停、道路异常等）

### WSL 启动方式

```bash
cd /root/S/Intelligent-Transportation-System
python3 cloud/stream_receiver/main_server.py
```

### Windows 镜像启动方式

```powershell
cd E:\Intelligent-Transportation-System
cloud\start-main-server.bat
```

启动后，本地服务监听：

```text
127.0.0.1:5001
```

frpc 会把它暴露到云端：

```text
http://106.54.10.11:15000
```

## 2.2 本地启动前端页面

前端页面同样跑在你的电脑上，视频由腾讯云提供，事件结果由你本地后端经 frp 暴露后提供。

### WSL 启动方式

```bash
cd /root/S/Intelligent-Transportation-System/ui
cp .env.tencent-frp.example .env
npm install
npm run dev -- --host 0.0.0.0
```

然后浏览器打开：

```text
http://localhost:5173
```

### Windows 侧访问

如果前端服务跑在 WSL，也可以直接在 Windows 浏览器打开：

```text
http://localhost:5173
```

frpc 会把前端暴露到云端：

```text
http://106.54.10.11:15173
```

## 2.3 本地启动 frpc

本地 frp 现在只转发后端和前端，不再转发 RTMP/HLS/WebRTC：

### Windows（推荐）

仓库已为当前机器准备好下载目录，`frp` 已下载并建议解压到：

```text
E:\Intelligent-Transportation-System\tools\frp\frp_0.69.1_windows_amd64
```

直接双击运行：

```text
deploy\frp\start-frpc-local-ai.bat
```

等价命令为：

```powershell
cd E:\Intelligent-Transportation-System\tools\frp\frp_0.69.1_windows_amd64
.\frpc.exe -c E:\Intelligent-Transportation-System\deploy\frp\frpc.local-ai.toml
```

> 注意：PowerShell 下运行当前目录程序通常要写成 `./frpc.exe` 或 `.\frpc.exe`。

### WSL / Linux（可选）

如果你使用 Linux 版 `frpc`，在 WSL 项目根目录执行：

```bash
cd /root/S/Intelligent-Transportation-System
./frpc -c deploy/frp/frpc.local-ai.toml
```

公网仍可访问：

```text
API:  http://106.54.10.11:15000
前端: http://106.54.10.11:15173
```

## 3. 手机推流

优先使用支持 SRT 的推流 App。建议参数：

```text
协议: SRT caller
地址: 106.54.10.11
端口: 8890
Stream ID: publish:live/mobile_001
Latency: 120ms - 300ms
分辨率: 640x360 或 1280x720
帧率: 15
码率: 800kbps - 1500kbps
编码: H.264
B 帧: 关闭
音频: 关闭或低码率
```

如果推流 App 只支持 RTMP，先用：

```text
rtmp://106.54.10.11:1935/live/mobile_001
```

## 4. 本地 AI 注册设备

复制云端 MediaMTX 配置：

```powershell
Copy-Item edge_member_a\config.tencent_frp.example.json edge_member_a\config.json
```

该配置会把设备流注册为：

```text
rtsp://106.54.10.11:8554/live/mobile_001
```

后端 AI 会从这个 RTSP 地址取帧。

## 5. 前端

复制前端环境变量后重启前端：

```powershell
Copy-Item ui\.env.tencent-frp.example ui\.env
```

前端优先播放：

```text
http://106.54.10.11:8889/live/mobile_001/whep
```

如果 WebRTC 不通，会回退到 HLS：

```text
http://106.54.10.11:8888/live/mobile_001/index.m3u8
```

## 快速判断

- MediaMTX 日志看到 SRT/RTMP publish，说明手机推流成功。
- 前端显示播放协议为 WebRTC，说明低延迟播放成功。
- 后端日志显示成功连接 `rtsp://106.54.10.11:8554/live/mobile_001`，说明本地 AI 取帧成功。
