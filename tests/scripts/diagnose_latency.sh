#!/bin/bash

echo "=========================================="
echo "🔍 前端延迟诊断工具"
echo "=========================================="
echo ""

# 1. 检查后端进程
echo "1️⃣  检查后端服务状态..."
if pgrep -f "main_server.py" > /dev/null; then
    echo "   ✅ 后端服务运行中"
    BACKEND_PID=$(pgrep -f "main_server.py")
    echo "   📌 进程ID: $BACKEND_PID"
else
    echo "   ❌ 后端服务未运行"
    echo "   💡 启动命令: python3 cloud/stream_receiver/main_server.py"
fi
echo ""

# 2. 检查前端进程
echo "2️⃣  检查前端服务状态..."
if pgrep -f "vite" > /dev/null; then
    echo "   ✅ 前端服务运行中"
else
    echo "   ❌ 前端服务未运行"
    echo "   💡 启动命令: cd ui && npm run dev"
fi
echo ""

# 3. 检查网络端口
echo "3️⃣  检查端口占用..."
for port in 5001 5173 8888 8889; do
    if netstat -tuln 2>/dev/null | grep ":$port " > /dev/null; then
        echo "   ✅ 端口 $port 已监听"
    else
        echo "   ⚠️  端口 $port 未监听"
    fi
done
echo ""

# 4. 检查环境变量
echo "4️⃣  检查性能配置..."
echo "   ITS_FRAME_SKIP=${ITS_FRAME_SKIP:-未设置 (默认=1)}"
echo "   ITS_OVERLAY_PUSH_SKIP=${ITS_OVERLAY_PUSH_SKIP:-未设置 (默认=1)}"
echo "   ITS_VEHICLE_CONF=${ITS_VEHICLE_CONF:-未设置 (默认=0.50)}"
echo "   ITS_PLATE_RECOGNITION_SKIP=${ITS_PLATE_RECOGNITION_SKIP:-未设置 (默认=3)}"
echo ""

# 5. 推荐配置
echo "5️⃣  推荐低延迟配置..."
echo "   export ITS_FRAME_SKIP=2          # 处理一半的帧，降低负载"
echo "   export ITS_OVERLAY_PUSH_SKIP=1   # 每帧都推送，保持流畅"
echo "   export ITS_VEHICLE_CONF=0.40     # 降低阈值，提高检测率"
echo "   export ITS_PLATE_RECOGNITION_SKIP=999  # 禁用车牌识别，极限性能"
echo ""

# 6. 检查前端修复
echo "6️⃣  检查前端优化状态..."
if grep -q "fetch.*data:image/jpeg;base64" ui/App.vue 2>/dev/null; then
    echo "   ✅ 前端 base64 解码已优化（使用 fetch data URI）"
else
    echo "   ⚠️  前端 base64 解码未优化"
fi

if grep -q "lastFrameSequence" ui/App.vue 2>/dev/null; then
    echo "   ✅ 帧丢弃机制已启用"
else
    echo "   ⚠️  帧丢弃机制未启用"
fi

if grep -q "requestAnimationFrame" ui/components/VideoPlayer.vue 2>/dev/null; then
    echo "   ✅ Canvas 渲染已优化（使用 requestAnimationFrame）"
else
    echo "   ⚠️  Canvas 渲染未优化"
fi
echo ""

# 7. 性能测试建议
echo "7️⃣  性能测试步骤..."
echo "   1. 启动后端: python3 cloud/stream_receiver/main_server.py"
echo "   2. 启动前端: cd ui && npm run dev"
echo "   3. 打开浏览器: http://localhost:5173"
echo "   4. 观察前端延迟显示（status bar）"
echo "   5. 观察后端性能日志（每30帧输出）"
echo ""

# 8. 问题排查
echo "8️⃣  常见问题排查..."
echo "   问题1: 画面延迟 > 300ms"
echo "      → 检查后端总耗时（应 < 150ms）"
echo "      → 检查网络带宽（局域网应 > 10Mbps）"
echo "      → 尝试 ITS_FRAME_SKIP=3 降低处理频率"
echo ""
echo "   问题2: 画面卡顿、不流畅"
echo "      → 检查前端是否启用帧丢弃机制"
echo "      → 检查 Chrome DevTools → Performance"
echo "      → 尝试 ITS_OVERLAY_PUSH_SKIP=2"
echo ""
echo "   问题3: 检测框位置滞后"
echo "      → 检查后端是否使用 get_detection_bbox()"
echo "      → 检查是否禁用了车牌识别"
echo "      → 尝试降低 JPEG 质量到 55"
echo ""

echo "=========================================="
echo "📖 详细文档: LATENCY_ANALYSIS.md"
echo "=========================================="
