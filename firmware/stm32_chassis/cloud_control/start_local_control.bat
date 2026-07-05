@echo off
setlocal
cd /d "%~dp0"
title Local Car Web Control
python "%~dp0local_control.py"
if errorlevel 1 (
  echo.
  echo Local control exited with an error.
  pause
)
