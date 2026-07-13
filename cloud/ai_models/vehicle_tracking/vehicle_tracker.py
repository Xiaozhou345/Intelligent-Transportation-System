"""
车辆跟踪模块
使用ByteTrack算法进行多目标车辆跟踪
"""
import numpy as np
from collections import deque
import cv2


class KalmanFilter:
    """简化的卡尔曼滤波器，用于目标位置预测"""

    def __init__(self):
        ndim, dt = 4, 1.

        # 创建卡尔曼滤波矩阵
        self._motion_mat = np.eye(2 * ndim, 2 * ndim)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt
        self._update_mat = np.eye(ndim, 2 * ndim)

        # 运动和观测不确定性权重
        self._std_weight_position = 1. / 20
        self._std_weight_velocity = 1. / 160

    def initiate(self, measurement):
        """初始化跟踪目标"""
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]

        std = [
            2 * self._std_weight_position * measurement[3],
            2 * self._std_weight_position * measurement[3],
            1e-2,
            2 * self._std_weight_position * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            1e-5,
            10 * self._std_weight_velocity * measurement[3]
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean, covariance):
        """预测下一帧的位置"""
        std_pos = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3]
        ]
        std_vel = [
            self._std_weight_velocity * mean[3],
            self._std_weight_velocity * mean[3],
            1e-5,
            self._std_weight_velocity * mean[3]
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))

        mean = np.dot(self._motion_mat, mean)
        covariance = np.linalg.multi_dot((
            self._motion_mat, covariance, self._motion_mat.T)) + motion_cov

        return mean, covariance

    def update(self, mean, covariance, measurement):
        """更新跟踪状态"""
        std = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-1,
            self._std_weight_position * mean[3]
        ]
        innovation_cov = np.diag(np.square(std))

        projected_mean = np.dot(self._update_mat, mean)
        projected_cov = np.linalg.multi_dot((
            self._update_mat, covariance, self._update_mat.T))

        update_cov = projected_cov + innovation_cov
        chol_factor = None
        for jitter in [0.0, 1e-6, 1e-4, 1e-2]:
            try:
                chol_factor = np.linalg.cholesky(
                    update_cov + np.eye(update_cov.shape[0]) * jitter
                )
                break
            except np.linalg.LinAlgError:
                continue

        if chol_factor is None:
            # 回退到更稳定的伪逆解，避免跟踪线程崩溃
            kalman_gain = np.dot(
                covariance,
                np.dot(self._update_mat.T, np.linalg.pinv(update_cov))
            )
        else:
            kalman_gain = np.linalg.lstsq(
                chol_factor, np.dot(covariance, self._update_mat.T).T,
                rcond=None)[0].T
        innovation = measurement - projected_mean

        new_mean = mean + np.dot(innovation, kalman_gain.T)
        new_covariance = covariance - np.linalg.multi_dot((
            kalman_gain, projected_cov, kalman_gain.T))
        return new_mean, new_covariance


class Track:
    """跟踪目标类"""

    _count = 0

    def __init__(self, bbox, score, frame_id):
        """
        初始化跟踪目标

        Args:
            bbox: [x1, y1, x2, y2] 边界框
            score: 置信度
            frame_id: 当前帧ID
        """
        self.track_id = Track._count
        Track._count += 1

        # 转换bbox为tlwh格式 (top-left x, y, width, height)
        self.tlwh = np.array([bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]])
        self.score = score

        # 卡尔曼滤波器
        self.kalman_filter = KalmanFilter()
        self.mean, self.covariance = self.kalman_filter.initiate(self.tlwh_to_xyah(self.tlwh))

        # 状态
        self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id
        self.tracklet_len = 0
        self.time_since_update = 0

        # 轨迹历史
        self.history = deque(maxlen=30)
        self.history.append(bbox)
        self.last_detection_bbox = [float(value) for value in bbox]

    @staticmethod
    def tlwh_to_xyah(tlwh):
        """转换tlwh到xyah格式 (center_x, center_y, aspect_ratio, height)"""
        ret = np.asarray(tlwh, dtype=np.float64).copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    @staticmethod
    def xyah_to_tlwh(xyah):
        """转换xyah到tlwh格式"""
        ret = np.asarray(xyah, dtype=np.float64).copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    def predict(self):
        """预测下一帧位置"""
        self.mean, self.covariance = self.kalman_filter.predict(self.mean, self.covariance)
        self.time_since_update += 1

    def update(self, new_bbox, new_score, frame_id):
        """更新跟踪状态"""
        self.frame_id = frame_id
        self.tracklet_len += 1
        self.time_since_update = 0

        new_tlwh = np.array([new_bbox[0], new_bbox[1],
                             new_bbox[2] - new_bbox[0],
                             new_bbox[3] - new_bbox[1]])
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_tlwh))
        self.score = new_score
        self.history.append(new_bbox)
        self.last_detection_bbox = [float(value) for value in new_bbox]

    def get_bbox(self):
        """获取当前bbox [x1, y1, x2, y2]"""
        if self.mean is None:
            tlwh = self.tlwh
        else:
            ret = self.mean[:4].copy()
            ret[2] *= ret[3]
            ret[:2] -= ret[2:] / 2
            tlwh = ret

        bbox = [tlwh[0], tlwh[1], tlwh[0] + tlwh[2], tlwh[1] + tlwh[3]]
        return bbox

    def get_detection_bbox(self):
        """返回最新检测框，避免展示层受卡尔曼平滑滞后影响。"""
        return list(self.last_detection_bbox)


class VehicleTracker:
    """车辆跟踪器"""

    def __init__(self, max_time_lost=30, track_thresh=0.5, match_thresh=0.8):
        """
        初始化车辆跟踪器

        Args:
            max_time_lost: 最大丢失帧数
            track_thresh: 跟踪置信度阈值
            match_thresh: IoU匹配阈值
        """
        self.max_time_lost = max_time_lost
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh

        self.frame_id = 0
        self.tracked_tracks = []  # 正在跟踪的目标
        self.lost_tracks = []     # 丢失的目标

        print("车辆跟踪器初始化完成")

    def reset(self):
        """重置跟踪器状态（用于视频流切换或场景变化）"""
        self.frame_id = 0
        self.tracked_tracks = []
        self.lost_tracks = []

    @staticmethod
    def iou(bbox1, bbox2):
        """计算两个bbox的IoU"""
        x1_min, y1_min, x1_max, y1_max = bbox1
        x2_min, y2_min, x2_max, y2_max = bbox2

        inter_x_min = max(x1_min, x2_min)
        inter_y_min = max(y1_min, y2_min)
        inter_x_max = min(x1_max, x2_max)
        inter_y_max = min(y1_max, y2_max)

        if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
            return 0.0

        inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
        bbox1_area = (x1_max - x1_min) * (y1_max - y1_min)
        bbox2_area = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = bbox1_area + bbox2_area - inter_area

        return inter_area / union_area if union_area > 0 else 0.0

    def update(self, detections):
        """
        更新跟踪器

        Args:
            detections: 检测结果列表，每个元素为字典:
                {
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float,
                    'class_name': str
                }

        Returns:
            list: 跟踪结果列表，每个元素为字典:
                {
                    'track_id': int,
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float,
                    'class_name': str
                }
        """
        self.frame_id += 1

        # 过滤明显无效的检测框，避免数值异常传播到 Kalman 更新
        valid_detections = []
        for det in detections:
            bbox = det.get('bbox')
            if not bbox or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            w = x2 - x1
            h = y2 - y1
            if w <= 2 or h <= 2:
                continue
            if not np.isfinite([x1, y1, x2, y2]).all():
                continue
            valid_detections.append(det)

        # 清理超时轨迹，并预测活跃/短暂丢失目标的位置。
        self.lost_tracks = [
            track for track in self.lost_tracks
            if self.frame_id - track.frame_id <= self.max_time_lost
        ]
        for track in self.tracked_tracks:
            track.predict()
        for track in self.lost_tracks:
            track.predict()

        # 分离高低置信度检测
        high_det = [d for d in valid_detections if d['confidence'] >= self.track_thresh]
        low_det = [d for d in valid_detections if d['confidence'] < self.track_thresh]

        # 匹配高置信度检测与跟踪
        unmatched_tracks, unmatched_dets = self._match(self.tracked_tracks, high_det)

        # 未匹配的跟踪尝试与低置信度检测匹配
        second_unmatched_tracks, _ = self._match(unmatched_tracks, low_det)

        # 优先用未匹配的高置信度检测恢复短暂丢失的 ID，
        # 否则偶发的一帧漏检会让违停计时从头开始。
        recoverable_lost = list(self.lost_tracks)
        still_lost, unmatched_dets = self._match(recoverable_lost, unmatched_dets)
        reactivated_tracks = [
            track for track in recoverable_lost if track not in still_lost
        ]
        for track in reactivated_tracks:
            if track in self.lost_tracks:
                self.lost_tracks.remove(track)
            if track not in self.tracked_tracks:
                self.tracked_tracks.append(track)

        # 标记丢失的跟踪
        for track in second_unmatched_tracks:
            if track not in self.lost_tracks:
                self.lost_tracks.append(track)
            if track in self.tracked_tracks:
                self.tracked_tracks.remove(track)

        # 创建新跟踪
        for det in unmatched_dets:
            new_track = Track(det['bbox'], det['confidence'], self.frame_id)
            new_track.class_name = det.get('class_name', 'vehicle')
            self.tracked_tracks.append(new_track)

        # 返回当前跟踪结果
        results = []
        for track in self.tracked_tracks:
            if track.is_activated:
                results.append({
                    'track_id': track.track_id,
                    # 展示与业务规则使用当前检测框，保证画框跟上当前画面。
                    'bbox': track.get_detection_bbox(),
                    'smoothed_bbox': track.get_bbox(),
                    'confidence': track.score,
                    'class_name': getattr(track, 'class_name', 'vehicle')
                })

        return results

    def _match(self, tracks, detections):
        """匹配跟踪和检测"""
        if len(tracks) == 0 or len(detections) == 0:
            # Return snapshots: callers may append reactivated tracks to the
            # original active list later in the same update cycle.
            return list(tracks), list(detections)

        # 计算IoU矩阵
        iou_matrix = np.zeros((len(tracks), len(detections)))
        for i, track in enumerate(tracks):
            track_bbox = track.get_bbox()
            for j, det in enumerate(detections):
                iou_matrix[i, j] = self.iou(track_bbox, det['bbox'])

        # 贪心匹配
        matched_tracks = []
        matched_dets = []

        for _ in range(min(len(tracks), len(detections))):
            max_iou = iou_matrix.max()
            if max_iou < self.match_thresh:
                break

            i, j = np.unravel_index(iou_matrix.argmax(), iou_matrix.shape)
            tracks[i].update(detections[j]['bbox'], detections[j]['confidence'], self.frame_id)
            tracks[i].class_name = detections[j].get(
                'class_name', getattr(tracks[i], 'class_name', 'vehicle')
            )
            matched_tracks.append(tracks[i])
            matched_dets.append(detections[j])

            iou_matrix[i, :] = -1
            iou_matrix[:, j] = -1

        unmatched_tracks = [t for t in tracks if t not in matched_tracks]
        unmatched_dets = [d for d in detections if d not in matched_dets]

        return unmatched_tracks, unmatched_dets


if __name__ == '__main__':
    # 测试代码
    tracker = VehicleTracker()

    # 模拟检测结果
    frame1_dets = [
        {'bbox': [100, 100, 200, 200], 'confidence': 0.9, 'class_name': 'car'},
        {'bbox': [300, 150, 400, 250], 'confidence': 0.85, 'class_name': 'bus'},
    ]

    frame2_dets = [
        {'bbox': [105, 105, 205, 205], 'confidence': 0.88, 'class_name': 'car'},
        {'bbox': [305, 155, 405, 255], 'confidence': 0.87, 'class_name': 'bus'},
    ]

    print("\n第1帧跟踪结果:")
    results1 = tracker.update(frame1_dets)
    for r in results1:
        print(f"  Track ID {r['track_id']}: {r['class_name']} at {r['bbox']}")

    print("\n第2帧跟踪结果:")
    results2 = tracker.update(frame2_dets)
    for r in results2:
        print(f"  Track ID {r['track_id']}: {r['class_name']} at {r['bbox']}")

    print("\n车辆跟踪器测试完成")
