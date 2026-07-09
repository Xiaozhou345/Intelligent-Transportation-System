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

cd /d E:\Intelligent-Transportation-System\cloud\stream_receiver
python main_server.py

pause
