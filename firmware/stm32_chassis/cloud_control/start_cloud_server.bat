@echo off
setlocal
cd /d "%~dp0"
title Cloud Car Server
python "%~dp0server.py" --bind 0.0.0.0 --http-port 8080 --tcp-port 9000 --token yourtoken
if errorlevel 1 (
  echo.
  echo Cloud server exited with an error.
  pause
)
