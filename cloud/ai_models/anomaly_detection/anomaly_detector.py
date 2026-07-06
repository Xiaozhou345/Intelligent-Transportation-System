"""
道路异常检测模块
使用MOG2背景建模检测路面异常物体
"""
import cv2
import numpy as np


class AnomalyDetector:
    """道路异常检测器"""

    def __init__(self, history=500, var_threshold=16, detect_shadows=False):
        """
        初始化异常检测器

        Args:
            history: 背景建模的历史帧数
            var_threshold: 方差阈值
            detect_shadows: 是否检测阴影
        """
        # MOG2背景建模器
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=var_threshold,
            detectShadows=detect_shadows
        )

        # 异常物体参数
        self.min_area = 500  # 最小异常物体面积
        self.static_frames_threshold = 15  # 静止帧数阈值
        self.anomaly_id_counter = 0

        # 跟踪的异常物体
        self.tracked_anomalies = {}

        print("道路异常检测器初始化完成")

    def update_background(self, frame):
        """
        更新背景模型（用于初始化）

        Args:
            frame: 输入图像帧
        """
        self.bg_subtractor.apply(frame)

    def detect(self, frame, vehicle_bboxes=None):
        """
        检测道路异常物体

        Args:
            frame: 输入图像帧 (numpy array, BGR格式)
            vehicle_bboxes: 正常车辆的bbox列表 [[x1,y1,x2,y2], ...]
                           用于从前景中排除正常车辆

        Returns:
            list: 异常检测结果列表，每个元素为字典:
                {
                    'anomaly_id': int,
                    'bbox': [x1, y1, x2, y2],
                    'center': [cx, cy],
                    'area': int,
                    'static_frames': int,  # 静止帧数
                    'status': 'warning' or 'normal'
                }
        """
        # 应用背景建模
        fg_mask = self.bg_subtractor.apply(frame)

        # 形态学操作去噪
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        # 如果提供了车辆bbox，从前景中移除车辆区域
        if vehicle_bboxes:
            vehicle_mask = np.zeros_like(fg_mask)
            for bbox in vehicle_bboxes:
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(vehicle_mask, (x1, y1), (x2, y2), 255, -1)
            # 从前景中减去车辆区域
            fg_mask = cv2.bitwise_and(fg_mask, cv2.bitwise_not(vehicle_mask))

        # 查找连通域
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 当前帧检测到的异常
        current_anomalies = []

        for contour in contours:
            area = cv2.contourArea(contour)

            # 过滤小面积物体
            if area < self.min_area:
                continue

            # 获取边界框
            x, y, w, h = cv2.boundingRect(contour)
            bbox = [x, y, x + w, y + h]
            center = [x + w // 2, y + h // 2]

            # 查找是否是已跟踪的异常
            matched = False
            for anomaly_id, anomaly_info in self.tracked_anomalies.items():
                prev_center = anomaly_info['center']
                # 计算中心距离
                dist = np.sqrt((center[0] - prev_center[0]) ** 2 +
                             (center[1] - prev_center[1]) ** 2)

                # 如果距离很近，认为是同一个异常
                if dist < 50:
                    matched = True
                    # 更新静止帧数
                    anomaly_info['static_frames'] += 1
                    anomaly_info['center'] = center
                    anomaly_info['bbox'] = bbox
                    anomaly_info['area'] = int(area)

                    # 判断是否触发告警
                    if anomaly_info['static_frames'] >= self.static_frames_threshold:
                        anomaly_info['status'] = 'warning'
                    else:
                        anomaly_info['status'] = 'normal'

                    current_anomalies.append({
                        'anomaly_id': anomaly_id,
                        'bbox': bbox,
                        'center': center,
                        'area': int(area),
                        'static_frames': anomaly_info['static_frames'],
                        'status': anomaly_info['status']
                    })
                    break

            # 如果是新异常，添加到跟踪列表
            if not matched:
                anomaly_id = self.anomaly_id_counter
                self.anomaly_id_counter += 1

                self.tracked_anomalies[anomaly_id] = {
                    'center': center,
                    'bbox': bbox,
                    'area': int(area),
                    'static_frames': 1,
                    'status': 'normal'
                }

                current_anomalies.append({
                    'anomaly_id': anomaly_id,
                    'bbox': bbox,
                    'center': center,
                    'area': int(area),
                    'static_frames': 1,
                    'status': 'normal'
                })

        # 清理消失的异常（未在当前帧检测到）
        current_ids = [a['anomaly_id'] for a in current_anomalies]
        disappeared_ids = [aid for aid in self.tracked_anomalies.keys() if aid not in current_ids]
        for aid in disappeared_ids:
            del self.tracked_anomalies[aid]

        return current_anomalies

    def reset(self):
        """重置检测器"""
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2()
        self.tracked_anomalies = {}
        self.anomaly_id_counter = 0


if __name__ == '__main__':
    # 测试代码
    detector = AnomalyDetector()

    # 创建测试视频帧
    print("\n模拟道路场景...")

    # 初始化背景（纯色背景）
    for i in range(30):
        bg_frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
        detector.update_background(bg_frame)

    print("背景模型初始化完成")

    # 模拟有异常物体的帧
    test_frame = np.ones((480, 640, 3), dtype=np.uint8) * 100

    # 添加一个异常物体（如石头、纸箱）
    cv2.rectangle(test_frame, (200, 150), (280, 200), (50, 50, 50), -1)

    # 模拟车辆bbox（正常车辆不应该被检测为异常）
    vehicle_bboxes = [
        [100, 300, 200, 400],
        [400, 320, 500, 420]
    ]

    # 在帧上画出车辆（模拟）
    for bbox in vehicle_bboxes:
        cv2.rectangle(test_frame, (bbox[0], bbox[1]), (bbox[2], bbox[3]),
                     (255, 255, 255), -1)

    print("\n连续检测15帧...")
    for frame_id in range(15):
        results = detector.detect(test_frame, vehicle_bboxes)

        if results:
            print(f"第{frame_id + 1}帧:")
            for r in results:
                print(f"  异常ID {r['anomaly_id']}: 面积={r['area']}, "
                      f"静止帧数={r['static_frames']}, 状态={r['status']}")

    print("\n道路异常检测器测试完成")
