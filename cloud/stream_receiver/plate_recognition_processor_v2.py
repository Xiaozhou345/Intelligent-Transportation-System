"""
实时车牌识别视频处理引擎 - 针对沙盘小车优化版本
"""
import cv2
import sys
import os
import threading
import time
from datetime import datetime
from queue import Queue
import numpy as np

# 添加AI模型路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../ai_models')

from vehicle_detection.detector import VehicleDetector


class PlateRecognitionProcessor:
    """车牌识别处理器 - 沙盘优化版"""

    def __init__(self, device_manager):
        """
        初始化处理器

        Args:
            device_manager: 设备管理器实例
        """
        self.device_manager = device_manager
        self.active_streams = {}
        self.stop_flags = {}
        self.results_queue = Queue()

        # 初始化AI模型
        print("=" * 60)
        print("正在初始化AI模型（沙盘优化版）...")
        print("=" * 60)

        try:
            base_path = os.path.dirname(os.path.abspath(__file__))
            yolo_path = os.path.join(base_path, '../ai_models/vehicle_detection/yolo11s.pt')

            # 降低置信度阈值，适应小目标
            self.vehicle_detector = VehicleDetector(model_path=yolo_path, conf_threshold=0.25)

            print("=" * 60)
            print("✅ AI模型加载完成！")
            print("   配置: 沙盘模式 - 低阈值检测")
            print("=" * 60)

        except Exception as e:
            print(f"❌ AI模型加载失败: {str(e)}")
            raise

    def start_processing(self, device_id, stream_url):
        """启动视频流处理"""
        if device_id in self.active_streams:
            print(f"设备 {device_id} 已在处理中")
            return False

        stop_event = threading.Event()
        self.stop_flags[device_id] = stop_event

        thread = threading.Thread(
            target=self._process_stream,
            args=(device_id, stream_url, stop_event),
            daemon=True
        )
        thread.start()
        self.active_streams[device_id] = thread

        print(f"🚀 开始处理设备 {device_id} 的视频流")
        print(f"   流地址: {stream_url}")
        return True

    def stop_processing(self, device_id):
        """停止视频流处理"""
        if device_id not in self.active_streams:
            return False

        self.stop_flags[device_id].set()
        self.active_streams[device_id].join(timeout=5)

        del self.active_streams[device_id]
        del self.stop_flags[device_id]

        print(f"⏹️  停止处理设备 {device_id} 的视频流")
        return True

    def _process_stream(self, device_id, stream_url, stop_event):
        """视频流处理主循环"""
        cap = None
        frame_count = 0
        process_interval = 10  # 每10帧处理一次

        try:
            print(f"📡 正在连接视频流: {stream_url}")
            cap = cv2.VideoCapture(stream_url)

            if not cap.isOpened():
                print(f"❌ 无法打开视频流: {stream_url}")
                return

            print(f"✅ 成功连接视频流: {device_id}")
            print(f"   开始AI分析（沙盘模式）...")

            while not stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    time.sleep(0.1)
                    continue

                frame_count += 1

                # 每N帧处理一次
                if frame_count % process_interval != 0:
                    continue

                # 执行车辆检测
                self._detect_vehicles(device_id, frame, frame_count)

        except Exception as e:
            print(f"❌ 视频流处理异常 {device_id}: {str(e)}")

        finally:
            if cap:
                cap.release()
            print(f"⏹️  视频流处理结束: {device_id}")

    def _detect_vehicles(self, device_id, frame, frame_count):
        """执行车辆检测并识别车牌"""
        try:
            # 检测车辆
            vehicles = self.vehicle_detector.detect(frame)

            if not vehicles:
                # 每100帧报告一次
                if frame_count % 100 == 0:
                    print(f"⏳ 帧 {frame_count}: 未检测到车辆")
                return

            # 找到车辆了！
            print("\n" + "=" * 60)
            print(f"🚗 检测到 {len(vehicles)} 辆车辆！")
            print("=" * 60)

            for idx, vehicle in enumerate(vehicles):
                bbox = vehicle['bbox']
                x1, y1, x2, y2 = bbox

                # 裁剪车辆区域
                vehicle_img = frame[y1:y2, x1:x2]

                if vehicle_img.size == 0:
                    continue

                # 尝试提取车牌号
                plate_number = self._extract_plate_from_image(vehicle_img)

                # 生成检测结果
                result = {
                    'event_type': 'vehicle_detection',
                    'timestamp': datetime.now().isoformat(),
                    'device_id': device_id,
                    'data': {
                        'vehicle_id': idx + 1,
                        'vehicle_type': vehicle['class_name'],
                        'confidence': vehicle['confidence'],
                        'plate_number': plate_number if plate_number else '未识别',
                        'is_in_whitelist': False,
                        'decision': 'unknown'
                    },
                    'bbox': bbox,
                    'status': 'detected'
                }

                # 保存结果
                self.results_queue.put(result)

                # 打印检测信息
                print(f"   车辆 #{idx + 1}:")
                print(f"      类型: {vehicle['class_name']}")
                print(f"      置信度: {vehicle['confidence']:.2f}")
                print(f"      位置: {bbox}")
                print(f"      车牌: {plate_number if plate_number else '未识别'}")

            print("=" * 60)

        except Exception as e:
            print(f"⚠️  车辆检测处理异常: {str(e)}")

    def _extract_plate_from_image(self, vehicle_img):
        """
        从车辆图像中提取车牌号
        使用OCR或模板匹配（简化版）
        """
        try:
            # 转灰度
            gray = cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2GRAY)

            # 查找蓝色区域（中国车牌通常是蓝底）
            hsv = cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2HSV)

            # 蓝色范围
            lower_blue = np.array([100, 50, 50])
            upper_blue = np.array([130, 255, 255])

            mask = cv2.inRange(hsv, lower_blue, upper_blue)

            # 查找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if contours:
                # 找最大的蓝色区域
                largest_contour = max(contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest_contour)

                # 宽高比检查（车牌通常是长方形）
                aspect_ratio = w / float(h) if h > 0 else 0

                if 2.0 < aspect_ratio < 5.0 and w > 20 and h > 5:
                    # 可能是车牌区域
                    plate_region = vehicle_img[y:y+h, x:x+w]
                    # 这里简化处理，返回检测到车牌
                    return "检测到车牌区域"

            return None

        except:
            return None

    def get_latest_results(self, max_count=10):
        """获取最新的识别结果"""
        results = []
        while not self.results_queue.empty() and len(results) < max_count:
            results.append(self.results_queue.get())
        return results


if __name__ == '__main__':
    from device_manager import DeviceManager

    device_manager = DeviceManager()
    processor = PlateRecognitionProcessor(device_manager)

    print("\n车牌识别处理器测试完成")
