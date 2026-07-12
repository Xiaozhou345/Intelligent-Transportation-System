"""
车道线检测器 - 基于传统CV方法
使用Canny边缘检测 + 霍夫直线变换识别车道分隔线
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional


class LaneDetector:
    """
    车道线检测器

    功能：
    1. 检测画面中的竖直车道分隔线（白色标线）
    2. 将画面划分为多个车道区域
    3. 支持动态缓存，减少抖动
    """

    def __init__(
        self,
        min_line_length: int = 150,  # 提高最小长度，过滤短线段
        max_line_gap: int = 30,       # 降低间隙，更严格
        rho: int = 1,
        theta: float = np.pi / 180,
        threshold: int = 80,           # 提高阈值，减少误检
        vertical_tolerance: float = 10.0,  # 降低角度容差，更严格
        cache_frames: int = 15,        # 增加缓存，更平滑
    ):
        """
        初始化车道线检测器

        Args:
            min_line_length: 最小线段长度（像素）
            max_line_gap: 线段间最大间隙（像素）
            rho: 霍夫变换距离分辨率
            theta: 霍夫变换角度分辨率
            threshold: 霍夫变换阈值
            vertical_tolerance: 竖直线容差角度（度），例如15度表示75-105度范围内的线都视为竖直
            cache_frames: 缓存帧数，用于平滑抖动
        """
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap
        self.rho = rho
        self.theta = theta
        self.threshold = threshold
        self.vertical_tolerance = vertical_tolerance
        self.cache_frames = cache_frames

        # 车道线缓存（用于时序平滑）
        self.lane_lines_history: List[List[int]] = []

    def detect_lane_lines(self, frame: np.ndarray, roi_y_start: Optional[int] = None) -> List[int]:
        """
        检测车道分隔线的x坐标

        Args:
            frame: 输入图像（BGR格式）
            roi_y_start: ROI起始y坐标（只检测画面下半部分，因为车道线主要在地面）

        Returns:
            车道分隔线的x坐标列表，已排序（从左到右）
        """
        height, width = frame.shape[:2]

        # 默认只处理画面下半部分（车道线主要在地面区域）
        if roi_y_start is None:
            roi_y_start = height // 3

        roi = frame[roi_y_start:, :]

        # 1. 转灰度图
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # 2. 高斯模糊（降噪）
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # 3. 边缘检测（Canny）
        edges = cv2.Canny(blurred, 50, 150)

        # 4. 霍夫直线变换
        lines = cv2.HoughLinesP(
            edges,
            rho=self.rho,
            theta=self.theta,
            threshold=self.threshold,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap,
        )

        if lines is None or len(lines) == 0:
            # 未检测到线段，返回空列表
            return []

        # 5. 筛选竖直线段
        vertical_lines = []
        for line in lines:
            # HoughLinesP返回格式: [[x1, y1, x2, y2]]
            if isinstance(line, np.ndarray) and line.ndim == 2:
                x1, y1, x2, y2 = line[0]
            else:
                x1, y1, x2, y2 = line

            # 计算线段角度（相对于水平线）
            if x2 - x1 == 0:
                angle = 90.0  # 完全竖直
            else:
                angle = abs(np.arctan((y2 - y1) / (x2 - x1)) * 180 / np.pi)

            # 筛选接近竖直的线段（90度 ± vertical_tolerance）
            if abs(angle - 90.0) <= self.vertical_tolerance:
                # 计算线段中点的x坐标
                mid_x = (x1 + x2) // 2
                vertical_lines.append(mid_x)

        if not vertical_lines:
            return []

        # 6. 聚类合并（相近的x坐标视为同一条车道线）
        vertical_lines = sorted(vertical_lines)
        merged_lines = []

        cluster = [vertical_lines[0]]
        for i in range(1, len(vertical_lines)):
            if vertical_lines[i] - cluster[-1] <= 30:  # 30像素容差
                cluster.append(vertical_lines[i])
            else:
                # 当前聚类结束，取平均值
                merged_lines.append(int(np.mean(cluster)))
                cluster = [vertical_lines[i]]

        # 处理最后一个聚类
        if cluster:
            merged_lines.append(int(np.mean(cluster)))

        # 7. 过滤边界线（距离画面边缘太近的线）
        margin = 50  # 边缘容差50像素
        filtered_lines = [x for x in merged_lines if margin < x < width - margin]

        # 8. 时序平滑（使用历史缓存）
        self.lane_lines_history.append(filtered_lines)
        if len(self.lane_lines_history) > self.cache_frames:
            self.lane_lines_history.pop(0)

        # 投票机制：只保留出现频率高的车道线
        stable_lines = self._vote_stable_lines(width)

        return sorted(stable_lines)

    def _vote_stable_lines(self, frame_width: int) -> List[int]:
        """
        对历史缓存中的车道线进行投票，返回稳定的车道线

        Args:
            frame_width: 画面宽度

        Returns:
            稳定的车道线x坐标列表
        """
        if not self.lane_lines_history:
            return []

        # 将所有历史车道线展平
        all_lines = []
        for lines in self.lane_lines_history:
            all_lines.extend(lines)

        if not all_lines:
            return []

        # 聚类投票（相近的x坐标视为同一条线）
        all_lines = sorted(all_lines)
        clusters = []

        cluster = [all_lines[0]]
        for i in range(1, len(all_lines)):
            if all_lines[i] - cluster[-1] <= 40:  # 40像素容差
                cluster.append(all_lines[i])
            else:
                clusters.append(cluster)
                cluster = [all_lines[i]]

        if cluster:
            clusters.append(cluster)

        # 只保留出现频率 >= 50%的聚类
        min_votes = len(self.lane_lines_history) * 0.5
        stable_lines = []

        for cluster in clusters:
            if len(cluster) >= min_votes:
                stable_lines.append(int(np.mean(cluster)))

        return stable_lines

    def divide_lanes(
        self, frame_width: int, lane_lines: List[int]
    ) -> List[Tuple[int, int, int]]:
        """
        根据车道线将画面划分为多个车道区域

        Args:
            frame_width: 画面宽度
            lane_lines: 车道分隔线的x坐标列表（已排序）

        Returns:
            车道区域列表，每个元素为 (lane_id, x_start, x_end)
        """
        if not lane_lines:
            # 未检测到车道线，整个画面视为一个车道
            return [(0, 0, frame_width)]

        lanes = []

        # 车道0：画面左边缘 到 第一条车道线
        lanes.append((0, 0, lane_lines[0]))

        # 中间车道：第i条车道线 到 第i+1条车道线
        for i in range(len(lane_lines) - 1):
            lanes.append((i + 1, lane_lines[i], lane_lines[i + 1]))

        # 最后一个车道：最后一条车道线 到 画面右边缘
        lanes.append((len(lane_lines), lane_lines[-1], frame_width))

        return lanes

    def assign_vehicle_to_lane(
        self, vehicle_x: int, lanes: List[Tuple[int, int, int]]
    ) -> int:
        """
        判断车辆属于哪个车道

        Args:
            vehicle_x: 车辆底部中心点的x坐标
            lanes: 车道区域列表 [(lane_id, x_start, x_end), ...]

        Returns:
            车道ID（lane_id）
        """
        for lane_id, x_start, x_end in lanes:
            if x_start <= vehicle_x < x_end:
                return lane_id

        # 边界情况：车辆在最右边缘
        if lanes:
            return lanes[-1][0]

        return 0

    def reset_cache(self):
        """重置历史缓存（用于切换场景或重启检测）"""
        self.lane_lines_history.clear()
