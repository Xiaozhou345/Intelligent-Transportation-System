#!/usr/bin/env python3
"""
违停检测诊断工具
用于排查违停检测不工作的原因
"""

import json
import sys
import os

# 读取配置
config_path = "cloud/stream_receiver/illegal_parking_config.json"
if not os.path.exists(config_path):
    print(f"❌ 配置文件不存在: {config_path}")
    sys.exit(1)

with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

default_config = config.get('default', {})
no_parking_zones = default_config.get('no_parking_zones', [])
parking_pixel_threshold = default_config.get('parking_stationary_pixel_threshold', 18)
parking_min_history = default_config.get('parking_min_history', 3)
parking_grace_frames = default_config.get('parking_release_grace_frames', 3)

print("=" * 60)
print("违停检测配置诊断")
print("=" * 60)
print()

print(f"📋 配置文件: {config_path}")
print(f"📊 禁停区数量: {len(no_parking_zones)}")
print()

if len(no_parking_zones) == 0:
    print("❌ 错误: 未配置任何禁停区！")
    sys.exit(1)

print("禁停区配置详情：")
print("-" * 60)

for idx, zone in enumerate(no_parking_zones, 1):
    zone_id = zone.get('zone_id', 'unknown')
    zone_name = zone.get('name', zone_id)
    polygon = zone.get('polygon', [])
    threshold = zone.get('threshold_seconds', 30)
    cooldown = zone.get('cooldown_seconds', 10)

    print(f"\n{idx}. {zone_name} (ID: {zone_id})")
    print(f"   - 停留阈值: {threshold} 秒")
    print(f"   - 冷却时间: {cooldown} 秒")
    print(f"   - 多边形顶点数: {len(polygon)}")

    if len(polygon) < 3:
        print(f"   ❌ 错误: 多边形顶点数少于3个，无法形成区域！")
        continue

    # 检查坐标是否为归一化坐标 (0-1) 还是像素坐标
    is_normalized = all(0 <= x <= 1 and 0 <= y <= 1 for x, y in polygon)

    if is_normalized:
        print(f"   ✓ 坐标类型: 归一化坐标 (0-1)")
        print(f"   - 顶点坐标:")
        for i, (x, y) in enumerate(polygon):
            print(f"     [{i}] ({x:.4f}, {y:.4f})")

        # 假设分辨率为 1280x720，计算像素坐标
        print(f"\n   假设分辨率 1280x720，像素坐标为:")
        for i, (x, y) in enumerate(polygon):
            px = int(x * 1280)
            py = int(y * 720)
            print(f"     [{i}] ({px}, {py})")
    else:
        print(f"   ✓ 坐标类型: 像素坐标")
        print(f"   - 顶点坐标:")
        for i, (x, y) in enumerate(polygon):
            print(f"     [{i}] ({int(x)}, {int(y)})")

print()
print("-" * 60)
print()

print("静止判断参数：")
print(f"  - 像素位移阈值: {parking_pixel_threshold} 像素")
print(f"  - 最小历史帧数: {parking_min_history} 帧")
print(f"  - 宽限帧数: {parking_grace_frames} 帧")
print()

print("=" * 60)
print("可能导致违停检测不工作的原因：")
print("=" * 60)
print()

issues = []

# 检查阈值是否合理
for zone in no_parking_zones:
    threshold = zone.get('threshold_seconds', 30)
    if threshold > 10:
        issues.append(f"⚠️  {zone.get('name')} 的停留阈值 ({threshold}秒) 可能过长")

# 检查静止阈值
if parking_pixel_threshold > 50:
    issues.append(f"⚠️  静止判断阈值 ({parking_pixel_threshold}px) 可能过大，车辆需要几乎完全不动")
elif parking_pixel_threshold < 10:
    issues.append(f"⚠️  静止判断阈值 ({parking_pixel_threshold}px) 可能过小，可能误判为非静止")

# 检查最小历史帧数
if parking_min_history > 5:
    issues.append(f"⚠️  最小历史帧数 ({parking_min_history}) 可能过大，需要更长时间才能判断为静止")

if len(issues) == 0:
    print("✓ 未发现明显配置问题")
else:
    for issue in issues:
        print(issue)

print()
print("=" * 60)
print("诊断建议：")
print("=" * 60)
print()

print("1. 确认车辆是否在禁停区内：")
print("   - 检查截图中车辆的位置坐标")
print("   - 对比上面显示的禁停区像素坐标范围")
print()

print("2. 确认停留时间是否足够：")
for zone in no_parking_zones:
    print(f"   - {zone.get('name')}: 需要停留 ≥ {zone.get('threshold_seconds', 30)} 秒")
print()

print("3. 确认车辆是否真的静止：")
print(f"   - 车辆在最近 {parking_min_history} 帧内的位移必须 ≤ {parking_pixel_threshold} 像素")
print()

print("4. 查看后端日志：")
print("   - 启动后应该看到: '🚨 违停监控初始化: 配置了 X 个禁停区'")
print("   - 车辆进入禁停区时: '🚨 track_id=X 进入禁停区 XXX'")
print("   - 停留监控过程中: '🚨 track_id=X 在 XXX: 停留X.Xs/Y.Ys'")
print("   - 触发告警时: '🚨🚨🚨 违停告警触发'")
print()

print("5. 快速测试建议：")
print("   - 临时修改配置，降低阈值进行测试：")
print('     "threshold_seconds": 2  # 改为2秒')
print('     "parking_stationary_pixel_threshold": 50  # 改为50像素（更宽松）')
print()
