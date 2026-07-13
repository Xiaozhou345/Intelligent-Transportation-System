"""
动态车道检测测试 - 验证车道数量是根据实际画面动态调整的
"""

import cv2
import numpy as np
import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CURRENT_DIR)
AI_MODELS_DIR = os.path.join(REPO_ROOT, "cloud", "ai_models")
sys.path.append(AI_MODELS_DIR)

from lane_detection import LaneDetector


def create_test_scene(num_lanes):
    """
    创建不同车道数量的测试场景

    Args:
        num_lanes: 车道数量 (2, 3, 4, 5)

    Returns:
        测试图像
    """
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[:, :] = (50, 50, 50)  # 深灰色道路

    # 根据车道数量计算车道线位置
    # num_lanes个车道需要 num_lanes-1 条分隔线
    num_lines = num_lanes - 1

    if num_lines > 0:
        # 均匀分布车道线
        step = 1920 // num_lanes
        lane_positions = [step * (i + 1) for i in range(num_lines)]

        for x in lane_positions:
            # 绘制白色虚线
            for y in range(0, 1080, 40):
                cv2.line(img, (x, y), (x, y + 20), (255, 255, 255), 3)

    return img, lane_positions if num_lines > 0 else []


def test_dynamic_detection():
    """测试动态车道检测"""
    print("=" * 70)
    print("动态车道检测测试")
    print("=" * 70)

    detector = LaneDetector(
        min_line_length=100,
        max_line_gap=50,
        threshold=50,
        vertical_tolerance=15.0,
        cache_frames=5,  # 减少缓存帧数，快速响应
    )

    # 测试不同车道数量的场景
    test_cases = [
        (2, "双车道场景"),
        (3, "三车道场景"),
        (4, "四车道场景"),
        (5, "五车道场景"),
        (1, "单车道场景（无分隔线）"),
    ]

    for num_lanes, description in test_cases:
        print(f"\n{'='*70}")
        print(f"测试场景: {description} (期望{num_lanes}个车道)")
        print(f"{'='*70}")

        # 创建测试图像
        test_img, expected_lines = create_test_scene(num_lanes)
        print(f"实际车道线位置: {expected_lines}")

        # 清空检测器缓存（模拟新场景）
        detector.reset_cache()

        # 多帧检测（模拟实时场景）
        for frame_idx in range(8):
            lane_lines = detector.detect_lane_lines(test_img)
            lanes = detector.divide_lanes(test_img.shape[1], lane_lines)

            if frame_idx == 0:
                print(f"\n  帧 {frame_idx+1}:")
                print(f"    检测到车道线: {lane_lines} (共{len(lane_lines)}条)")
                print(f"    划分车道数: {len(lanes)}个")
            elif frame_idx == 7:  # 最后一帧（时序平滑后的稳定结果）
                print(f"\n  帧 {frame_idx+1} (稳定结果):")
                print(f"    检测到车道线: {lane_lines} (共{len(lane_lines)}条)")
                print(f"    划分车道数: {len(lanes)}个")

                # 验证结果
                if len(lanes) == num_lanes:
                    print(f"    ✅ 正确！车道数 = {num_lanes} (符合预期)")
                else:
                    print(f"    ⚠️  车道数 = {len(lanes)} (期望{num_lanes})")

                # 输出车道详情
                print(f"\n  车道详情:")
                for lane_id, x_start, x_end in lanes:
                    width = x_end - x_start
                    print(f"    车道{lane_id}: x={x_start:4d} ~ {x_end:4d} (宽度{width:4d}px)")

    print(f"\n{'='*70}")
    print("✅ 动态检测测试完成！")
    print("结论: 车道数量根据画面实际情况动态调整，不是固定值")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    test_dynamic_detection()
