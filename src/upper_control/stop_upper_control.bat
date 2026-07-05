@echo off
setlocal

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765"') do (
  echo [INFO] Stopping process %%p on port 8765...
  taskkill /PID %%p /F >nul 2>nul
)

echo [INFO] Done. You can run start_upper_control.bat again.
pause
