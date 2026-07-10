@echo off
echo ========================================
echo Start FRPC (Local AI Computer)
echo ========================================
echo.
set FRP_DIR=E:\Intelligent-Transportation-System\tools\frp\frp_0.69.1_windows_amd64
set CONFIG=E:\Intelligent-Transportation-System\deploy\frp\frpc.local-ai.toml

if not exist "%FRP_DIR%\frpc.exe" (
  echo [ERROR] frpc.exe not found: %FRP_DIR%\frpc.exe
  echo Please re-download or re-extract the frp package.
  pause
  exit /b 1
)

if not exist "%CONFIG%" (
  echo [ERROR] config not found: %CONFIG%
  pause
  exit /b 1
)

cd /d "%FRP_DIR%"
.\frpc.exe -c "%CONFIG%"

pause
