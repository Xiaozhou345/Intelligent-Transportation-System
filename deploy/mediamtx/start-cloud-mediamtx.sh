#!/usr/bin/env bash
set -euo pipefail

MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-v1.19.2}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/mediamtx}"
PUBLIC_IP="${PUBLIC_IP:-106.54.10.11}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ ! -x "./mediamtx" ]; then
  ARCHIVE="mediamtx_${MEDIAMTX_VERSION}_linux_amd64.tar.gz"
  URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/${ARCHIVE}"
  echo "Downloading MediaMTX from ${URL}"
  wget -O "$ARCHIVE" "$URL"
  tar -xzf "$ARCHIVE"
  chmod +x ./mediamtx
fi

cp "$SCRIPT_DIR/cloud-mediamtx.yml" ./cloud-mediamtx.yml
sed -i "s/webrtcAdditionalHosts: \\[106.54.10.11\\]/webrtcAdditionalHosts: [${PUBLIC_IP}]/" ./cloud-mediamtx.yml

echo "Starting MediaMTX with PUBLIC_IP=${PUBLIC_IP}"
echo "SRT publish:  srt://${PUBLIC_IP}:8890?streamid=publish:live/mobile_001&latency=200"
echo "RTMP fallback: rtmp://${PUBLIC_IP}:1935/live/mobile_001"
echo "WHEP play:    http://${PUBLIC_IP}:8889/live/mobile_001/whep"
echo "RTSP pull:    rtsp://${PUBLIC_IP}:8554/live/mobile_001"

exec ./mediamtx ./cloud-mediamtx.yml
