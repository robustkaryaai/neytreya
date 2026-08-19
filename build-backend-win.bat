@echo off
:: ── build-backend-win.bat ──
:: Compile the FastAPI Python backend into a single executable and place it into Electron's resources directory on Windows.

set PROJECT_ROOT=%~dp0
set BACKEND_DIR=%PROJECT_ROOT%backend
set ELECTRON_DIR=%PROJECT_ROOT%electron
set RESOURCES_DIR=%ELECTRON_DIR%\resources\backend

echo === [1/4] Setting up build environment ===
if not exist "%RESOURCES_DIR%" mkdir "%RESOURCES_DIR%"

cd /d "%BACKEND_DIR%"

set VENV_PY=%BACKEND_DIR%\venv\Scripts\python.exe
if not exist "%VENV_PY%" (
    echo Creating virtual environment...
    python -m venv venv
)

call "%BACKEND_DIR%\venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo === [2/4] Compiling Python Backend via PyInstaller ===
pyinstaller --clean --onefile ^
  --name neytreya-backend ^
  --workpath "%PROJECT_ROOT%build\pyinstaller_work" ^
  --distpath "%RESOURCES_DIR%" ^
  main.py

echo === [3/4] Copying dependencies and assets ===
if exist ".rxc" (
    echo Bundling .rxc modules...
    xcopy /E /I /Y ".rxc" "%RESOURCES_DIR%\.rxc"
)

echo === [4/4] Verification ===
if exist "%RESOURCES_DIR%\neytreya-backend.exe" (
    echo [OK] Backend built successfully: %RESOURCES_DIR%\neytreya-backend.exe
) else (
    echo [ERR] Backend executable not found!
    exit /b 1
)
