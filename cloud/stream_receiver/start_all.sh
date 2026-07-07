#!/bin/bash
# 一键启动云端所有服务

PROJECT_ROOT="/root/S/Intelligent-Transportation-System"
CLOUD_DIR="$PROJECT_ROOT/cloud/stream_receiver"

echo "=========================================="
echo "云边端智慧交通系统 - 云端服务启动"
echo "=========================================="
echo ""

# 检查Python依赖
echo "检查Python依赖..."
pip3 list | grep -q flask-socketio
if [ $? -ne 0 ]; then
    echo "安装缺失的依赖..."
    pip3 install flask-cors flask-socketio python-socketio
fi

echo ""
echo "✅ 依赖检查完成"
echo ""

# 获取本机IP
IP=$(hostname -I | awk '{print $1}')
echo "📍 本机IP地址: $IP"
echo ""

echo "==================== 服务启动顺序 ===================="
echo ""
echo "1️⃣  启动 RTMP 服务器 (端口 1935)"
echo "2️⃣  启动云端主服务器 (端口 5000)"
echo ""
echo "边端需要使用的地址:"
echo "   - HTTP API: http://$IP:5000"
echo "   - RTMP推流: rtmp://$IP:1935/live/<device_id>"
echo ""
echo "前端需要使用的地址:"
echo "   - HTTP API: http://$IP:5000"
echo "   - WebSocket: ws://$IP:5000/socket.io/"
echo ""
echo "======================================================"
echo ""

read -p "按 Enter 键开始启动服务..."

echo ""
echo "🚀 启动 RTMP 服务器（后台运行）..."
cd "$CLOUD_DIR"
nohup ./start_rtmp_server.sh > rtmp_server.log 2>&1 &
RTMP_PID=$!
echo "   RTMP 服务器 PID: $RTMP_PID"
sleep 2

echo ""
echo "🚀 启动云端主服务器..."
cd "$CLOUD_DIR"
python3 main_server.py

echo ""
echo "服务已停止"
