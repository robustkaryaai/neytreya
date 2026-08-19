"""
rexycore_bootstrap.py
─────────────────────
Runs once at Neytreya startup.

Ensures the RexyCore API packages are installed into ~/.rexycore/lib/
so ANY product on this machine can find them without knowing Neytreya's
path. Neytreya bundles a specific version of the API; if a newer bundle is
present it overwrites the installed copy.

After bootstrap completes, ~/.rexycore/lib/ is added to sys.path so the
current process can import rmp / rexycore_auth / rexycore_client directly.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────

# Where Neytreya's bundled copy of the API lives (next to this file)
_BUNDLE_DIR = Path(__file__).parent / ".rxc" / "lib"

# System-wide installation target
_INSTALL_DIR = Path.home() / ".rexycore" / "lib"

# Version sentinel files
_BUNDLE_VERSION_FILE  = _BUNDLE_DIR  / ".version"
_INSTALL_VERSION_FILE = _INSTALL_DIR / ".version"

# Packages that live inside the lib directory
_PACKAGES = ("rmp", "rexycore_auth", "rexycore_client")


# ── Version helpers ─────────────────────────────────────────────────────────

def _read_version(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def _bundle_is_newer() -> bool:
    installed = _version_tuple(_read_version(_INSTALL_VERSION_FILE))
    bundled   = _version_tuple(_read_version(_BUNDLE_VERSION_FILE))
    return bundled > installed


# ── Core bootstrap ──────────────────────────────────────────────────────────

def _install_from_bundle() -> None:
    """Copy bundled packages → ~/.rexycore/lib/ (overwrite existing)."""
    _INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    for pkg in _PACKAGES:
        src = _BUNDLE_DIR / pkg
        dst = _INSTALL_DIR / pkg
        if not src.exists():
            logger.warning("[rxc-bootstrap] bundled package missing: %s", pkg)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.debug("[rxc-bootstrap] installed %s → %s", pkg, dst)

    # Write version sentinel
    bundled_version = _read_version(_BUNDLE_VERSION_FILE)
    (_INSTALL_DIR / ".version").write_text(bundled_version, encoding="utf-8")
    logger.info("[rxc-bootstrap] RexyCore API v%s installed to %s", bundled_version, _INSTALL_DIR)


def _ensure_on_path() -> None:
    """Add ~/.rexycore/lib to sys.path if it isn't already there."""
    lib_str = str(_INSTALL_DIR)
    if lib_str not in sys.path:
        sys.path.insert(0, lib_str)
        logger.debug("[rxc-bootstrap] added %s to sys.path", lib_str)


# ── Public entry point ──────────────────────────────────────────────────────

def bootstrap() -> bool:
    """
    Ensure ~/.rexycore/lib/ has the RexyCore API, then add it to sys.path.

    Returns True if the API is available (installed or already present),
    False if the bundle is missing and no prior installation exists.

    Never raises — failures are logged and Neytreya continues without
    RexyCore integration.
    """
    try:
        has_bundle   = _BUNDLE_DIR.exists()
        has_install  = _INSTALL_DIR.exists()

        if has_bundle:
            if not has_install or _bundle_is_newer():
                logger.info("[rxc-bootstrap] Installing/updating RexyCore API …")
                _install_from_bundle()
            else:
                logger.debug("[rxc-bootstrap] Installed API is current, skipping copy.")
        elif not has_install:
            logger.warning(
                "[rxc-bootstrap] No bundled or installed RexyCore API found. "
                "RexyCore features will be unavailable."
            )
            return False

        _ensure_on_path()

        # Quick import smoke-test (no side effects)
        import importlib
        importlib.import_module("rmp")
        importlib.import_module("rexycore_client")

        logger.info("[rxc-bootstrap] RexyCore API ready at %s", _INSTALL_DIR)
        return True

    except Exception as exc:
        logger.warning("[rxc-bootstrap] Bootstrap failed: %s — RexyCore unavailable.", exc)
        return False
