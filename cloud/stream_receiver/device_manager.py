"""
设备管理模块
负责边端设备的注册、管理和视频流信息维护
"""
from datetime import datetime
from typing import Dict, Optional
import threading


class Device:
    """设备信息类"""

    def __init__(self, device_id: str, stream_url: str, resolution: str,
                 fps: int, scene_id: str, codec: str = "H.264",
                 bitrate: str = "2Mbps"):
        """
        初始化设备信息

        Args:
            device_id: 设备唯一标识
            stream_url: RTMP推流地址
            resolution: 分辨率（如：1280x720）
            fps: 帧率
            scene_id: 场景标识
            codec: 编码格式
            bitrate: 码率
        """
        self.device_id = device_id
        self.stream_url = stream_url
        self.resolution = resolution
        self.fps = fps
        self.scene_id = scene_id
        self.codec = codec
        self.bitrate = bitrate
        self.register_time = datetime.now()
        self.last_heartbeat = datetime.now()
        self.status = "online"  # online, offline

    def to_dict(self):
        """转换为字典"""
        return {
            "device_id": self.device_id,
            "stream_url": self.stream_url,
            "resolution": self.resolution,
            "fps": self.fps,
            "scene_id": self.scene_id,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "register_time": self.register_time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_heartbeat": self.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S"),
            "status": self.status
        }

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now()
        self.status = "online"


class DeviceManager:
    """设备管理器"""

    def __init__(self):
        """初始化设备管理器"""
        self.devices: Dict[str, Device] = {}
        self.lock = threading.Lock()
        print("设备管理器初始化完成")

    def register_device(self, device_id: str, stream_url: str,
                       resolution: str, fps: int, scene_id: str,
                       codec: str = "H.264", bitrate: str = "2Mbps") -> bool:
        """
        注册新设备

        Args:
            device_id: 设备ID
            stream_url: RTMP流地址
            resolution: 分辨率
            fps: 帧率
            scene_id: 场景ID
            codec: 编码格式
            bitrate: 码率

        Returns:
            bool: 是否注册成功
        """
        with self.lock:
            if device_id in self.devices:
                print(f"设备 {device_id} 已存在，更新设备信息")
            else:
                print(f"注册新设备: {device_id}")

            device = Device(
                device_id=device_id,
                stream_url=stream_url,
                resolution=resolution,
                fps=fps,
                scene_id=scene_id,
                codec=codec,
                bitrate=bitrate
            )
            self.devices[device_id] = device
            return True

    def unregister_device(self, device_id: str) -> bool:
        """
        注销设备

        Args:
            device_id: 设备ID

        Returns:
            bool: 是否注销成功
        """
        with self.lock:
            if device_id in self.devices:
                del self.devices[device_id]
                print(f"设备 {device_id} 已注销")
                return True
            else:
                print(f"设备 {device_id} 不存在")
                return False

    def get_device(self, device_id: str) -> Optional[Device]:
        """
        获取设备信息

        Args:
            device_id: 设备ID

        Returns:
            Device: 设备对象，不存在则返回None
        """
        with self.lock:
            return self.devices.get(device_id)

    def get_all_devices(self) -> Dict[str, Device]:
        """
        获取所有设备

        Returns:
            Dict[str, Device]: 所有设备字典
        """
        with self.lock:
            return self.devices.copy()

    def update_heartbeat(self, device_id: str) -> bool:
        """
        更新设备心跳

        Args:
            device_id: 设备ID

        Returns:
            bool: 是否更新成功
        """
        with self.lock:
            device = self.devices.get(device_id)
            if device:
                device.update_heartbeat()
                return True
            return False

    def set_device_offline(self, device_id: str):
        """
        设置设备离线

        Args:
            device_id: 设备ID
        """
        with self.lock:
            device = self.devices.get(device_id)
            if device:
                device.status = "offline"
                print(f"设备 {device_id} 已离线")


if __name__ == '__main__':
    # 测试代码
    manager = DeviceManager()

    # 注册设备
    manager.register_device(
        device_id="mobile_001",
        stream_url="rtmp://192.168.1.100:1935/live/stream_001",
        resolution="1280x720",
        fps=15,
        scene_id="scene_704_sandbox"
    )

    # 获取设备
    device = manager.get_device("mobile_001")
    if device:
        print(f"\n设备信息: {device.to_dict()}")

    # 更新心跳
    manager.update_heartbeat("mobile_001")

    # 获取所有设备
    all_devices = manager.get_all_devices()
    print(f"\n所有在线设备数: {len(all_devices)}")

    print("\n设备管理器测试完成")
