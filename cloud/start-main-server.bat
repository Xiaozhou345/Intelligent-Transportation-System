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

REM RTX 3050 demo profile: 15 FPS input -> about 5 AI frames/s.
set "ITS_FRAME_SKIP=3"
set "ITS_CAPTURE_FRAME_SKIP=2"
set "ITS_PLATE_RECOGNITION_SKIP=2"
set "ITS_OVERLAY_PUSH_SKIP=1"
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
