@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Facebook Poster - Kiem tra loi
if not exist ".venv\Scripts\python.exe" (
  echo Chay setup.bat truoc de cai moi truong.
  pause
  exit /b 1
)
if not exist "logs" mkdir "logs"
echo Dang chay Facebook Poster. Nhat ky khoi dong luu tai logs\startup.log
".venv\Scripts\python.exe" -u app.py >"logs\startup.log" 2>&1
type "logs\startup.log"
pause
