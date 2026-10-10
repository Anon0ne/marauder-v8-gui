@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-And-Install-Windows.ps1"
if errorlevel 1 (echo BUILD FAILED. Review messages above.)
pause
