#!/bin/bash
# 启动RTMP服务器（MediaMTX）

echo "=========================================="
echo "启动 RTMP 服务器 (MediaMTX)"
echo "=========================================="

# 检查是否已下载MediaMTX
if [ ! -f "/tmp/mediamtx" ]; then
    echo "正在下载 MediaMTX..."
    cd /tmp
    wget -q https://github.com/bluenviron/mediamtx/releases/download/v1.9.3/mediamtx_v1.9.3_linux_amd64.tar.gz
    tar -xzf mediamtx_v1.9.3_linux_amd64.tar.gz
    chmod +x mediamtx
    echo "MediaMTX 下载完成"
fi

# 创建配置文件
cat > /tmp/mediamtx.yml << 'EOF'
# MediaMTX 配置文件

# RTMP服务器配置
rtmp: yes
rtmpAddress: :1935

# HLS配置
hls: yes
hlsAddress: :8888

# WebRTC配置（可选）
webrtc: no

# 日志级别
logLevel: info

# 路径配置
paths:
  all:
    # 允许所有来源推流
    publishUser: ""
    publishPass: ""
    publishIPs: []

    # 允许所有来源拉流
    readUser: ""
    readPass: ""
    readIPs: []
EOF

echo ""
echo "✅ RTMP 服务配置:"
echo "   - 监听端口: 1935"
echo "   - HLS 端口: 8888"
echo "   - 推流地址: rtmp://<你的IP>:1935/live/<stream_name>"
echo ""
echo "边端推流示例:"
echo "   rtmp://192.168.1.100:1935/live/mobile_001"
echo ""
echo "正在启动服务器..."
echo "=========================================="
echo ""

# 启动MediaMTX
cd /tmp
./mediamtx /tmp/mediamtx.yml
