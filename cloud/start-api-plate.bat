@echo off
echo ========================================
echo Cloud API Server (Plate Recognition)
echo ========================================
echo.
echo Starting HTTP API Service with Plate YOLO + LPRNet...
echo.

cd /d E:\Intelligent-Transportation-System\cloud\stream_receiver
python api_server_sandbox.py

pause
