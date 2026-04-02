@echo off
REM ============================================================
REM Cat Sentry Pro — Build standalone .exe for Windows
REM ============================================================
REM Prerequisites:
REM   1. Python 3.9+ installed and in PATH
REM   2. Run this script from the lite/ directory
REM
REM Output: dist/cat_sentry_pro/  (folder with .exe and all deps)
REM ============================================================

echo [1/3] Installing build dependencies...
pip install pyinstaller

echo [2/3] Running PyInstaller...
pyinstaller ^
    --noconfirm ^
    --name cat_sentry_pro ^
    --add-data "index.html;." ^
    --add-data "config.json.example;." ^
    --add-data "yolov8m.pt;." ^
    --hidden-import=ultralytics ^
    --hidden-import=torch ^
    --hidden-import=cv2 ^
    --hidden-import=numpy ^
    --hidden-import=requests ^
    --collect-all ultralytics ^
    --copy-metadata ultralytics ^
    cat_sentry_pro.py

echo [3/3] Copying config template...
copy config.json.example dist\cat_sentry_pro\config.json.example

echo.
echo ============================================================
echo Build complete!
echo.
echo To run:
echo   1. cd dist\cat_sentry_pro
echo   2. copy config.json.example config.json
echo   3. Edit config.json with your RTSP URL and push keys
echo   4. cat_sentry_pro.exe
echo   5. Open http://localhost:8080
echo ============================================================
pause
