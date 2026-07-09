"""
车牌检测模块
使用YOLOv11进行车牌区域检测
"""
from ultralytics import YOLO


class PlateDetector:
    """车牌检测器"""

    PLATE_NAMES = {'plate'}

    def __init__(self, model_path='sandbox_plate_best.pt', conf_threshold=0.2):
        """
        初始化车牌检测器

        Args:
            model_path: YOLO车牌检测模型权重路径
            conf_threshold: 置信度阈值
        """
        print(f"正在加载车牌YOLO模型: {model_path}")
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold

        # 自动选择GPU或CPU
        import torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model.to(self.device)
        print(f"车牌检测器初始化完成 (设备: {self.device}, conf: {self.conf_threshold})")

    def detect(self, frame):
        """
        检测图像中的车牌区域

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
        results = self.model.predict(source=frame, conf=self.conf_threshold, verbose=False)

        detections = []
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            class_name = self.model.names.get(cls_id, str(cls_id))

            if class_name in self.PLATE_NAMES:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                detections.append({
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'class_id': cls_id,
                    'class_name': class_name,
                    'confidence': conf
                })

        return detections
