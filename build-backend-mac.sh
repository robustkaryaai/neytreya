#!/bin/bash
# ── build-backend-mac.sh ──
# Compile the FastAPI Python backend into a single executable and place it into Electron's resources directory.

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
ELECTRON_DIR="$PROJECT_ROOT/electron"
RESOURCES_DIR="$ELECTRON_DIR/resources/backend"

echo "=== [1/4] Setting up build environment ==="
mkdir -p "$RESOURCES_DIR"

cd "$BACKEND_DIR"

# Ensure venv Python is active or run from venv directly
VENV_PY="$BACKEND_DIR/venv/bin/python3"
if [ ! -f "$VENV_PY" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Upgrade pip and install build dependencies
"$BACKEND_DIR/venv/bin/pip" install --upgrade pip
"$BACKEND_DIR/venv/bin/pip" install -r requirements.txt
"$BACKEND_DIR/venv/bin/pip" install pyinstaller

echo "=== [2/4] Compiling Python Backend via PyInstaller ==="
# We bundle PyInstaller to search main.py and compile single binary
"$BACKEND_DIR/venv/bin/pyinstaller" --clean --onefile \
  --name neytreya-backend \
  --workpath "$PROJECT_ROOT/build/pyinstaller_work" \
  --distpath "$RESOURCES_DIR" \
  main.py

echo "=== [3/4] Copying dependencies and assets ==="
# If there are any static/db assets or specific library files (like .rxc) package them next to backend
if [ -d ".rxc" ]; then
    echo "Bundling .rxc modules next to the binary..."
    cp -R ".rxc" "$RESOURCES_DIR/"
fi

echo "=== [4/4] Verification ==="
if [ -f "$RESOURCES_DIR/neytreya-backend" ]; then
    echo "✓ Backend built successfully: $RESOURCES_DIR/neytreya-backend"
else
    echo "❌ Error: Backend executable not found!"
    exit 1
fi
