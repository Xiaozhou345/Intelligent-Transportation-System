"""
车辆检测模块
使用YOLOv11进行车辆目标检测
"""
from ultralytics import YOLO
import cv2
import numpy as np
import os


class VehicleDetector:
    """车辆检测器"""
    
    # COCO 预训练模型中的车辆类别名称；自训练沙盘模型使用 vehicle 类别
    VEHICLE_NAMES = {'car', 'motorcycle', 'bus', 'truck', 'vehicle'}
    
    def __init__(self, model_path='yolo11s.pt', conf_threshold=0.5):
        """
        初始化车辆检测器

        Args:
            model_path: YOLO模型权重路径
            conf_threshold: 置信度阈值
        """
        print(f"正在加载YOLOv11模型: {model_path}")
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold

        # 自动选择GPU或CPU
        import torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.imgsz = int(os.getenv('ITS_VEHICLE_IMGSZ', '640'))
        self.use_half = (
            self.device == 'cuda'
            and os.getenv('ITS_ENABLE_FP16', 'true').lower() == 'true'
        )
        if self.device == 'cuda':
            torch.backends.cudnn.benchmark = True
        self.model.to(self.device)
        print(
            f"车辆检测器初始化完成 "
            f"(设备: {self.device}, imgsz: {self.imgsz}, FP16: {self.use_half})"
        )
    
    def detect(self, frame):
        """
        检测视频帧中的车辆
        
        Args:
            frame: 输入图像帧 (numpy array)
            
        Returns:
            list: 检测结果列表，每个元素为字典:
                {
                    'bbox': [x1, y1, x2, y2],
                    'class_id': int,
                    'class_name': str,
                    'confidence': float
                }
        """
        # 使用YOLO进行推理
        results = self.model.predict(
            source=frame,
            conf=self.conf_threshold,
            imgsz=self.imgsz,
            device=self.device,
            half=self.use_half,
            verbose=False,
        )
        
        # 解析检测结果
        detections = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            class_name = self.model.names.get(cls_id, str(cls_id))

            # 只保留车辆类别：兼容 COCO 预训练模型和沙盘自训练模型
            if class_name in self.VEHICLE_NAMES:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])

                detections.append({
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'class_id': cls_id,
                    'class_name': class_name,
                    'confidence': conf
                })
        
        return detections
    
    def detect_all_objects(self, frame):
        """
        检测所有目标（不限车辆）
        
        Args:
            frame: 输入图像帧
            
        Returns:
            list: 所有检测结果
        """
        results = self.model.predict(
            source=frame,
            conf=self.conf_threshold,
            imgsz=self.imgsz,
            device=self.device,
            half=self.use_half,
            verbose=False,
        )
        
        detections = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            conf = float(box.conf[0])
            
            detections.append({
                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                'class_id': cls_id,
                'class_name': self.model.names[cls_id],
                'confidence': conf
            })
        
        return detections


if __name__ == '__main__':
    # 测试代码
    detector = VehicleDetector()
    
    # 使用测试图片
    test_img = cv2.imread('/root/model_test/bus.jpg')
    if test_img is not None:
        results = detector.detect(test_img)
        print(f"\n检测到 {len(results)} 辆车辆:")
        for r in results:
            print(f"  - {r['class_name']}: {r['confidence']:.2f} at {r['bbox']}")
    else:
        print("测试图片未找到")
