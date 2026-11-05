@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Dong goi thanh YouTubeDownloader.exe (chay mot lan tren Windows, can chay setup.bat truoc).
".venv\Scripts\python.exe" -m pip install -q pyinstaller || goto :error
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name YouTubeFacebook --collect-all yt_dlp --collect-all yt_dlp_ejs --collect-all playwright --collect-all webview --add-data "webui.html;." webapp.py || goto :error
echo.
echo Xong: dist\YouTubeDownloader.exe
pause
exit /b
:error
echo Dong goi loi.
pause
