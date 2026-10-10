@echo off
cd /d "%~dp0"
if exist ".npu-venv\Scripts\python.exe" (
  ".npu-venv\Scripts\python.exe" marauder_workspace.py
) else (
  echo Run SETUP_NPU.cmd first.
  pause
)
