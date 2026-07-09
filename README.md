# 云边端协同智慧交通视觉感知系统

## 项目简介

本项目旨在模拟并开发一套"云边端协同"的智慧交通视觉感知系统。系统采用轻量化边端采集、云端高算力分析、独立前端展示的物理分离架构，主要应用于智慧交通沙盘或真实道路场景。

## 系统架构

```
边端（移动设备）
    ↓ 视频采集 & RTMP推流
云端（电脑A - AI分析服务器）
    ↓ 视频接收 & AI推理 & 业务逻辑
前端（电脑B - 可视化展示）
    ↓ 实时展示 & 告警管理
```

### 物理部署
- **边端（移动设备）**: 实时视频流/视频段采集与网络推流
- **云端（电脑A）**: 接收视频流，提供AI算力，运行多模型智能调度
- **前端（电脑B）**: 接收分析结果，进行大屏可视化渲染与告警展示

## 核心功能

### 1. 车牌识别与通行决策
- 实时检测车辆并识别车牌
- 与本地白名单库比对
- 输出道闸开放决策
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
- **技术方案**: YOLOv11s/m + ByteTrack

### 4. 道路异常检测
- 检测路面异常物体（目标未知）
- 即时触发告警并标注位置
- 显示受影响车道拓扑图
- **技术方案**: MOG2背景建模 + YOLO车辆掩膜 + drivable_area道路约束 + 时序异常判定

## 技术栈

### 边端采集层
- 视频传输: RTMP推流（主） / HTTP分段传输（备用）
- 视频编码: H.264
- 参数: 1280×720 @ 15fps

### 云端AI分析层
- 深度学习框架: PyTorch / TensorFlow
- 计算机视觉: OpenCV
- 目标检测: YOLOv11
- 车牌识别: LPRNet
- 目标跟踪: ByteTrack
- 异常检测: MOG2背景建模 + 车辆掩膜 + 道路区域约束 + 时序判定
- 后端框架: Flask / FastAPI / Django
- 流媒体: FFmpeg / RTMP服务
- 数据库: SQLite / MySQL

### 前端展示层
- 前端框架: Vue3 / React
- 数据可视化: ECharts / Canvas / D3.js
- 实时通信: WebSocket
- UI组件库: Element UI / Ant Design

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

### 成员B - 云端AI分析引擎
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
| **边端 → 云端** | RTMP / HTTP | 视频流传输、设备注册 |
| **云端 → 前端** | WebSocket / HTTP | 分析结果推送（JSON格式） |
| **前端 ↔ 云端** | WebSocket | 双向控制信令、场景切换 |

## 项目结构

```
Intelligent-Transportation-System/
├── edge_member_a/           # 边端注册、心跳、RTMP联调脚本
├── cloud/                   # 云端AI分析模块
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
├── deploy/                 # 腾讯云frp公网转发演示配置
│   └── frp/
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

### 当前演示链路

本项目当前使用腾讯云轻量服务器做公网中转，本地电脑负责 AI 推理和流媒体服务：

```text
手机/平板 RTMP 推流
  -> 腾讯云 106.54.10.11:1935
  -> frp 转发到本地 AI 电脑 127.0.0.1:1935
  -> MediaMTX 生成 HLS 127.0.0.1:8888
  -> frp 转发到 http://106.54.10.11:18888/live/mobile_001/index.m3u8
  -> Vue 前端使用 hls.js 播放
```

浏览器不能直接播放 RTMP，所以前端播放地址是 HLS 的 `.m3u8`，不是 `rtmp://` 地址。

### 1. 腾讯云服务器启动 frps

安全组放行：

```text
7000
15000
1935
18888
```

进入 frp 服务端目录并启动：

```bash
cd ~/frp_0.69.1_linux_amd64
./frps -c frps.toml
```

`frps.toml` 示例见 [deploy/frp/frps.toml](./deploy/frp/frps.toml)。

### 2. 本地 AI 电脑启动 RTMP/HLS 与后端

先确保本地有三个服务：

```text
后端 API / Socket.IO: 127.0.0.1:5000
RTMP 接收服务: 127.0.0.1:1935
HLS 服务: 127.0.0.1:8888
```

MediaMTX 负责接收手机 RTMP，并生成 HLS。启动后可以用下面命令检查端口：

```powershell
Get-NetTCPConnection -LocalPort 1935,8888,5000
```

### 3. 本地 AI 电脑启动 frpc

配置见 [deploy/frp/frpc.local-ai.toml](./deploy/frp/frpc.local-ai.toml)。启动：

```powershell
.\frpc.exe -c deploy\frp\frpc.local-ai.toml
```

启动成功后，公网地址会转发到本地：

```text
API:  http://106.54.10.11:15000
RTMP: rtmp://106.54.10.11:1935/live/mobile_001
HLS:  http://106.54.10.11:18888/live/mobile_001/index.m3u8
```

### 4. 手机或平板推流

在 Larix Broadcaster 或其他 RTMP 推流软件中填写：

```text
rtmp://106.54.10.11:1935/live/mobile_001
```

推荐参数：

```text
分辨率: 1280x720
帧率: 10-15fps
码率: 1-1.5Mbps
编码: H.264
```

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
http://106.54.10.11:18888/live/mobile_001/index.m3u8
```

如果 API 能打开，说明 `5000` 转发正常。
如果手机开始推流后 HLS 地址能打开，说明 `1935` 和 `8888` 链路正常。

常见问题：

- `./frps: No such file or directory`：先 `cd ~/frp_0.69.1_linux_amd64`，再运行 `./frps -c frps.toml`。
- 公网 HLS 返回 `502`：通常是本地 MediaMTX 没启动，或 `frpc` 没连上 `frps`。
- 前端无画面但手机已推流：先直接打开 HLS 地址确认 `.m3u8` 是否可访问；前端只播放 HLS，不播放 RTMP。
- `127.0.0.1:1935` 连接拒绝：本地 RTMP 服务未监听，先启动 MediaMTX。

更完整的腾讯云 frp 演示说明见 [deploy/tencent-frp-demo.md](./deploy/tencent-frp-demo.md)。

### 前端依赖

```bash
cd ui
npm install
```

## 文档

- [需求分析文档](./需求分析文档.md)
- [系统设计报告](./系统设计报告.md)

## 实现计划

### 第一阶段：基础链路打通
- [ ] 边端到云端的视频传输
- [ ] 云端RTMP接收服务
- [ ] 验证视频帧稳定读取

### 第二阶段：云端AI分析实现
- [ ] YOLO车辆检测
- [ ] 车牌识别与白名单比对
- [ ] ByteTrack车辆跟踪
- [ ] MOG2+车辆掩膜+道路约束+时序异常检测

### 第三阶段：前端展示实现
- [ ] 实时视频画面展示
- [ ] 车牌识别结果展示
- [ ] 拥堵热力图绘制
- [ ] 违停告警展示
- [ ] 异常检测告警展示

### 第四阶段：系统联调与优化
- [ ] 三端联调
- [ ] 性能优化
- [ ] 测试与演示

## 应用场景

- 智慧交通沙盘
- 校内外道路交通监控

## License

待定

## 团队

3人小组开发项目
