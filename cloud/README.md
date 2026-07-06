# 云端AI分析引擎

云端AI分析模块，负责接收边端视频流并进行多场景AI分析。

## 模块结构

```
cloud/
├── ai_models/              # AI模型
│   ├── vehicle_detection/  # 车辆检测 (YOLOv11)
│   ├── plate_recognition/  # 车牌识别 (LPRNet)
│   ├── vehicle_tracking/   # 车辆跟踪 (ByteTrack)
│   └── anomaly_detection/  # 异常检测 (MOG2)
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

### 3. ByteTrack & MOG2
- 无需额外权重文件

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
cd cloud/ai_models/anomaly_detection
python3 anomaly_detector.py
```

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

### 4. 道路异常检测
- 模型: MOG2 + YOLOv11动态掩膜
- 功能: 检测路面异常物体（掉落物、障碍物）
- 输出: 异常物体位置、面积、告警状态

## 开发状态

- [x] YOLOv11车辆检测模块
- [x] LPRNet车牌识别模块
- [x] ByteTrack车辆跟踪模块
- [x] MOG2道路异常检测模块
- [ ] 视频流接收服务
- [ ] 多模型动态调度
- [ ] 业务逻辑处理
- [ ] API接口服务
