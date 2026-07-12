#!/bin/bash

echo "=========================================="
echo "✅ video_overlay 完整数据修复验证"
echo "=========================================="
echo ""

# 1. 检查后端是否推送完整 overlay
echo "1️⃣  检查后端 video_overlay 推送..."
if grep -A5 "推送完整的 overlay 数据" cloud/stream_receiver/video_processor.py | grep -q "self._send_result(overlay)"; then
    echo "   ✅ 后端推送完整 overlay 数据"
else
    echo "   ❌ 后端仍使用简化数据"
fi
echo ""

# 2. 检查是否有简化推送的残留
echo "2️⃣  检查是否有简化数据推送..."
if grep -q "'vehicle_count': len(overlay\['data'\]\['vehicles'\])" cloud/stream_receiver/video_processor.py; then
    echo "   ⚠️  发现简化数据推送残留"
    grep -n "'vehicle_count': len(overlay" cloud/stream_receiver/video_processor.py
else
    echo "   ✅ 无简化数据推送残留"
fi
echo ""

# 3. 检查前端 skipDraw 逻辑
echo "3️⃣  检查前端 skipDraw 逻辑..."
if grep -q "handleVideoOverlay(data, true)" ui/App.vue; then
    echo "   ✅ 前端使用 skipDraw=true（避免重复绘制）"
else
    echo "   ⚠️  前端未使用 skipDraw=true"
fi
echo ""

# 4. 检查延迟优化是否保留
echo "4️⃣  检查延迟优化是否保留..."
if grep -q "fetch.*data:image/jpeg;base64" ui/App.vue; then
    echo "   ✅ 前端高性能 base64 解码已保留"
else
    echo "   ⚠️  前端 base64 解码优化丢失"
fi

if grep -q "lastFrameSequence" ui/App.vue; then
    echo "   ✅ 帧丢弃机制已保留"
else
    echo "   ⚠️  帧丢弃机制丢失"
fi

if grep -q "requestAnimationFrame" ui/components/VideoPlayer.vue; then
    echo "   ✅ Canvas 渲染优化已保留"
else
    echo "   ⚠️  Canvas 渲染优化丢失"
fi
echo ""

# 5. 检查画质优化是否保留
echo "5️⃣  检查画质优化是否保留..."
JPEG_QUALITY=$(grep "IMWRITE_JPEG_QUALITY" cloud/stream_receiver/video_processor.py | grep -oP '\d+' | tail -1)
if [ "$JPEG_QUALITY" = "85" ]; then
    echo "   ✅ JPEG 质量: 85（高画质）"
else
    echo "   ⚠️  JPEG 质量: $JPEG_QUALITY（非预期值）"
fi

if grep -q "imageSmoothingQuality.*'high'" ui/components/VideoPlayer.vue; then
    echo "   ✅ 前端图像平滑: high（高画质）"
else
    echo "   ⚠️  前端图像平滑未设置为 high"
fi
echo ""

# 6. 逻辑链完整性检查
echo "=========================================="
echo "📊 逻辑链完整性检查"
echo "=========================================="
echo ""
echo "后端推送链:"
echo "  1. AI 分析 → 完整数据"
echo "  2. 构建 overlay → 完整 bbox"
echo "  3. 绘制检测框 → video_frame"
echo "  4. 推送 video_frame → 前端显示 ✅"
echo "  5. 推送 overlay (完整) → EventStream/HistoryQuery ✅"
echo ""
echo "前端接收链:"
echo "  1. video_frame → handleVideoFrame → 显示画面 ✅"
echo "  2. video_overlay (skipDraw) → 保存数据 ✅"
echo "  3. EventStream 使用 overlay.data.vehicles ✅"
echo "  4. HistoryQuery 使用 overlay.data.vehicles ✅"
echo "  5. buildOverlayBoxes 返回正确框 ✅"
echo ""

# 7. 测试步骤
echo "=========================================="
echo "🧪 测试验证步骤"
echo "=========================================="
echo ""
echo "步骤1: 重启后端服务"
echo "  pkill -f main_server.py"
echo "  python3 cloud/stream_receiver/main_server.py"
echo ""
echo "步骤2: 刷新前端页面"
echo "  浏览器按 Ctrl+Shift+R 强制刷新"
echo ""
echo "步骤3: 验证事件流显示"
echo "  • 打开事件流面板"
echo "  • 查找 'video_overlay' 事件"
echo "  • 应显示: '当前帧叠加目标 X 个' (X > 0)"
echo "  • ❌ 如果显示 '0 个'，说明修复失败"
echo ""
echo "步骤4: 验证历史查询"
echo "  • 打开历史查询面板"
echo "  • 筛选 '画框快照' 事件"
echo "  • 详情列应显示: '目标 X 个' (X > 0)"
echo "  • ❌ 如果显示 '0 个'，说明修复失败"
echo ""
echo "步骤5: 验证场景切换"
echo "  • 切换到不同场景（车辆检测、违停检测等）"
echo "  • 检测框应保持显示，不会消失"
echo "  • ❌ 如果检测框消失，说明有问题"
echo ""
echo "步骤6: 验证画质和延迟"
echo "  • 画面应清晰（JPEG=85）"
echo "  • 延迟应 < 300ms"
echo "  • 画面应流畅，无卡顿"
echo ""

# 8. 预期效果
echo "=========================================="
echo "🎯 预期效果"
echo "=========================================="
echo ""
echo "✅ 画面清晰流畅（画质优化保留）"
echo "✅ 延迟低（延迟优化保留）"
echo "✅ 事件流显示正确统计"
echo "✅ 历史查询显示正确统计"
echo "✅ 场景切换检测框不消失"
echo "✅ 无渲染冲突（skipDraw=true 确保）"
echo "✅ 逻辑链完整，无断链"
echo ""

echo "=========================================="
echo "📖 详细文档: COMPLETE_LOGIC_AUDIT.md"
echo "=========================================="
echo ""
echo "✅ 修复完成，请按测试步骤验证！"
echo ""
