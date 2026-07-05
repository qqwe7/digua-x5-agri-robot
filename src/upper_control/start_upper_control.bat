@echo off
setlocal
cd /d "%~dp0"

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
  echo Install Python 3, then run this script again.
  pause
  exit /b 1
)

if "%UPPER_CONTROL_HOST%"=="" (
  set "UPPER_CONTROL_HOST=0.0.0.0"
)
if "%UPPER_DEVICE_TIMEOUT_SECONDS%"=="" (
  set "UPPER_DEVICE_TIMEOUT_SECONDS=60"
)

%PYTHON_EXE% %PYTHON_ARGS% -c "import socket,sys;s=socket.socket();s.settimeout(1);sys.exit(0 if s.connect_ex(('127.0.0.1',8765))==0 else 1)" >nul 2>nul
if %errorlevel%==0 (
  echo [INFO] Upper control server is already running.
  echo [INFO] Opening http://127.0.0.1:8765
  start "" "http://127.0.0.1:8765"
  timeout /t 2 /nobreak >nul
  exit /b 0
)

echo [INFO] Starting upper control server in background...
echo [INFO] Listen host: %UPPER_CONTROL_HOST%
echo [INFO] Device heartbeat timeout: %UPPER_DEVICE_TIMEOUT_SECONDS%s
echo [INFO] Logs:
echo        %~dp0standalone.out.log
echo        %~dp0standalone.err.log

del "%~dp0standalone.out.log" >nul 2>nul
del "%~dp0standalone.err.log" >nul 2>nul

start "Upper Control Server" /min "%~dp0run_upper_control_server.bat"

echo [INFO] Waiting for server...
for /l %%i in (1,1,20) do (
  %PYTHON_EXE% %PYTHON_ARGS% -c "import socket,sys;s=socket.socket();s.settimeout(1);sys.exit(0 if s.connect_ex(('127.0.0.1',8765))==0 else 1)" >nul 2>nul
  if not errorlevel 1 (
    echo [INFO] Server is ready.
    echo [INFO] Opening http://127.0.0.1:8765
    start "" "http://127.0.0.1:8765"
    timeout /t 2 /nobreak >nul
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)

echo [ERROR] Server did not start within 20 seconds.
echo [ERROR] Please check standalone.err.log.
type "%~dp0standalone.err.log" 2>nul
pause
exit /b 1
