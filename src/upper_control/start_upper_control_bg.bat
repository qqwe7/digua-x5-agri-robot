@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Launching upper control server.
call "%~dp0start_upper_control.bat"
endlocal
