@echo off
setlocal

set "ITS_FRAME_SKIP=3"
set "ITS_CAPTURE_FRAME_SKIP=2"
set "ITS_PLATE_RECOGNITION_SKIP=2"
set "ITS_OVERLAY_PUSH_SKIP=1"
set "ITS_ENABLE_FP16=true"
set "OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp"
set "ITS_STREAM_STALL_TIMEOUT=8"
set "ITS_STREAM_FAILURE_GRACE=6"
set "ITS_PORT=5001"

set "ITS_PYTHON_EXE=D:\Python\python.exe"
if not exist "%ITS_PYTHON_EXE%" set "ITS_PYTHON_EXE=python"

cd /d "%~dp0stream_receiver"
"%ITS_PYTHON_EXE%" -u main_server.py 1>"%~dp0main_server.gpu.v2.log" 2>"%~dp0main_server.gpu.v2.err.log"
