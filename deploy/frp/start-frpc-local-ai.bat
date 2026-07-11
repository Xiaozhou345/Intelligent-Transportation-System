@echo off
echo ========================================
echo Start FRPC (Local AI Computer)
echo ========================================
echo.
set "FRP_DIR=D:\frp\restore\frp_0.69.1_windows_amd64"
set "CONFIG=%~dp0frpc.local-ai.toml"

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
