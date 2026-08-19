# -*- mode: python ; coding: utf-8 -*-
# Windows PyInstaller spec for Neytreya backend
# Run on Windows: pyinstaller neytreya-backend-win.spec

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'ctypes',
        'ctypes.wintypes',
        'win32api',
        'win32gui',
        'win32process',
        'aiosqlite',
        'pydantic_settings',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # macOS-only
        'audiocap',
        # Audio Recall — lazy-imported at runtime; exclude to save ~150MB
        'faster_whisper',
        'ctranslate2',
        'av',
        # ML / science — not used
        'torch', 'torchaudio', 'torchvision',
        'numpy', 'scipy', 'sklearn', 'matplotlib',
        'pandas', 'IPython', 'notebook', 'jupyter',
        # GUI toolkits
        'tkinter', '_tkinter', 'wx', 'PyQt5', 'PyQt6',
        # Dev / test tooling
        'pytest', 'setuptools', 'distutils', 'pip',
        'unittest', 'doctest', 'pdb',
        # Encoding extras
        'bz2', 'lzma',
    ],
    noarchive=False,
    optimize=2,   # strip docstrings + assert statements → smaller bytecode
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='neytreya-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,    # strip debug symbols
    upx=True,      # UPX compression (install UPX and add to PATH on Windows)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
