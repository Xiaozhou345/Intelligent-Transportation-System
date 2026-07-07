"""
实时车牌识别视频处理引擎
集成YOLO车辆检测 + LPRNet车牌识别
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
from plate_recognition.plate_recognizer import PlateRecognizer


class PlateRecognitionProcessor:
    """车牌识别处理器"""

    def __init__(self, device_manager):
        """
        初始化处理器

        Args:
            device_manager: 设备管理器实例
        """
        self.device_manager = device_manager
        self.active_streams = {}  # {device_id: thread}
        self.stop_flags = {}  # {device_id: stop_event}
        self.results_queue = Queue()  # 识别结果队列

        # 初始化AI模型
        print("=" * 60)
        print("正在初始化AI模型...")
        print("=" * 60)

        try:
            # 获取模型路径
            base_path = os.path.dirname(os.path.abspath(__file__))
            yolo_path = os.path.join(base_path, '../ai_models/vehicle_detection/yolo11s.pt')
            lprnet_path = os.path.join(base_path, '../ai_models/plate_recognition/Final_LPRNet_model.pth')

            # 加载车辆检测器
            self.vehicle_detector = VehicleDetector(model_path=yolo_path, conf_threshold=0.5)

            # 加载车牌识别器
            self.plate_recognizer = PlateRecognizer(model_path=lprnet_path)

            print("=" * 60)
            print("✅ AI模型加载完成！")
            print("=" * 60)

        except Exception as e:
            print(f"❌ AI模型加载失败: {str(e)}")
            raise

    def start_processing(self, device_id, stream_url):
        """
        启动视频流处理

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
        """
        if device_id in self.active_streams:
            print(f"设备 {device_id} 已在处理中")
            return False

        # 创建停止标志
        stop_event = threading.Event()
        self.stop_flags[device_id] = stop_event

        # 启动处理线程
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
        """
        视频流处理主循环

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
            stop_event: 停止事件
        """
        cap = None
        frame_count = 0
        process_interval = 15  # 每15帧处理一次（约1秒处理一次，假设15fps）

        try:
            # 打开视频流
            print(f"📡 正在连接视频流: {stream_url}")
            cap = cv2.VideoCapture(stream_url)

            if not cap.isOpened():
                print(f"❌ 无法打开视频流: {stream_url}")
                return

            print(f"✅ 成功连接视频流: {device_id}")
            print(f"   开始AI分析...")

            while not stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    print(f"⚠️  读取视频帧失败: {device_id}")
                    time.sleep(0.1)
                    continue

                frame_count += 1

                # 每N帧处理一次
                if frame_count % process_interval != 0:
                    continue

                # 执行车牌识别
                self._recognize_plates(device_id, frame)

        except Exception as e:
            print(f"❌ 视频流处理异常 {device_id}: {str(e)}")

        finally:
            if cap:
                cap.release()
            print(f"⏹️  视频流处理结束: {device_id}")

    def _recognize_plates(self, device_id, frame):
        """
        执行车牌识别

        Args:
            device_id: 设备ID
            frame: 视频帧
        """
        try:
            # 1. 检测车辆
            vehicles = self.vehicle_detector.detect(frame)

            if not vehicles:
                return

            # 2. 对每个车辆尝试识别车牌
            for vehicle in vehicles:
                bbox = vehicle['bbox']
                x1, y1, x2, y2 = bbox

                # 裁剪车辆区域
                vehicle_img = frame[y1:y2, x1:x2]

                if vehicle_img.size == 0:
                    continue

                # 简单的车牌区域估计（通常在车辆下半部分）
                h, w = vehicle_img.shape[:2]
                plate_region = vehicle_img[int(h*0.6):h, :]  # 下40%区域

                if plate_region.size == 0:
                    continue

                try:
                    # 3. 识别车牌
                    plate_number = self.plate_recognizer.recognize(plate_region)

                    # 过滤无效结果（太短或包含过多'-'）
                    if len(plate_number) < 6 or plate_number.count('-') > 2:
                        continue

                    # 4. 生成识别结果
                    result = {
                        'event_type': 'plate_recognition',
                        'timestamp': datetime.now().isoformat(),
                        'device_id': device_id,
                        'data': {
                            'plate_number': plate_number,
                            'vehicle_type': vehicle['class_name'],
                            'confidence': vehicle['confidence'],
                            'is_in_whitelist': self._check_whitelist(plate_number),
                            'decision': self._make_decision(plate_number)
                        },
                        'bbox': bbox,
                        'status': 'normal'
                    }

                    # 5. 保存结果
                    self.results_queue.put(result)

                    # 6. 打印到控制台
                    print("\n" + "=" * 60)
                    print("🚗 车牌识别成功！")
                    print("=" * 60)
                    print(f"   车牌号: {plate_number}")
                    print(f"   车辆类型: {vehicle['class_name']}")
                    print(f"   置信度: {vehicle['confidence']:.2f}")
                    print(f"   白名单: {'✅ 是' if result['data']['is_in_whitelist'] else '❌ 否'}")
                    print(f"   通行决策: {'🟢 允许' if result['data']['decision'] == 'allow' else '🔴 拒绝'}")
                    print(f"   位置: {bbox}")
                    print("=" * 60)

                except Exception as e:
                    # 识别失败，跳过
                    continue

        except Exception as e:
            print(f"⚠️  车牌识别处理异常: {str(e)}")

    def _check_whitelist(self, plate_number):
        """
        检查车牌是否在白名单中

        Args:
            plate_number: 车牌号

        Returns:
            bool: 是否在白名单
        """
        # TODO: 从数据库加载白名单
        # 临时白名单
        whitelist = ['京A12345', '沪B67890', '粤C88888', '京D99999']
        return plate_number in whitelist

    def _make_decision(self, plate_number):
        """
        生成通行决策

        Args:
            plate_number: 车牌号

        Returns:
            str: 'allow' 或 'deny'
        """
        return 'allow' if self._check_whitelist(plate_number) else 'deny'

    def get_latest_results(self, max_count=10):
        """
        获取最新的识别结果

        Args:
            max_count: 最多返回的结果数

        Returns:
            list: 识别结果列表
        """
        results = []
        while not self.results_queue.empty() and len(results) < max_count:
            results.append(self.results_queue.get())
        return results


if __name__ == '__main__':
    # 测试代码
    from device_manager import DeviceManager

    device_manager = DeviceManager()
    processor = PlateRecognitionProcessor(device_manager)

    print("\n车牌识别处理器测试完成")
