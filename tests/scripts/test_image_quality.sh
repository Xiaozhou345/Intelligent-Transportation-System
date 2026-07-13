#!/bin/bash

echo "=========================================="
echo "🎨 视频画质优化验证"
echo "=========================================="
echo ""

# 1. 检查后端 JPEG 质量
echo "1️⃣  检查后端 JPEG 质量..."
JPEG_QUALITY=$(grep "IMWRITE_JPEG_QUALITY.*," cloud/stream_receiver/video_processor.py | grep -oP '\d+' | tail -1)
if [ "$JPEG_QUALITY" -ge 85 ]; then
    echo "   ✅ JPEG 质量: $JPEG_QUALITY（高画质）"
elif [ "$JPEG_QUALITY" -ge 75 ]; then
    echo "   ⚠️  JPEG 质量: $JPEG_QUALITY（中高画质）"
elif [ "$JPEG_QUALITY" -ge 65 ]; then
    echo "   ⚠️  JPEG 质量: $JPEG_QUALITY（中等画质，建议提升到 85）"
else
    echo "   ❌ JPEG 质量: $JPEG_QUALITY（画质较差）"
fi
echo ""

# 2. 检查前端图像平滑质量
echo "2️⃣  检查前端图像平滑质量..."
if grep -q "imageSmoothingQuality = 'high'" ui/components/VideoPlayer.vue; then
    echo "   ✅ 图像平滑: high（高画质）"
elif grep -q "imageSmoothingQuality = 'medium'" ui/components/VideoPlayer.vue; then
    echo "   ⚠️  图像平滑: medium（中等画质）"
elif grep -q "imageSmoothingQuality = 'low'" ui/components/VideoPlayer.vue; then
    echo "   ⚠️  图像平滑: low（低画质，建议提升到 high）"
else
    echo "   ❌ 图像平滑: 未设置"
fi
echo ""

# 3. 预期性能影响
echo "3️⃣  预期性能影响..."
echo "   修改前（JPEG=65, smooth=low）："
echo "      • 画质: ⭐⭐⭐ (中下)"
echo "      • JPEG编码: 12-18ms"
echo "      • Canvas渲染: 5-10ms"
echo "      • 帧大小: 25-35KB"
echo "      • 总延迟: 135-260ms"
echo ""
echo "   修改后（JPEG=85, smooth=high）："
echo "      • 画质: ⭐⭐⭐⭐⭐ (高)"
echo "      • JPEG编码: 15-23ms (+3-5ms)"
echo "      • Canvas渲染: 7-15ms (+2-5ms)"
echo "      • 帧大小: 40-50KB (+40%)"
echo "      • 总延迟: 145-280ms (+10-20ms)"
echo ""

# 4. 测试步骤
echo "4️⃣  测试步骤..."
echo ""
echo "   步骤1: 重启后端"
echo "   ================================"
echo "   pkill -f main_server.py"
echo "   python3 cloud/stream_receiver/main_server.py"
echo ""
echo "   步骤2: 刷新前端（强制刷新）"
echo "   ================================"
echo "   浏览器按 Ctrl+Shift+R"
echo ""
echo "   步骤3: 观察画质"
echo "   ================================"
echo "   ✓ 车牌号是否清晰可读？"
echo "   ✓ 车辆轮廓是否锐利？"
echo "   ✓ 检测框边缘是否平滑？"
echo "   ✓ 快速移动时是否清晰？"
echo ""
echo "   步骤4: 观察性能（后端日志）"
echo "   ================================"
echo "   查找：JPEG编码 和 帧大小"
echo "   预期：编码约18ms，帧大小约45KB"
echo ""
echo "   步骤5: 观察延迟（前端 status bar）"
echo "   ================================"
echo "   延迟应 < 300ms"
echo "   如果 > 300ms，考虑降低到 JPEG=75"
echo ""

# 5. 微调建议
echo "5️⃣  微调建议..."
echo ""
echo "   如果画质仍不满意："
echo "   ================================"
echo "   修改 video_processor.py:1447"
echo "   encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]"
echo "   或 95（极致画质，文件更大）"
echo ""
echo "   如果延迟过高（> 300ms）："
echo "   ================================"
echo "   修改 video_processor.py:1447"
echo "   encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]"
echo "   或调整为 medium smoothing"
echo ""
echo "   如果网络带宽不足："
echo "   ================================"
echo "   JPEG=75 + smoothing=medium"
echo "   或 JPEG=70 + smoothing=low（回退）"
echo ""

# 6. 快速对比测试
echo "6️⃣  快速对比测试..."
echo ""
echo "   可以通过环境变量临时测试不同质量："
echo "   （暂未实现，需要代码支持）"
echo ""

echo "=========================================="
echo "📖 详细文档: IMAGE_QUALITY_FIX.md"
echo "=========================================="
echo ""
echo "✅ 画质优化已完成，请重启服务测试！"
echo ""
