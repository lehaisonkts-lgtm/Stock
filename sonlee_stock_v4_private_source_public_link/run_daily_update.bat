@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Chua co .venv. Hay chay run_pc.bat lan dau de cai moi truong.
  pause
  exit /b 1
)
.venv\Scripts\python.exe daily_update.py
pause
