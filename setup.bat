@echo off
chcp 65001 >nul
cd /d "%~dp0"
title YouTube Downloader

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Chua co Python. Dang cai Python 3.12 bang winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Cai xong. Dong cua so nay roi mo lai setup.bat.
  pause
  exit /b
)

if not exist ".venv\Scripts\python.exe" (
  echo Lan dau chay: dang tao moi truong va cai yt-dlp...
  %PY% -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --upgrade -r requirements.txt || goto :error
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b

:error
echo Khong cai duoc. Kiem tra mang roi chay lai.
pause
