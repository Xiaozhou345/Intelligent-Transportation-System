#!/bin/bash
# 启动 MediaMTX 流媒体服务

echo "=========================================="
echo "启动 MediaMTX 流媒体服务"
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

# RTMP 兼容接收配置
rtmp: yes
rtmpAddress: :1935

# HLS配置
hls: yes
hlsAddress: :8888
hlsAllowOrigins: ["*"]
hlsAlwaysRemux: yes
hlsVariant: lowLatency
hlsSegmentCount: 7
hlsSegmentDuration: 1s
hlsPartDuration: 200ms
hlsSegmentMaxSize: 50M

# WebRTC WHIP/WHEP 配置
webrtc: yes
webrtcAddress: :8889
webrtcAllowOrigins: ["*"]
webrtcAdditionalHosts: [106.54.10.11]
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: ""

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
echo "✅ MediaMTX 服务配置:"
echo "   - RTMP 兼容端口: 1935"
echo "   - HLS 端口: 8888"
echo "   - HLS 模式: Low-Latency HLS (1s segment / 200ms part)"
echo "   - WebRTC WHIP/WHEP 端口: 8889"
echo "   - WebRTC UDP 媒体端口: 8189"
echo "   - RTSP 取帧端口: 8554"
echo "   - WHIP 推流地址: http://<你的IP>:8889/live/<stream_name>/whip"
echo "   - WHEP 播放地址: http://<你的IP>:8889/live/<stream_name>/whep"
echo ""
echo "边端推流示例（推荐 WebRTC/WHIP）:"
echo "   http://192.168.1.100:8889/live/mobile_001/whip"
echo "RTMP 兜底示例:"
echo "   rtmp://192.168.1.100:1935/live/mobile_001"
echo ""
echo "正在启动服务器..."
echo "=========================================="
echo ""

# 启动MediaMTX
cd /tmp
./mediamtx /tmp/mediamtx.yml
