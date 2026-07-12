@echo off
echo ========================================
echo Cloud Main Server (Traffic + Tracking)
echo ========================================
echo.
echo Starting integrated main_server.py ...
echo This server provides:
echo   - vehicle_detection
echo   - traffic_density
echo   - illegal_parking
echo   - road_anomaly
echo.

REM RTX 3050 demo profile: sample once in capture worker, then analyze every received frame.
REM 15 FPS input -> about 7.5 fresh AI frames/s without a second skip layer.
set "ITS_FRAME_SKIP=1"
set "ITS_CAPTURE_FRAME_SKIP=2"
set "ITS_PLATE_RECOGNITION_SKIP=2"
set "ITS_OVERLAY_PUSH_SKIP=1"
set "ITS_PLATE_IN_VEHICLE_SCENE=false"
set "ITS_FRAME_LOG_EVERY=30"
set "ITS_PERF_LOG_EVERY=30"
set "ITS_ANOMALY_AUTO_START=true"
set "ITS_ANOMALY_BACKEND=dino_reference"
set "ITS_DINO_MODEL=dinov2_vits14_reg"
set "ITS_DINO_IMAGE_SIZE=518"
set "ITS_DINO_HEAT_THRESHOLD=0.18"
set "ITS_DINO_PIXEL_THRESHOLD=0.14"
set "ITS_DINO_CAMERA_CHANGE_RATIO=0.30"
set "ITS_DINO_ALLOW_BG_VEHICLES=false"
set "ITS_DINO_MAX_CANDIDATES=1"
set "ITS_VEHICLE_MASK_MIN_CONF=0.75"
set "ITS_WARMUP_MODELS=true"
set "ITS_WARMUP_WIDTH=1280"
set "ITS_WARMUP_HEIGHT=720"
set "ITS_ENABLE_FP16=true"
set "OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp"
set "ITS_STREAM_STALL_TIMEOUT=8"
set "ITS_STREAM_FAILURE_GRACE=6"
set "ITS_PORT=5001"

cd /d "%~dp0stream_receiver"
if not defined ITS_PYTHON_EXE (
    if exist "D:\Python\python.exe" (
        set "ITS_PYTHON_EXE=D:\Python\python.exe"
    ) else (
        set "ITS_PYTHON_EXE=python"
    )
)

echo Python: %ITS_PYTHON_EXE%
"%ITS_PYTHON_EXE%" -u main_server.py

pause
