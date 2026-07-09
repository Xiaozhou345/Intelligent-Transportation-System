# 腾讯云 frp 演示部署方案

本方案用于“本地电脑负责 AI 推理，腾讯云轻量服务器只做公网转发”的演示部署。

## 端口规划

| 用途 | 外部访问地址 | 转发到本地 AI 电脑 |
| --- | --- | --- |
| frp 控制连接 | `106.54.10.11:7000` | `frps` 本机 |
| 后端 API / Socket.IO | `http://106.54.10.11:15000` | `127.0.0.1:5000` |
| 手机 RTMP 推流 | `rtmp://106.54.10.11:1935/live/mobile_001` | `127.0.0.1:1935` |
| 前端 HLS 播放 | `http://106.54.10.11:18888/live/mobile_001/index.m3u8` | `127.0.0.1:8888` |

如果腾讯云公网 IP 变化，把所有 `106.54.10.11` 替换成新的公网 IP。

## 1. 腾讯云服务器

在腾讯云防火墙/安全组放行：

```text
7000
15000
1935
18888
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
后端 API / Socket.IO: 127.0.0.1:5000
RTMP 接收服务: 127.0.0.1:1935
HLS 服务: 127.0.0.1:8888
```

把 `deploy/frp/frpc.local-ai.toml` 中的 token 改成和服务器一致，然后启动：

```bash
./frpc -c frpc.local-ai.toml
```

启动后，公网访问 `106.54.10.11:15000/1935/18888` 会转发到本地 AI 电脑。

## 3. 手机推流

推流地址填写：

```text
rtmp://106.54.10.11:1935/live/mobile_001
```

建议演示参数：

```text
分辨率: 1280x720
帧率: 10-15fps
码率: 1-1.5Mbps
编码: H.264
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
http://106.54.10.11:18888/live/mobile_001/index.m3u8
```

如果 API 能打开，说明 `5000` 转发正常。
如果手机开始推流后 HLS 地址能播放，说明 `1935` 和 `8888` 链路正常。
