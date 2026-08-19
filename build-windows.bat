@echo off
REM ============================================================
REM  Neytreya v1.0.0 — Windows Build Script
REM  Run on ARM64 Windows  → produces ARM64 backend + both installers
REM  Run on x64 Windows    → produces x64  backend + both installers
REM  For both archs: run this script on each machine, then merge
REM  the two neytreya-backend.exe files before running npm dist:win:all
REM ============================================================

REM ── Detect architecture ──────────────────────────────────────
if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set ARCH=arm64
) else (
    set ARCH=x64
)
echo [BUILD] Detected architecture: %ARCH%

echo [BUILD] Setting up Python venv...
cd backend
python -m venv venv
call venv\Scripts\activate.bat

REM ─── CRITICAL: Upgrade pip first so it can find pre-built wheels ───
echo [BUILD] Upgrading pip, setuptools, wheel...
python -m pip install --upgrade pip setuptools wheel

echo [BUILD] Installing core dependencies...
pip install --only-binary :all: fastapi websockets aiosqlite mss pytesseract Pillow psutil pyperclip httpx pydantic pydantic-settings cryptography keyring pyinstaller

REM ─── Install uvicorn WITHOUT [standard] extras to avoid httptools C-build ───
echo [BUILD] Installing uvicorn (no C-extension extras)...
pip install --only-binary :all: uvicorn

REM ─── Try httptools/watchfiles (binary-only); uvicorn falls back gracefully if missing ───
pip install --only-binary :all: httptools watchfiles 2>nul || echo [WARN] httptools/watchfiles not available - uvicorn will use pure-Python fallback.

REM ─── Try faster-whisper (x64 only, skip on ARM) ───
echo [BUILD] Attempting faster-whisper install...
pip install faster-whisper==1.2.1 2>nul || echo [WARN] faster-whisper skipped - not supported on this architecture. Audio Recall will be disabled.

echo [BUILD] Compiling backend with PyInstaller...
venv\Scripts\pyinstaller.exe neytreya-backend-win.spec

if errorlevel 1 (
    echo [ERROR] PyInstaller failed!
    pause
    exit /b 1
)

REM ─── Copy backend into arch-specific subfolder ───
echo [BUILD] Copying %ARCH% backend binary to electron resources...
if not exist "..\electron\resources\backend\%ARCH%" mkdir "..\electron\resources\backend\%ARCH%"
copy /Y dist\neytreya-backend.exe ..\electron\resources\backend\%ARCH%\neytreya-backend.exe
REM Also copy to root backend folder (used by the currently-running build)
if not exist "..\electron\resources\backend" mkdir "..\electron\resources\backend"
copy /Y dist\neytreya-backend.exe ..\electron\resources\backend\neytreya-backend.exe

cd ..\electron

echo [BUILD] Installing Node deps...
npm cache clean --force
npm install --legacy-peer-deps --prefer-online

if errorlevel 1 (
    echo [ERROR] npm install failed!
    pause
    exit /b 1
)

REM ─── Build for the current machine's architecture ───
echo [BUILD] Building Windows installer for %ARCH%...
if "%ARCH%"=="arm64" (
    npm run dist:win:arm64
) else (
    npm run dist:win:x64
)

echo.
echo [BUILD] Done!
echo   ARM64 installer: electron\dist\Neytreya-1.0.0-arm64-Setup.exe
echo   x64   installer: electron\dist\Neytreya-1.0.0-x64-Setup.exe
echo.
echo   TIP: Run this script on an x64 Windows machine too to get the x64 build.
pause
