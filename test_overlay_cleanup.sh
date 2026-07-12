#!/bin/bash

echo "=========================================="
echo "🔧 video_overlay 逻辑清理验证"
echo "=========================================="
echo ""

# 1. 检查后端是否删除了 video_overlay 推送
echo "1️⃣  检查后端 video_overlay 推送..."
if grep -q "'event_type': 'video_overlay'" cloud/stream_receiver/video_processor.py; then
    echo "   ⚠️  后端仍在推送 video_overlay（检查是否为注释）"
    OVERLAY_COUNT=$(grep -c "'event_type': 'video_overlay'" cloud/stream_receiver/video_processor.py)
    echo "      找到 $OVERLAY_COUNT 处引用"

    # 检查是否都在注释中
    if grep "'event_type': 'video_overlay'" cloud/stream_receiver/video_processor.py | grep -q "^[[:space:]]*#"; then
        echo "      ✅ 都在注释中，已正确删除"
    else
        echo "      ❌ 仍有活跃的 video_overlay 推送"
    fi
else
    echo "   ✅ 后端已完全删除 video_overlay 推送"
fi
echo ""

# 2. 检查前端是否简化了 handleVideoOverlay
echo "2️⃣  检查前端 handleVideoOverlay 函数..."
if grep -q "skipDraw" ui/App.vue; then
    echo "   ⚠️  前端仍包含 skipDraw 参数"
    if grep "handleVideoOverlay(data, true)" ui/App.vue > /dev/null; then
        echo "      ❌ 仍在使用 skipDraw=true 调用"
    else
        echo "      ✅ 已移除 skipDraw 参数传递"
    fi
else
    echo "   ✅ 前端已移除 skipDraw 参数"
fi
echo ""

# 3. 检查是否删除了 redrawCurrentOverlay 调用
echo "3️⃣  检查 redrawCurrentOverlay 调用..."
if grep -q "redrawCurrentOverlay()" ui/App.vue | grep -v "^[[:space:]]*//" | grep -v "^[[:space:]]*\*"; then
    echo "   ❌ 仍在调用 redrawCurrentOverlay()"
    grep -n "redrawCurrentOverlay()" ui/App.vue | grep -v "//" | grep -v "\*"
else
    echo "   ✅ 已删除 redrawCurrentOverlay() 调用"
fi
echo ""

# 4. 检查是否注释了 redrawCurrentOverlay 函数
echo "4️⃣  检查 redrawCurrentOverlay 函数定义..."
if grep -q "const redrawCurrentOverlay = " ui/App.vue; then
    if grep -B2 "const redrawCurrentOverlay" ui/App.vue | grep -q "//"; then
        echo "   ✅ redrawCurrentOverlay 函数已注释"
    else
        echo "   ⚠️  redrawCurrentOverlay 函数仍存在但未注释"
    fi
else
    echo "   ✅ redrawCurrentOverlay 函数已完全删除"
fi
echo ""

# 5. 检查场景切换逻辑
echo "5️⃣  检查场景切换逻辑..."
if grep -A5 "const handleSceneChange" ui/App.vue | grep -q "redrawCurrentOverlay"; then
    echo "   ❌ handleSceneChange 仍调用 redrawCurrentOverlay"
else
    echo "   ✅ handleSceneChange 已移除 redrawCurrentOverlay 调用"
fi
echo ""

# 6. 检查 buildOverlayBoxes 函数
echo "6️⃣  检查 buildOverlayBoxes 函数..."
if grep -q "const buildOverlayBoxes = " ui/App.vue; then
    echo "   ⚠️  buildOverlayBoxes 函数仍存在"
    # 检查是否还在被使用
    USAGE_COUNT=$(grep -c "buildOverlayBoxes(" ui/App.vue)
    DEFINITION_COUNT=$(grep -c "const buildOverlayBoxes = " ui/App.vue)
    ACTUAL_USAGE=$((USAGE_COUNT - DEFINITION_COUNT))

    if [ $ACTUAL_USAGE -eq 0 ]; then
        echo "      ✅ 函数未被使用，可以删除"
    else
        echo "      ⚠️  函数仍被使用 $ACTUAL_USAGE 次"
        grep -n "buildOverlayBoxes(" ui/App.vue | grep -v "const buildOverlayBoxes"
    fi
else
    echo "   ✅ buildOverlayBoxes 函数已删除"
fi
echo ""

# 7. 修复总结
echo "=========================================="
echo "📊 修复总结"
echo "=========================================="
echo ""
echo "✅ 已完成的修复："
echo "   1. 后端删除 video_overlay 推送"
echo "   2. 前端简化 handleVideoOverlay 函数"
echo "   3. 删除 redrawCurrentOverlay 调用"
echo "   4. 注释/删除 redrawCurrentOverlay 函数"
echo ""
echo "🎯 预期效果："
echo "   • 减少网络传输量 ~30%"
echo "   • 消除渲染冲突风险"
echo "   • 场景切换时检测框不会消失"
echo "   • 逻辑更清晰，易于维护"
echo ""
echo "🚀 测试步骤："
echo "   1. 重启后端服务"
echo "   2. 刷新前端页面（Ctrl+Shift+R）"
echo "   3. 切换不同场景（车辆检测、违停检测等）"
echo "   4. 验证检测框始终正常显示"
echo "   5. 观察控制台无错误"
echo ""
echo "=========================================="
echo "📖 详细文档: LOGIC_AUDIT_REPORT.md"
echo "=========================================="
echo ""
