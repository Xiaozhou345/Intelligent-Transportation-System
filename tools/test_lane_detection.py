"""
车道线检测测试脚本
"""

import cv2
import numpy as np
import sys
import os

# 添加路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CURRENT_DIR)
AI_MODELS_DIR = os.path.join(REPO_ROOT, "cloud", "ai_models")
sys.path.append(AI_MODELS_DIR)

from lane_detection import LaneDetector


def create_test_image_with_lanes():
    """创建一个带车道线的测试图像"""
    # 创建1920x1080的黑色图像（模拟道路）
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[:, :] = (50, 50, 50)  # 深灰色道路

    # 绘制3条白色竖直车道线
    lane_positions = [640, 960, 1280]  # 3条车道线，分割为4个车道

    for x in lane_positions:
        # 绘制白色虚线（模拟车道分隔线）
        for y in range(0, 1080, 40):
            cv2.line(img, (x, y), (x, y + 20), (255, 255, 255), 3)

    return img


def draw_lane_detection_result(img, lane_lines, lanes):
    """在图像上绘制检测结果"""
    result_img = img.copy()
    height, width = img.shape[:2]

    # 绘制检测到的车道线（红色竖线）
    for x in lane_lines:
        cv2.line(result_img, (x, 0), (x, height), (0, 0, 255), 2)
        cv2.putText(
            result_img,
            f"x={x}",
            (x + 5, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2
        )

    # 绘制车道区域（半透明覆盖）
    overlay = result_img.copy()
    colors = [
        (0, 255, 0),    # 绿色
        (255, 0, 0),    # 蓝色
        (0, 255, 255),  # 黄色
        (255, 0, 255),  # 紫色
        (255, 128, 0),  # 橙色
    ]

    for i, (lane_id, x_start, x_end) in enumerate(lanes):
        color = colors[i % len(colors)]
        cv2.rectangle(overlay, (x_start, 0), (x_end, height), color, -1)

        # 标注车道ID
        center_x = (x_start + x_end) // 2
        cv2.putText(
            result_img,
            f"Lane {lane_id}",
            (center_x - 40, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2
        )

    # 混合原图和半透明覆盖
    result_img = cv2.addWeighted(result_img, 0.7, overlay, 0.3, 0)

    return result_img


def test_lane_detector():
    """测试车道检测器"""
    print("=" * 60)
    print("车道线检测器测试")
    print("=" * 60)

    # 1. 创建测试图像
    print("\n1. 创建测试图像（带3条车道线）...")
    test_img = create_test_image_with_lanes()
    print(f"   图像尺寸: {test_img.shape}")

    # 2. 初始化车道检测器
    print("\n2. 初始化车道检测器...")
    detector = LaneDetector(
        min_line_length=100,
        max_line_gap=50,
        threshold=50,
        vertical_tolerance=15.0,
        cache_frames=10,
    )
    print("   ✅ 初始化成功")

    # 3. 检测车道线
    print("\n3. 检测车道线...")
    lane_lines = detector.detect_lane_lines(test_img)
    print(f"   检测到 {len(lane_lines)} 条车道线: {lane_lines}")

    # 4. 划分车道
    print("\n4. 划分车道区域...")
    width = test_img.shape[1]
    lanes = detector.divide_lanes(width, lane_lines)
    print(f"   划分为 {len(lanes)} 个车道:")
    for lane_id, x_start, x_end in lanes:
        print(f"     车道 {lane_id}: x={x_start} ~ {x_end} (宽度 {x_end - x_start}px)")

    # 5. 测试车辆归属判定
    print("\n5. 测试车辆车道归属判定...")
    test_vehicles = [
        (320, "车辆A"),
        (800, "车辆B"),
        (1100, "车辆C"),
        (1500, "车辆D"),
        (1800, "车辆E"),
    ]

    for vehicle_x, vehicle_name in test_vehicles:
        lane_id = detector.assign_vehicle_to_lane(vehicle_x, lanes)
        print(f"   {vehicle_name} (x={vehicle_x}) -> 车道 {lane_id}")

    # 6. 可视化结果
    print("\n6. 生成可视化结果...")
    result_img = draw_lane_detection_result(test_img, lane_lines, lanes)

    # 保存结果图像
    output_dir = os.path.join(REPO_ROOT, "data", "lane_detection_test")
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "lane_detection_result.jpg")
    cv2.imwrite(output_path, result_img)
    print(f"   ✅ 结果已保存: {output_path}")

    # 7. 测试时序平滑（多帧）
    print("\n7. 测试时序平滑（连续10帧）...")
    for i in range(10):
        # 模拟轻微抖动
        noisy_img = test_img.copy()
        lane_lines_frame = detector.detect_lane_lines(noisy_img)
        print(f"   帧 {i+1}: 检测到 {len(lane_lines_frame)} 条车道线: {lane_lines_frame}")

    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_lane_detector()
