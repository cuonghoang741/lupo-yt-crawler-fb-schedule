@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Facebook Poster
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
  echo Can Python 3.10 tro len. Dang cai Python 3.12 bang winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo Cai xong. Dong cua so nay roi mo lai setup.bat.
  pause & exit /b
)
if not exist ".venv\Scripts\python.exe" ( %PY% -m venv .venv || goto :error )
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --upgrade -r requirements.txt || goto :error
echo Dang kiem tra Firefox cho tool...
".venv\Scripts\python.exe" -m playwright install firefox || goto :error
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b
:error
echo Khong cai duoc. Kiem tra mang roi chay lai.
pause
