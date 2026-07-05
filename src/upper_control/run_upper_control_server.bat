@echo off
setlocal
cd /d "%~dp0"

if "%UPPER_CONTROL_HOST%"=="" (
  set "UPPER_CONTROL_HOST=0.0.0.0"
)
if "%UPPER_DEVICE_TIMEOUT_SECONDS%"=="" (
  set "UPPER_DEVICE_TIMEOUT_SECONDS=60"
)

set "PYTHON_EXE="
set "PYTHON_ARGS="
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
  )
)

if "%PYTHON_EXE%"=="" (
  echo [ERROR] Python was not found in PATH.
  pause
  exit /b 1
)

echo [INFO] Upper control service window. Keep this window open.
echo [INFO] Open http://127.0.0.1:8765 in your browser.
echo [INFO] Listen host: %UPPER_CONTROL_HOST%
echo [INFO] Device heartbeat timeout: %UPPER_DEVICE_TIMEOUT_SECONDS%s
echo [INFO] Logs are also written to standalone.out.log and standalone.err.log.

%PYTHON_EXE% %PYTHON_ARGS% "%~dp0standalone_server.py" >> "%~dp0standalone.out.log" 2>> "%~dp0standalone.err.log"

echo [ERROR] Server stopped. Check standalone.err.log.
pause
