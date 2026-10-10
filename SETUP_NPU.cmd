@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_NPU.ps1"
if errorlevel 1 (
  echo NPU setup failed. Review the error above.
  pause
  exit /b 1
)
echo NPU setup completed. Launch RUN_NPU.cmd.
pause
