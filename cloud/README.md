# 本地 AI 分析引擎

当前演示部署中，腾讯云轻量服务器只运行 MediaMTX 做视频流中转；本目录中的 AI 分析服务运行在本地 AI 电脑上，通过云端 MediaMTX 的 RTSP 地址拉流取帧，并通过 Flask-SocketIO 向前端推送分析结果。

## 模块结构

```
cloud/
├── ai_models/              # AI模型
│   ├── vehicle_detection/  # 车辆检测 (YOLOv11)
│   ├── plate_recognition/  # 车牌识别 (LPRNet)
│   ├── vehicle_tracking/   # 车辆跟踪 (ByteTrack)
│   └── anomaly_detection/  # 异常检测 (DINOv2参考特征+车辆掩膜+道路约束+时序判定)
├── stream_receiver/        # 视频流接收
├── business_logic/         # 业务逻辑
└── api/                    # API接口
```

## 安装依赖

```bash
cd cloud
pip install -r requirements.txt
```

## 模型权重

### 1. YOLOv11s
- 文件名: `yolo11s.pt`
- 大小: ~19MB
- 下载: https://github.com/ultralytics/assets/releases
- 位置: `cloud/ai_models/vehicle_detection/yolo11s.pt`

### 2. LPRNet
- 文件名: `Final_LPRNet_model.pth`
- 大小: ~1.8MB
- 下载: https://github.com/sirius-ai/LPRNet_Pytorch
- 位置: `cloud/ai_models/plate_recognition/Final_LPRNet_model.pth`

### 3. ByteTrack
- ByteTrack 无需额外权重文件

### 4. 沙盘道路分割模型（可选道路约束）
- 文件名: `sandbox_drivable_best.pt`
- 训练数据: `data/sandbox_drivable`
- 训练脚本: `cloud/ai_models/anomaly_detection/train_drivable_segmenter.py`
- 位置: `cloud/ai_models/anomaly_detection/sandbox_drivable_best.pt`

### 5. DINOv2-S 道路异常特征模型
- 模型名: `dinov2_vits14_reg`
- 大小: 约 84MB
- 首次启动由 PyTorch Hub 自动下载到 `.tools/model-cache`，后续启动复用缓存
- 无网络时可设置 `ITS_ANOMALY_BACKEND=mog2` 回退旧后端

## 快速测试

### 测试车辆检测
```bash
cd cloud/ai_models/vehicle_detection
python3 detector.py
```

### 测试车牌识别
```bash
cd cloud/ai_models/plate_recognition
python3 plate_recognizer.py
```

### 测试车辆跟踪
```bash
cd cloud/ai_models/vehicle_tracking
python3 vehicle_tracker.py
```

### 测试异常检测
```bash
python -m unittest cloud.stream_receiver.test_anomaly_processor
python tools/evaluate_dinov2_reference.py --max-pairs 10
```

### 训练沙盘道路分割模型
```powershell
python cloud\ai_models\anomaly_detection\train_drivable_segmenter.py --data data\sandbox_drivable\data.yaml --model yolo11n-seg.pt --epochs 80 --imgsz 640 --batch 4
```

### 测试云端异常检测处理器
```bash
cd ..
python cloud/stream_receiver/test_anomaly_processor.py
```

调度层复用同一帧时，可直接调用：
```python
from cloud.stream_receiver.anomaly_processor import RoadAnomalyProcessor

anomaly_processor = RoadAnomalyProcessor(
    drivable_model_path="cloud/ai_models/anomaly_detection/sandbox_drivable_best.pt"
)
events = anomaly_processor.process_frame(
    device_id="mobile_001",
    frame=frame,
    vehicle_bboxes=vehicle_bboxes
)
```

`vehicle_bboxes` 来自车辆检测模型，用于把正常车辆区域从异常候选区域中排除，避免影响车牌识别或其他模型的独立逻辑。

实时沙盘演示必须按以下顺序标定：

1. 固定手机或摄像头，之后不要移动、变焦或切换横竖屏。
2. 最好保持异物检测区内道路为空再点击“初始化背景”；有车辆时会逐位置遮罩车辆区域并继续学习，仅在有效道路几乎全部被遮挡时跳过该帧。
3. 等待至少 20 个有效背景帧并进入检测模式，再放置纸箱、石块等异物。
4. 只要镜头位置、焦距或照明发生明显变化，就重新初始化背景。

DINOv2检测器只上报相对正常模板持续出现的特征变化；背景标定和检测阶段都会遮罩车辆区域，少量车辆不再导致整帧跳过。连续出现大面积全局变化时，系统会停止告警并返回背景学习，避免镜头移动造成叠框刷屏。需要临时回退旧方案时，设置 `ITS_ANOMALY_BACKEND=mog2`。

## 四大业务场景

### 1. 车牌识别与通行决策
- 模型: YOLOv11 + LPRNet
- 功能: 检测车牌并识别字符，与白名单比对
- 输出: 车牌号、是否在白名单、通行决策

### 2. 车辆检测与拥堵热力图
- 模型: YOLOv11
- 功能: 检测所有车辆，统计区域密度
- 输出: 车辆数量、拥堵等级、热力图数据

### 3. 违停跟踪与告警
- 模型: YOLOv11 + ByteTrack
- 功能: 跟踪禁停区域车辆，计算停留时长
- 输出: 车辆轨迹、停留时长、违停告警

- 模型: DINOv2正常模板特征对比 + YOLO车辆掩膜 + 道路区域约束 + 时序异常判定
- 功能: 固定机位下检测路面异常物体（掉落物、障碍物）
- 输出: 异常物体位置、面积、告警状态

## 开发状态

- [x] YOLOv11车辆检测模块
- [x] LPRNet车牌识别模块
- [x] ByteTrack车辆跟踪模块
- [x] DINOv2参考特征+车辆掩膜+道路约束+时序异常检测模块（保留MOG2回退）
- [x] 道路异常检测支持前端手动“初始化背景 / 开始检测 / 重新标定”
- [x] 视频流接收服务（从云端 MediaMTX 的 RTSP 地址拉流）
- [x] 场景切换与共享车辆检测调度
- [x] 拥堵统计、违停跟踪、道路异常业务逻辑
- [x] Flask HTTP API + Socket.IO 实时推送
- [x] 独立车牌识别测试链路（主服务 `video_overlay.plates` 字段预留）
- [x] 基础 smoke test 入口：`python tools/smoke_test.py`
- [ ] 待车牌模型稳定后，将车牌识别并入统一主服务实时流
- [ ] pytest/CI 回归套件
