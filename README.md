# 云边端协同智慧交通视觉感知系统

## 项目简介

本项目旨在模拟并开发一套"云边端协同"的智慧交通视觉感知系统。系统采用轻量化边端采集、云端高算力分析、独立前端展示的物理分离架构，主要应用于智慧交通沙盘或真实道路场景。

## 系统架构

```
边端（移动设备）
    ↓ SRT/RTMP 推流
腾讯云 MediaMTX（轻量流媒体中转）
    ↓ WHEP/WebRTC 播放流       ↓ RTSP 取帧流
前端（Vue 可视化展示）         本地 AI 电脑（检测/识别/告警）
    ↓ 实时展示 & 告警管理       ↓ WebSocket/API 推送结果
```

### 物理部署
- **边端（移动设备）**: 使用支持 SRT/RTMP 的推流 App 采集摄像头并推到公网服务器
- **腾讯云轻量服务器**: 运行 MediaMTX，只负责接收、转发和封装视频流，不跑 AI 推理
- **本地 AI 电脑**: 从云端 RTSP 拉流取帧，运行车辆检测、车牌识别、道路异常检测等模型
- **前端展示端**: 优先通过 WHEP/WebRTC 播放云端低延迟视频流，并展示本地 AI 推送的分析结果

## 核心功能

### 1. 车牌识别与通行决策
- 已有车牌检测 + LPRNet OCR 的独立测试链路
- 前端已预留车牌识别面板与 `video_overlay.plates` 画框字段
- 当前统一主运行链路以车辆检测、拥堵、违停和道路异常为主，车牌识别尚未稳定并入 `main_server.py`
- **技术方案**: YOLOv11s/m + LPRNet

### 2. 车辆检测与拥堵热力图
- 检测画面中所有车辆目标
- 统计区域车辆密度
- 动态生成拥堵热力图
- 直观显示红绿拥堵状态
- **技术方案**: YOLOv11s/m + OpenCV

### 3. 违停跟踪与告警
- 对进入禁停区域的单一车辆进行持续跟踪（非单纯检测）
- 计算停留时长
- 超时触发告警
- 前端可在视频上叠加禁停区多边形与违停车框
- **技术方案**: YOLOv11s/m + ByteTrack

### 4. 道路异常检测
- 检测路面异常物体（目标未知）
- 即时触发告警并标注位置
- 最终演示采用固定机位，前端提供“初始化背景 / 开始检测 / 重新标定”按钮
- 前端可在视频中叠加异常物品框
- **技术方案**: 手动背景初始化 + MOG2背景建模 + YOLO车辆掩膜 + 道路区域约束 + 时序异常判定

## 技术栈

### 边端采集层
- 视频传输: SRT 推流（推荐） / RTMP 推流（兜底）
- 视频编码: H.264
- 参数: 1280×720 @ 15fps

### 本地 AI 分析层
- 深度学习框架: PyTorch
- 计算机视觉: OpenCV
- 目标检测: YOLOv11
- 车牌识别: LPRNet
- 目标跟踪: ByteTrack
- 异常检测: 手动背景初始化 + MOG2背景建模 + 车辆掩膜 + 道路区域约束 + 时序判定
- 后端框架: Flask + Flask-SocketIO
- 流媒体: 腾讯云 MediaMTX / FFmpeg
- 数据持久化: 当前主链路未接入数据库，前端登录与处置台账使用浏览器本地状态

### 前端展示层
- 前端框架: Vue3
- 数据可视化: ECharts / Canvas
- 实时通信: WebSocket
- 视频播放: WHEP/WebRTC 优先，HLS 兜底
- UI组件库: Element Plus

## 核心技术难点

### 1. 多模型动态切换机制
- GPU/CPU异构计算
- 模型并行常驻，零秒级切换
- 资源分配与负载均衡

### 2. 实时性优化
- 智能跳帧策略（处理1帧，丢弃2-3帧）
- 卡尔曼滤波预测补全帧率
- 异步解耦长耗时任务
- 最新帧缓存策略

### 3. 未知目标异常检测
- 演示前先手动进入背景学习模式，固定机位下学习正常道路背景
- MOG2背景建模提取固定机位下的异常前景
- YOLO车辆掩膜消除正常车辆遮挡干扰
- drivable_area道路分割或道路ROI限制检测范围
- 时序追踪确认持续占用道路的未知异常物体

## 小组分工

### 成员A - 边端采集与传输层
**核心职责**: 解决"视频如何从移动设备到云端"

- 移动端视频采集实现
- 视频传输方案设计与实现（RTMP/HTTP/WebSocket）
- 视频预处理（压缩、帧率控制）
- 与云端的通信协议设计

### 成员B - 本地 AI 分析引擎
**核心职责**: 解决"如何高效处理视频并进行多场景AI分析"

- 视频流/视频段接收服务搭建
- 4个场景的模型选型与集成
- 多模型动态切换机制（技术难点核心）
- 实时性优化策略（跳帧、分段分析）
- 业务逻辑处理（白名单比对、时长计算、告警触发）
- 分析结果数据输出接口

### 成员C - 前端展示与系统集成
**核心职责**: 解决"如何直观展示分析结果并保证系统整体可用"

- 前端可视化界面开发
- 实时视频流展示
- 车牌识别结果展示
- 拥堵热力图动态绘制
- 违停告警列表与时长显示
- 异常检测告警与位置标注
- 与云端的数据交互（WebSocket）
- 系统整体联调与集成测试

## 协作接口

| 接口 | 协议 | 说明 |
|------|------|------|
| **手机 → 腾讯云 MediaMTX** | SRT / RTMP | 原始视频推流 |
| **腾讯云 MediaMTX → 前端** | WHEP/WebRTC / HLS | 低延迟视频播放，HLS 兜底 |
| **腾讯云 MediaMTX → 本地 AI** | RTSP | OpenCV 拉流取帧 |
| **本地 AI 后端 → 前端** | WebSocket / HTTP | 分析结果推送（JSON格式）、场景切换 |

## 项目结构

```
Intelligent-Transportation-System/
├── edge_member_a/           # 设备注册、心跳、云端拉流地址配置
├── cloud/                   # 本地 AI 分析模块（从云端 MediaMTX 拉流）
│   ├── stream_receiver/    # 视频流接收
│   ├── ai_models/          # AI模型
│   │   ├── plate_recognition/
│   │   ├── vehicle_detection/
│   │   ├── vehicle_tracking/
│   │   └── anomaly_detection/
│   ├── business_logic/     # 业务逻辑
│   └── api/                # API接口
├── ui/                     # Vue3前端展示模块
│   ├── components/         # 前端组件
│   ├── utils/              # WebSocket等工具
│   └── dist/               # 构建产物
├── deploy/                 # 腾讯云 MediaMTX / frp 演示配置
│   ├── frp/
│   └── mediamtx/
├── 需求分析文档.md
├── 系统设计报告.md
└── README.md
```

## 快速开始

### 环境要求
- Python 3.8+
- Node.js 16+
- CUDA 11.x (推荐，用于GPU加速)
- FFmpeg / MediaMTX
- frp 0.69.x

### 当前推荐演示链路

本项目当前推荐使用腾讯云轻量服务器承载 MediaMTX，本地电脑继续负责后端 API、前端开发服务和 AI 推理：

```text
手机/平板 SRT 推流 App
  -> 腾讯云 MediaMTX 接收 SRT/RTMP 并输出 WHEP/RTSP/HLS
  -> Vue 前端优先使用 WebRTC/WHEP 播放
  -> 本地 AI 电脑从 rtsp://106.54.10.11:8554/live/mobile_001 取帧
```

RTMP 手机推流 App 容易引入 5 秒以上缓冲，当前推荐改用支持 SRT 的手机推流 App。没有域名时，不再依赖手机浏览器采集摄像头；浏览器前端只负责播放云端 WHEP，不直接播放 `rtmp://` 地址。

完整步骤见 [deploy/cloud-mediamtx-demo.md](./deploy/cloud-mediamtx-demo.md)。旧的“云服务器只做 frp 转发、本地运行 MediaMTX”方案仍可参考 [deploy/tencent-frp-demo.md](./deploy/tencent-frp-demo.md)，但低延迟演示优先使用云端 MediaMTX。

### 1. 腾讯云服务器启动 MediaMTX 与 frps

安全组放行：

```text
7000
15000
15173
1935
8890/UDP
8888
8889
8189/TCP + UDP
8554
```

MediaMTX 使用 [deploy/mediamtx/cloud-mediamtx.yml](./deploy/mediamtx/cloud-mediamtx.yml)：

```bash
cd ~/mediamtx
./mediamtx ./cloud-mediamtx.yml
```

如果还没有安装 MediaMTX，可以把 [deploy/mediamtx](./deploy/mediamtx) 目录上传到服务器并运行：

```bash
cd ~/Intelligent-Transportation-System/deploy/mediamtx
chmod +x ./start-cloud-mediamtx.sh
PUBLIC_IP=106.54.10.11 ./start-cloud-mediamtx.sh
```

进入 frp 服务端目录并启动：

```bash
cd ~/frp_0.69.1_linux_amd64
./frps -c frps.toml
```

`frps.toml` 示例见 [deploy/frp/frps.toml](./deploy/frp/frps.toml)。

### 2. 本地 AI 电脑启动后端与前端

本地电脑不再启动 MediaMTX，只保留业务服务：

```text
后端 API / Socket.IO: 127.0.0.1:5000
前端开发服务: 127.0.0.1:5173
```

启动后可以用下面命令检查端口：

```powershell
Get-NetTCPConnection -LocalPort 5000,5173
```

### 3. 本地 AI 电脑启动 frpc

配置见 [deploy/frp/frpc.local-ai.toml](./deploy/frp/frpc.local-ai.toml)。启动：

```powershell
.\frpc.exe -c deploy\frp\frpc.local-ai.toml
```

启动成功后，公网地址会转发到本地：

```text
API:  http://106.54.10.11:15000
前端: http://106.54.10.11:15173
```

### 4. 手机或平板推流

推荐使用支持 SRT 的手机推流 App：

```text
srt://106.54.10.11:8890?streamid=publish:live/mobile_001&latency=200
```

如果 App 只支持 RTMP，使用兜底地址：

```text
rtmp://106.54.10.11:1935/live/mobile_001
```

手机浏览器需要 HTTPS 才能稳定授权摄像头。若暂时没有 HTTPS，可继续用电脑 FFmpeg 低延迟推流做兜底，或把手机作为电脑摄像头后由电脑推流。

### 5. 边端注册与心跳

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

### 6. 前端启动

复制公网演示环境变量：

```powershell
Copy-Item ui\.env.tencent-frp.example ui\.env
```

启动开发服务：

```powershell
cd ui
npm install
npm run dev
```

构建生产包：

```powershell
cd ui
npm run build
```

### 快速验证

按顺序访问：

```text
http://106.54.10.11:15000/api/health
http://106.54.10.11:8889/live/mobile_001/whep
http://106.54.10.11:8888/live/mobile_001/index.m3u8
rtsp://106.54.10.11:8554/live/mobile_001
```

如果 API 能打开，说明 `5000` 转发正常。
如果手机开始推流后前端 WebRTC 有画面，说明 `8889` 和 `8189/UDP` 链路正常。
如果 WebRTC 不通但 HLS 地址能打开，前端会自动回退到 HLS，但延迟会更高。

### 生产环境安全配置

默认配置用于本地/沙盘演示。将 API 暴露到公网前，至少设置：

```powershell
$env:ITS_SECRET_KEY = "一个长随机字符串"
$env:ITS_ALLOWED_ORIGINS = "https://your-frontend.example.com"
$env:ITS_MAX_UPLOAD_MB = "100"
$env:ITS_DB_PASSWORD = "你的MySQL密码"  # 仅在启用MySQL时需要
$env:ITS_API_TOKEN = "一个独立的长随机API令牌"
```

`ITS_ALLOWED_ORIGINS` 可以是英文逗号分隔的多个前端地址。同时应替换 `deploy/frp/*.toml`
中的演示令牌，并保证 frps 与 frpc 使用相同的新令牌。
API 令牌启用后，边端 JSON 配置需增加 `"api_token": "..."`，前端构建环境需设置
`VITE_API_TOKEN=...`。不设置 `ITS_API_TOKEN` 时保持原有沙盘演示行为。

常见问题：

- `./frps: No such file or directory`：先 `cd ~/frp_0.69.1_linux_amd64`，再运行 `./frps -c frps.toml`。
- 公网 HLS 返回错误：通常是云端 MediaMTX 没启动，或手机还没有推流。
- 手机浏览器发布页打不开摄像头：检查是否通过 HTTPS 访问；没有域名时建议直接使用 SRT 推流 App，绕过浏览器摄像头 HTTPS 限制。
- 前端无画面但手机已推流：优先看云端 MediaMTX 日志里是否出现 SRT/RTMP 发布和 WebRTC 读取；再检查 `8189/UDP` 是否放行。
- `rtsp://106.54.10.11:8554/live/mobile_001` 无法打开：先确认云端 MediaMTX 已启动、手机已推流、`8554/TCP` 已放行。

更完整的腾讯云 frp 演示说明见 [deploy/tencent-frp-demo.md](./deploy/tencent-frp-demo.md)。
如果要让手机和电脑不在同一网络下使用浏览器摄像头推流，请按 [deploy/https-webrtc-demo.md](./deploy/https-webrtc-demo.md) 配置 HTTPS 入口。

### 前端依赖

```bash
cd ui
npm install
```

## 文档

- [需求分析文档](./需求分析文档.md)
- [系统设计报告](./系统设计报告.md)

## 当前状态与待完善

### 已打通
- [x] 手机/平板到云端 MediaMTX 的 SRT/RTMP 推流链路
- [x] 云端 MediaMTX 输出 WHEP/WebRTC、HLS、RTSP
- [x] 本地 AI 电脑从云端 RTSP 拉流取帧
- [x] Flask + Socket.IO 后端向前端推送分析结果
- [x] 前端实时播放视频并展示车辆框、禁停区、违停车框、异常物品框、事件流、告警和统计面板
- [x] YOLO 车辆检测、ByteTrack 违停跟踪、拥堵统计、道路异常检测基础链路
- [x] 车牌检测 + LPRNet OCR 独立测试链路（主链路暂预留 `video_overlay.plates` 字段）
- [x] 基础 smoke test 入口：`python tools/smoke_test.py`
- [x] 无数据库前端管理能力：本地登录角色、告警处置台账、事件导出、演示检查清单
- [x] 道路异常检测支持“初始化背景 / 开始检测 / 重新标定”的固定机位演示流程

### 待完善
- [ ] 待车牌模型稳定后，再将车牌识别并入统一主服务实时流
- [ ] 将 smoke test 扩展为 pytest/CI 回归套件
- [ ] 按实际演示环境沉淀 `.env`、云端 IP 和端口配置模板
- [ ] 继续优化三端联调延迟、弱网恢复和异常日志

## 应用场景

- 智慧交通沙盘
- 校内外道路交通监控

## License

待定

## 团队

3人小组开发项目
