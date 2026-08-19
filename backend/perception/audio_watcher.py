"""
perception/audio_watcher.py
────────────────────────────
Captures speaker output via the native audiocap helper (ScreenCaptureKit)
and transcribes with faster-whisper locally on Apple Silicon.

Architecture
────────────
  audiocap (Swift binary)
      │  stdout: 4-byte length-prefixed WAV chunks (30s each)
      ▼
  AudioWatcher._reader_thread()
      │  queue of raw WAV bytes
      ▼
  AudioWatcher._transcriber_thread()
      │  faster-whisper → text segments
      ▼
  AudioWatcher.rolling_transcript   ← read by recall_loop in main.py
"""

from __future__ import annotations

import io
import logging
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_IS_MAC = sys.platform == "darwin"

# Path to bundled audiocap binary (next to this python file when packaged,
# or in audiocap/ dir during development)
_HERE = Path(__file__).parent
_AUDIOCAP_PATHS = [
    _HERE.parent / "audiocap" / "audiocap",           # dev
    Path(sys._MEIPASS) / "audiocap" if hasattr(sys, "_MEIPASS") else None,  # packaged
    Path(os.environ.get("AUDIOCAP_BIN", "")) if os.environ.get("AUDIOCAP_BIN") else None,
]

MODELS_DIR = Path.home() / ".neytreya" / "models"
WHISPER_MODEL = "base"        # ~150MB, great English+Hindi accuracy
CHUNK_SECONDS = 30            # matches audiocap chunk size
TRANSCRIPT_WINDOW = 10        # keep last N chunks in rolling transcript (~5 min)


def _find_audiocap() -> Optional[Path]:
    for p in _AUDIOCAP_PATHS:
        if p and p.exists() and os.access(p, os.X_OK):
            return p
    return None


class AudioWatcher:
    """
    Manages the audiocap subprocess + faster-whisper transcription.
    Thread-safe. Can be started/stopped at runtime when user toggles
    'Audio Recall' in settings.
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._wav_queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self._transcript_buf: deque[str] = deque(maxlen=TRANSCRIPT_WINDOW)
        self._reader_thread: Optional[threading.Thread] = None
        self._transcriber_thread: Optional[threading.Thread] = None
        self._running = False
        self._whisper = None          # lazy-loaded
        self._whisper_error: Optional[str] = None
        self._lock = threading.Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def rolling_transcript(self) -> str:
        """Return the last ~5 minutes of transcribed speech as a single string."""
        with self._lock:
            return " ".join(self._transcript_buf)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if not _IS_MAC:
            logger.info("[audio] Audio Recall is macOS-only — skipping on %s", sys.platform)
            return
        if self._running:
            return
        audiocap = _find_audiocap()
        if not audiocap:
            logger.warning("[audio] audiocap binary not found — audio capture disabled")
            return

        self._running = True
        self._proc = subprocess.Popen(
            [str(audiocap)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        # Monitor stderr for status messages
        threading.Thread(target=self._stderr_monitor, daemon=True).start()

        self._reader_thread = threading.Thread(target=self._read_chunks, daemon=True)
        self._reader_thread.start()

        self._transcriber_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._transcriber_thread.start()
        logger.info("[audio] AudioWatcher started")

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None
        logger.info("[audio] AudioWatcher stopped")

    # ── Internal threads ────────────────────────────────────────────────────

    def _stderr_monitor(self) -> None:
        """Log audiocap stderr output."""
        if not self._proc or not self._proc.stderr:
            return
        for line in self._proc.stderr:
            text = line.decode(errors="replace").strip()
            if text:
                logger.debug("[audiocap] %s", text)

    def _read_chunks(self) -> None:
        """Read length-prefixed WAV chunks from audiocap stdout."""
        proc = self._proc
        if not proc or not proc.stdout:
            return
        while self._running:
            try:
                # Read 4-byte little-endian chunk size
                size_bytes = proc.stdout.read(4)
                if len(size_bytes) < 4:
                    logger.debug("[audio] reader: EOF from audiocap")
                    break
                chunk_size = struct.unpack("<I", size_bytes)[0]
                if chunk_size == 0 or chunk_size > 50 * 1024 * 1024:
                    logger.warning("[audio] suspicious chunk size %d, skipping", chunk_size)
                    continue
                wav_bytes = proc.stdout.read(chunk_size)
                if len(wav_bytes) < chunk_size:
                    break
                try:
                    self._wav_queue.put_nowait(wav_bytes)
                except queue.Full:
                    logger.debug("[audio] queue full, dropping chunk")
            except Exception as exc:
                if self._running:
                    logger.error("[audio] reader error: %s", exc)
                break

    def _transcribe_loop(self) -> None:
        """Pull WAV chunks from queue and transcribe with faster-whisper."""
        while self._running:
            try:
                wav_bytes = self._wav_queue.get(timeout=5)
            except queue.Empty:
                continue

            try:
                text = self._transcribe(wav_bytes)
                if text:
                    with self._lock:
                        self._transcript_buf.append(text)
                    logger.info("[audio] transcribed: %s", text[:80])
            except Exception as exc:
                logger.warning("[audio] transcription error: %s", exc)

    def _transcribe(self, wav_bytes: bytes) -> str:
        """Transcribe WAV bytes using faster-whisper. Returns plain text."""
        model = self._load_whisper()
        if model is None:
            return ""

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        try:
            segments, info = model.transcribe(
                tmp_path,
                language=None,          # auto-detect: handles Hindi + English
                task="transcribe",
                beam_size=3,
                vad_filter=True,        # skip silence
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join(s.text.strip() for s in segments if s.text.strip())
            return text
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _load_whisper(self):
        """Lazy-load faster-whisper model (downloads on first call)."""
        if self._whisper is not None:
            return self._whisper
        if self._whisper_error:
            return None
        try:
            from faster_whisper import WhisperModel
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("[audio] Loading faster-whisper model '%s'...", WHISPER_MODEL)
            self._whisper = WhisperModel(
                WHISPER_MODEL,
                device="auto",              # uses CoreML / Metal on Apple Silicon
                compute_type="float32",
                download_root=str(MODELS_DIR),
            )
            logger.info("[audio] faster-whisper model loaded")
            return self._whisper
        except ImportError:
            self._whisper_error = "faster-whisper not installed"
            logger.warning("[audio] faster-whisper not installed — transcription disabled. "
                           "Enable 'Audio Recall' in settings to auto-install.")
        except Exception as exc:
            self._whisper_error = str(exc)
            logger.error("[audio] Failed to load whisper: %s", exc)
        return None
