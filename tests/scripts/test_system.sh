#!/bin/bash
# 智慧交通系统测试脚本 - 验证三个问题的修复

set -e

echo "=========================================="
echo "智慧交通系统启动脚本"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查是否在正确的目录
if [ ! -f "cloud/stream_receiver/main_server.py" ]; then
    echo -e "${RED}错误: 请在项目根目录运行此脚本${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 当前目录正确${NC}"
echo ""

# 设置环境变量
export ITS_DB_PASSWORD=${ITS_DB_PASSWORD:-mysql2026}
export ITS_VEHICLE_COOLDOWN=${ITS_VEHICLE_COOLDOWN:-30}
export ITS_PLATE_COOLDOWN=${ITS_PLATE_COOLDOWN:-30}

echo "环境变量配置："
echo "  - ITS_DB_PASSWORD: ${ITS_DB_PASSWORD}"
echo "  - ITS_VEHICLE_COOLDOWN: ${ITS_VEHICLE_COOLDOWN}秒"
echo "  - ITS_PLATE_COOLDOWN: ${ITS_PLATE_COOLDOWN}秒"
echo ""

echo -e "${YELLOW}提示: 本脚本只启动后端服务${NC}"
echo -e "${YELLOW}前端需要在另一个终端手动启动:${NC}"
echo -e "  cd ui && npm run dev -- --host 0.0.0.0"
echo ""

echo -e "${YELLOW}设备注册命令（后端启动后执行）:${NC}"
echo 'curl -X POST http://127.0.0.1:5001/api/register_device \'
echo "  -H \"Content-Type: application/json\" \\"
echo '  -d '"'"'{
    "device_id": "mobile_001",
    "stream_url": "rtsp://106.54.10.11:8554/live/mobile_001",
    "resolution": "1280x720",
    "fps": 15,
    "scene_id": "scene_704_sandbox",
    "device_type": "huawei_tablet",
    "codec": "H.264",
    "bitrate": "1.5Mbps"
  }'"'"
echo ""

read -p "按回车键启动后端服务..."

echo ""
echo "=========================================="
echo "启动后端服务..."
echo "=========================================="
echo ""

# 启动后端
cd /root/S/Intelligent-Transportation-System
python3 cloud/stream_receiver/main_server.py
