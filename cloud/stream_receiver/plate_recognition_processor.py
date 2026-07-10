"""
实时车牌识别视频处理引擎
集成车牌YOLO检测 + LPRNet车牌识别
"""
import cv2
import sys
import os
import threading
import time
from datetime import datetime
from queue import Queue

# 添加AI模型路径
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_models_dir = os.path.join(current_dir, '..', 'ai_models')
plate_detection_dir = os.path.join(ai_models_dir, 'plate_detection')
cloud_dir = os.path.dirname(current_dir)

sys.path.insert(0, ai_models_dir)
sys.path.insert(0, plate_detection_dir)
if cloud_dir not in sys.path:
    sys.path.insert(0, cloud_dir)

from plate_detection.detector import PlateDetector
from plate_recognition.plate_recognizer import PlateRecognizer
from database import mysql_client


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

        print("=" * 60)
        print("正在初始化车牌识别AI模型...")
        print("=" * 60)

        try:
            self.plate_model_path = self._resolve_plate_model_path()
            self.lprnet_path = self._resolve_lprnet_model_path()

            print(f"车牌检测模型路径: {self.plate_model_path}")
            print(f"LPRNet模型路径: {self.lprnet_path}")

            self.plate_detector = PlateDetector(
                model_path=self.plate_model_path,
                conf_threshold=0.20
            )
            self.plate_recognizer = PlateRecognizer(model_path=self.lprnet_path)

            print("=" * 60)
            print("✅ 车牌识别AI模型加载完成！")
            print("   配置: 车牌直检模式 (conf=0.20)")
            print("=" * 60)

        except Exception as e:
            print(f"❌ AI模型加载失败: {str(e)}")
            raise

    def _resolve_plate_model_path(self):
        candidates = [
            os.path.join(ai_models_dir, 'plate_detection', 'sandbox_plate_best.pt'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        raise FileNotFoundError("未找到车牌检测模型 sandbox_plate_best.pt")

    def _resolve_lprnet_model_path(self):
        repo_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
        candidates = [
            os.path.join(ai_models_dir, 'plate_recognition', 'Final_LPRNet_model.pth'),
            os.path.join(repo_root, 'models', 'lprnet_best.pth'),
            os.path.join(repo_root, 'ui', 'models', 'pretrained_lprnet.pth'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        raise FileNotFoundError("未找到可用的LPRNet模型文件")

    def start_processing(self, device_id, stream_url):
        """
        启动视频流处理

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
        """
        if device_id in self.active_streams:
            thread = self.active_streams[device_id]
            if thread.is_alive():
                print(f"设备 {device_id} 已在处理中")
                return False

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
            print("   开始车牌检测 + OCR 分析...")

            consecutive_errors = 0
            max_consecutive_errors = 60
            last_read_error_log_time = 0

            while not stop_event.is_set():
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

                    if consecutive_errors >= max_consecutive_errors:
                        print(f"❌ 连续读取失败 {max_consecutive_errors} 次，停止处理")
                        break
                    time.sleep(0.5)
                    continue

                if consecutive_errors > 0:
                    print(f"✅ 视频流恢复: {device_id}")
                consecutive_errors = 0
                frame_count += 1

                if frame_count % process_interval != 0:
                    continue

                self._recognize_plates(device_id, frame, frame_count)

        except Exception as e:
            print(f"❌ 视频流处理异常 {device_id}: {str(e)}")

        finally:
            if cap:
                cap.release()
            print(f"⏹️  视频流处理结束: {device_id} (共处理 {frame_count} 帧)")

    def _recognize_plates(self, device_id, frame, frame_count):
        """
        执行车牌检测与识别

        Args:
            device_id: 设备ID
            frame: 视频帧
        """
        try:
            print(f"🔎 帧 {frame_count}: 开始车牌检测")
            plates = self.plate_detector.detect(frame)

            if not plates:
                print(f"⏳ 帧 {frame_count}: 未检测到车牌")
                return

            print("\n" + "=" * 60)
            print(f"🔵 检测到 {len(plates)} 个车牌区域！")
            print("=" * 60)

            for idx, plate in enumerate(plates):
                bbox = plate['bbox']
                x1, y1, x2, y2 = bbox
                plate_img = frame[y1:y2, x1:x2]

                if plate_img is None or plate_img.size == 0:
                    print(f"⚠️  车牌 #{idx + 1} 裁剪为空，跳过")
                    continue

                try:
                    plate_number = self.plate_recognizer.recognize(plate_img)
                except Exception as e:
                    print(f"⚠️  车牌 #{idx + 1} OCR 失败: {str(e)}")
                    continue

                if not plate_number or len(plate_number.strip()) < 4:
                    print(f"⚠️  车牌 #{idx + 1} OCR 结果过短: {plate_number!r}")
                    continue

                result = {
                    'event_type': 'plate_recognition',
                    'timestamp': datetime.now().isoformat(),
                    'device_id': device_id,
                    'data': {
                        'plate_number': plate_number,
                        'vehicle_type': 'unknown',
                        'confidence': plate['confidence'],
                        'is_in_whitelist': self._check_whitelist(plate_number),
                        'decision': self._make_decision(plate_number)
                    },
                    'bbox': bbox,
                    'status': 'normal'
                }

                self.results_queue.put(result)
                device = self.device_manager.get_device(device_id)
                scene_id = device.scene_id if device else None
                mysql_client.insert_recognition_event('plate_recognition', device_id, result, scene_id=scene_id)

                print(f"   车牌 #{idx + 1}:")
                print(f"      车牌号: {plate_number}")
                print(f"      置信度: {plate['confidence']:.2f}")
                print(f"      白名单: {'✅ 是' if result['data']['is_in_whitelist'] else '❌ 否'}")
                print(f"      通行决策: {'🟢 允许' if result['data']['decision'] == 'allow' else '🔴 拒绝'}")
                print(f"      位置: {bbox}")

            print("=" * 60)

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
        row = mysql_client.get_whitelist_entry(plate_number)
        if row is not None:
            return bool(row.get('permission_status', 0))

        # 数据库不可用或未录入时，退回临时白名单
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
    from device_manager import DeviceManager

    device_manager = DeviceManager()
    processor = PlateRecognitionProcessor(device_manager)

    print("\n车牌识别处理器测试完成")
