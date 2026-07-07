"""
视频流处理引擎
负责从RTMP拉取视频流、解帧、送入AI模型、推送结果到前端
"""
import cv2
import threading
import time
from datetime import datetime
from queue import Queue
import json


class VideoProcessor:
    """视频流处理器"""

    def __init__(self, device_manager, socketio):
        """
        初始化视频处理器

        Args:
            device_manager: 设备管理器实例
            socketio: SocketIO实例，用于推送结果
        """
        self.device_manager = device_manager
        self.socketio = socketio
        self.active_streams = {}  # {device_id: thread}
        self.stop_flags = {}  # {device_id: stop_event}
        self.frame_skip = 3  # 每3帧处理1帧（性能优化）

        print("视频处理引擎初始化完成")

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

        print(f"开始处理设备 {device_id} 的视频流: {stream_url}")
        return True

    def stop_processing(self, device_id):
        """
        停止视频流处理

        Args:
            device_id: 设备ID
        """
        if device_id not in self.active_streams:
            print(f"设备 {device_id} 未在处理中")
            return False

        # 设置停止标志
        self.stop_flags[device_id].set()

        # 等待线程结束
        self.active_streams[device_id].join(timeout=5)

        # 清理
        del self.active_streams[device_id]
        del self.stop_flags[device_id]

        print(f"停止处理设备 {device_id} 的视频流")
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

        try:
            # 打开视频流
            cap = cv2.VideoCapture(stream_url)

            if not cap.isOpened():
                print(f"无法打开视频流: {stream_url}")
                self._send_error(device_id, "无法打开视频流")
                return

            print(f"成功连接视频流: {device_id}")

            while not stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    print(f"视频流 {device_id} 读取失败")
                    time.sleep(0.1)
                    continue

                frame_count += 1

                # 跳帧策略：每3帧处理1帧
                if frame_count % self.frame_skip != 0:
                    continue

                # 处理帧（目前生成模拟数据）
                self._analyze_frame(device_id, frame, frame_count)

                # 控制处理速度
                time.sleep(0.1)

        except Exception as e:
            print(f"视频流处理异常 {device_id}: {str(e)}")
            self._send_error(device_id, str(e))

        finally:
            if cap:
                cap.release()
            print(f"视频流处理结束: {device_id}")

    def _analyze_frame(self, device_id, frame, frame_count):
        """
        分析单帧图像（目前生成模拟数据）

        Args:
            device_id: 设备ID
            frame: 图像帧
            frame_count: 帧计数
        """
        # TODO: 集成真实AI模型
        # 目前生成模拟数据用于演示

        timestamp = datetime.now().isoformat()

        # 每10帧生成一次模拟结果
        if frame_count % 10 == 0:
            event_type = self._get_event_type(frame_count)
            result = self._generate_mock_result(device_id, timestamp, event_type)

            # 通过WebSocket推送结果
            self._send_result(result)

    def _get_event_type(self, frame_count):
        """根据帧数循环返回不同事件类型"""
        types = ['plate_recognition', 'traffic_density', 'illegal_parking', 'road_anomaly']
        return types[(frame_count // 10) % len(types)]

    def _generate_mock_result(self, device_id, timestamp, event_type):
        """
        生成模拟分析结果

        Args:
            device_id: 设备ID
            timestamp: 时间戳
            event_type: 事件类型

        Returns:
            dict: 分析结果
        """
        base_result = {
            'event_type': event_type,
            'timestamp': timestamp,
            'device_id': device_id,
            'status': 'normal'
        }

        if event_type == 'plate_recognition':
            base_result['data'] = {
                'plate_number': '京A12345',
                'is_in_whitelist': True,
                'decision': 'allow'
            }
            base_result['bbox'] = [120, 80, 220, 140]

        elif event_type == 'traffic_density':
            base_result['data'] = {
                'regions': [
                    {'region_id': 'road_A', 'vehicle_count': 2, 'status': 'smooth', 'color': 'green'},
                    {'region_id': 'road_B', 'vehicle_count': 5, 'status': 'slow', 'color': 'yellow'},
                    {'region_id': 'road_C', 'vehicle_count': 8, 'status': 'congested', 'color': 'red'}
                ]
            }

        elif event_type == 'illegal_parking':
            base_result['data'] = {
                'track_id': 17,
                'stay_time': 35.5,
                'threshold': 30
            }
            base_result['bbox'] = [230, 180, 310, 260]
            base_result['status'] = 'warning'

        elif event_type == 'road_anomaly':
            base_result['data'] = {
                'anomaly_type': 'unknown_object',
                'affected_lane': 'lane_1',
                'duration_frames': 20
            }
            base_result['bbox'] = [360, 220, 420, 280]
            base_result['status'] = 'warning'

        return base_result

    def _send_result(self, result):
        """
        通过WebSocket发送结果到前端

        Args:
            result: 分析结果字典
        """
        try:
            self.socketio.emit('analysis_result', result)
            print(f"推送结果: {result['event_type']}")
        except Exception as e:
            print(f"推送结果失败: {str(e)}")

    def _send_error(self, device_id, error_message):
        """
        发送错误信息

        Args:
            device_id: 设备ID
            error_message: 错误消息
        """
        try:
            self.socketio.emit('error', {
                'device_id': device_id,
                'message': error_message,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"发送错误信息失败: {str(e)}")

    def get_active_streams(self):
        """获取当前活跃的视频流列表"""
        return list(self.active_streams.keys())


if __name__ == '__main__':
    # 测试代码
    from device_manager import DeviceManager

    class MockSocketIO:
        def emit(self, event, data):
            print(f"[SocketIO] {event}: {data}")

    device_manager = DeviceManager()
    socketio = MockSocketIO()

    processor = VideoProcessor(device_manager, socketio)

    # 注册测试设备
    device_manager.register_device(
        device_id="test_001",
        stream_url="rtmp://localhost:1935/live/test_001",
        resolution="1280x720",
        fps=15,
        scene_id="test_scene"
    )

    print("\n视频处理引擎测试完成")
