#!/usr/bin/env bash
set -euo pipefail
ROOT="/root/S/Intelligent-Transportation-System"
FRP_DIR="$ROOT/tools/frp_linux/frp_0.69.1_linux_amd64"
CONFIG="$ROOT/deploy/frp/frpc.local-ai.toml"

if [[ ! -x "$FRP_DIR/frpc" ]]; then
  echo "[ERROR] frpc not found: $FRP_DIR/frpc"
  echo "Please re-download or re-extract the Linux frp package."
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "[ERROR] config not found: $CONFIG"
  exit 1
fi

cd "$FRP_DIR"
./frpc -c "$CONFIG"
