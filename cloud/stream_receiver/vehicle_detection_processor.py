"""
实时车辆检测视频处理引擎 - 修复版
"""
import cv2
import sys
import os
import threading
import time
from datetime import datetime
from queue import Queue
import numpy as np

# 修正路径 - AI模型在 cloud/ai_models 下
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_models_dir = os.path.join(current_dir, '..', 'ai_models')
vehicle_detection_dir = os.path.join(ai_models_dir, 'vehicle_detection')

sys.path.insert(0, ai_models_dir)
sys.path.insert(0, vehicle_detection_dir)

from detector import VehicleDetector


class VehicleDetectionProcessor:
    """车辆检测处理器"""

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
        print("正在初始化AI模型...")
        print("=" * 60)

        try:
            sandbox_model_path = os.path.join(ai_models_dir, 'vehicle_detection', 'sandbox_vehicle_best.pt')
            default_model_path = os.path.join(ai_models_dir, 'vehicle_detection', 'yolo11s.pt')
            yolo_path = sandbox_model_path if os.path.exists(sandbox_model_path) else default_model_path
            print(f"YOLO权重路径: {yolo_path}")

            if not os.path.exists(yolo_path):
                raise FileNotFoundError(f"YOLO权重文件不存在: {yolo_path}")

            # 横竖屏增强模型在 0.45 左右可减少横屏和空场景误检
            self.vehicle_detector = VehicleDetector(model_path=yolo_path, conf_threshold=0.45)

            print("=" * 60)
            print("✅ AI模型加载完成！")
            print("   配置: 沙盘模式 - 横竖屏增强检测 (0.45)")
            print("=" * 60)

        except Exception as e:
            print(f"❌ AI模型加载失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

    def start_processing(self, device_id, stream_url):
        """启动视频流处理"""
        if device_id in self.active_streams:
            thread = self.active_streams[device_id]
            if thread.is_alive():
                print(f"设备 {device_id} 已在处理中")
                return False

            # 之前的处理线程可能因为读流失败已退出，清理后允许重新启动
            print(f"⚠️  设备 {device_id} 的旧处理线程已结束，重新启动处理")
            self.active_streams.pop(device_id, None)
            old_stop_event = self.stop_flags.pop(device_id, None)
            if old_stop_event:
                old_stop_event.set()

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
        return True

    def ensure_processing(self, device_id, stream_url):
        """确保指定设备的视频处理线程正在运行"""
        thread = self.active_streams.get(device_id)
        if thread and thread.is_alive():
            return True
        return self.start_processing(device_id, stream_url)

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

            open_attempts = 0
            max_open_attempts = 60
            while not stop_event.is_set() and open_attempts < max_open_attempts:
                open_attempts += 1
                cap = cv2.VideoCapture(stream_url)

                if cap.isOpened():
                    break

                if cap:
                    cap.release()
                    cap = None

                if open_attempts == 1 or open_attempts % 5 == 0:
                    print(
                        f"⚠️  视频流尚未可读: {stream_url} "
                        f"(打开尝试 {open_attempts}/{max_open_attempts})"
                    )
                time.sleep(1)

            if not cap or not cap.isOpened():
                print(f"❌ 无法打开视频流: {stream_url}")
                return

            print(f"✅ 成功连接视频流: {device_id}")
            print(f"   开始AI分析（沙盘优化模式）...")

            consecutive_errors = 0
            max_consecutive_errors = 60
            last_read_error_log_time = 0

            while not stop_event.is_set():
                try:
                    ret, frame = cap.read()

                    if not ret:
                        consecutive_errors += 1
                        now = time.time()
                        if consecutive_errors == 1 or now - last_read_error_log_time >= 3:
                            print(
                                f"⚠️  视频流暂时无帧: {device_id} "
                                f"(连续失败 {consecutive_errors}/{max_consecutive_errors})"
                            )
                            last_read_error_log_time = now

                        # RTMP 推流端短暂卡顿或重连时不要立刻结束线程，继续等待
                        if consecutive_errors >= max_consecutive_errors:
                            print(f"❌ 连续读取失败 {max_consecutive_errors} 次，停止处理")
                            break
                        time.sleep(0.5)
                        continue

                    if consecutive_errors > 0:
                        print(f"✅ 视频流恢复: {device_id}")
                    consecutive_errors = 0  # 重置错误计数
                    frame_count += 1

                    # 每N帧处理一次
                    if frame_count % process_interval != 0:
                        continue

                    # 执行车辆检测
                    self._detect_vehicles(device_id, frame, frame_count)

                except Exception as e:
                    print(f"⚠️  帧处理异常: {str(e)}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"❌ 连续异常 {max_consecutive_errors} 次，停止处理")
                        break
                    time.sleep(0.1)

        except Exception as e:
            print(f"❌ 视频流处理异常 {device_id}: {str(e)}")
            import traceback
            traceback.print_exc()

        finally:
            if cap:
                cap.release()
            print(f"⏹️  视频流处理结束: {device_id} (共处理 {frame_count} 帧)")

    def _detect_vehicles(self, device_id, frame, frame_count):
        """执行车辆检测"""
        try:
            # 每次真正进入模型推理都打印一行，方便确认不是卡在读流阶段
            print(f"🔎 帧 {frame_count}: 开始车辆检测")

            # 检测车辆
            vehicles = self.vehicle_detector.detect(frame)

            if not vehicles:
                print(f"⏳ 帧 {frame_count}: 未检测到车辆")
                return

            # 检测到车辆！
            print("\n" + "=" * 60)
            print(f"🚗 检测到 {len(vehicles)} 辆车辆！")
            print("=" * 60)

            for idx, vehicle in enumerate(vehicles):
                bbox = vehicle['bbox']

                # 生成检测结果
                result = {
                    'event_type': 'vehicle_detection',
                    'timestamp': datetime.now().isoformat(),
                    'device_id': device_id,
                    'data': {
                        'vehicle_id': idx + 1,
                        'vehicle_type': vehicle['class_name'],
                        'confidence': vehicle['confidence'],
                        'plate_number': '未识别',
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

            print("=" * 60)

        except Exception as e:
            print(f"⚠️  车辆检测处理异常: {str(e)}")
            import traceback
            traceback.print_exc()

    def get_latest_results(self, max_count=10):
        """获取最新的识别结果"""
        results = []
        while not self.results_queue.empty() and len(results) < max_count:
            results.append(self.results_queue.get())
        return results


if __name__ == '__main__':
    from device_manager import DeviceManager

    device_manager = DeviceManager()
    processor = VehicleDetectionProcessor(device_manager)

    print("\n车辆检测处理器测试完成")
