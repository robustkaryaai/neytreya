"""
Neytreya Backend — Perceptual Intelligence Engine
FastAPI + WebSocket server, port 7432.

Pipeline:
  Perception Layer → Context Engine → Inference Engine → Observation Engine
  → SQLite Episode Memory → WebSocket broadcast
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import ssl
import sys
import httpx
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Set

# Fix for macOS Python SSL certificate issues
if platform.system() == "Darwin":
    ssl._create_default_https_context = ssl._create_unverified_context

# ── RexyCore bootstrap: must run before SDK imports ──────────────────────────
import rexycore_bootstrap as _rxc_boot
_rxc_boot.bootstrap()
del _rxc_boot
# ─────────────────────────────────────────────────────────────────────────────

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import NeytreyadSettings
from engines.context import ContextEngine
from engines.inference import InferenceEngine
from engines.observation import ObservationEngine
from integrations.rexycore import RexyCoreLink
from memory.db import NeytreyadDB
from memory.models import PerceptionData
from memory.recall import RecallEngine
from perception.active_recall import ActiveRecall
from perception.apps import AppWatcher
from perception.audio_watcher import AudioWatcher
from perception.clipboard import ClipboardWatcher
from perception.resources import ResourceWatcher
from perception.screen import ScreenWatcher
from vision.qwen_vl import QwenVLVision

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("neytreya")

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
settings        = NeytreyadSettings.load()
db              = NeytreyadDB()

app_watcher     = AppWatcher()
resource_watcher= ResourceWatcher()
screen_watcher  = ScreenWatcher(min_interval=float(settings.capture_interval))
clipboard_watcher= ClipboardWatcher()

context_engine  = ContextEngine()
inference_engine= InferenceEngine(stuck_threshold_minutes=settings.stuck_threshold_minutes)
obs_engine      = ObservationEngine(db=db)      # wire DB for error recall

vision          = QwenVLVision(
    ollama_url=settings.ollama_url,
    model=settings.vision_model,
)
rexycore        = RexyCoreLink()
recall_engine   = RecallEngine(db=db)
active_recall   = ActiveRecall()
audio_watcher   = AudioWatcher()

# Connected WebSocket clients
_ws_clients: Set[WebSocket] = set()

_LLM_CATEGORY_CACHE: dict[str, str] = {}
_LLM_CATEGORY_PENDING: set[str] = set()

async def _fetch_llm_category(app: str, title: str, cache_key: str):
    try:
        cat = await vision.predict_category(app, title)
        if cat:
            _LLM_CATEGORY_CACHE[cache_key] = cat
    finally:
        _LLM_CATEGORY_PENDING.discard(cache_key)

# Latest broadcast payload (sent to new clients on connect)
_latest_payload: dict = {}

# Self-apps that should be ignored so panel stays on last real context
_SELF_APP_NAMES = {"electron", "neytreya", "neytreya.app"}
# Last real app seen before we opened the panel
_last_known_app:   str | None = None
_last_known_window:str | None = None


# ---------------------------------------------------------------------------
# Perception tick
# ---------------------------------------------------------------------------

async def perception_tick() -> dict:
    """
    One full perception + engine cycle.
    Returns the dict to broadcast over WebSocket.
    """
    global settings

    # ── 1. Resources (always) ──────────────────────────────────────────
    res       = await asyncio.to_thread(resource_watcher.get_resources)
    load_tier = res["load_tier"]

    # ── 2. Active app (unless quiet) ──────────────────────────────────
    global _last_known_app, _last_known_window
    active_app:   str | None = None
    window_title: str | None = None

    if not settings.is_quiet_time():
        info       = await asyncio.to_thread(app_watcher.get_active_app)
        active_app = info.get("name")
        window_title= info.get("window_title")

    # Skip self (Neytreya / Electron panel) — keep showing last real context
    if active_app and active_app.lower().rstrip('.app') in _SELF_APP_NAMES:
        active_app   = _last_known_app
        window_title = _last_known_window
    elif active_app and active_app != "[blocked]":
        _last_known_app    = active_app
        _last_known_window = window_title

    # Blocked app check
    if active_app and settings.is_app_blocked(active_app):
        active_app   = "[blocked]"
        window_title = None

    # ── 3. Screen / OCR (only when watching + OCR enabled, LOW/MEDIUM load) ─
    screen_text: str | None = None
    last_image              = None

    if (
        settings.watching_enabled
        and settings.ocr_enabled
        and load_tier != "HIGH"
        and not settings.is_quiet_time()
        and active_app != "[blocked]"
    ):
        try:
            sd         = await asyncio.to_thread(screen_watcher.get_screen_data)
            screen_text= sd.get("text") or None
            last_image = sd.get("image")
        except Exception as exc:
            logger.debug("Screen capture skipped: %s", exc)

    # ── 4. Vision (LOW only, if enabled, Ollama available) ───────────
    vision_summary: str | None = None

    # Auto-protection: if system is under HIGH load or user is gaming, temporarily skip vision
    is_gaming = active_app and any(g in active_app.lower() for g in ["minecraft", "roblox", "steam", "epic games", "league of legends", "valorant", "csgo", "cs2", "dota", "overwatch", "gta", "cyberpunk"])
    
    if (load_tier == "HIGH" or is_gaming) and settings.vision_enabled:
        reason = "User is gaming" if is_gaming else "System under heavy load"
        logger.warning(f"[main] {reason} detected — skipping vision this tick to protect performance.")
        # Push a one-time warning observation so it shows in the panel
        _high_load_obs = {
            "type": "observation",
            "data": {
                "message": f"{reason} — Vision Engine paused this cycle to preserve framerate.",
                "is_error": False,
                "app": active_app or "System",
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
        }
        await _broadcast(_high_load_obs)

    if (
        settings.watching_enabled
        and load_tier == "LOW"
        and settings.vision_enabled
        and last_image is not None
        and not is_gaming
    ):
        try:
            hint           = f"{active_app or ''} · {window_title or ''}"
            vision_summary = await vision.analyze(last_image, context_hint=hint) or None
        except Exception as exc:
            logger.debug("Vision skipped: %s", exc)

    # ── 5. Clipboard (LOW only) ───────────────────────────────────────
    clipboard_text: str | None = None
    if load_tier == "LOW" and settings.clipboard_enabled:
        try:
            clipboard_text = await asyncio.to_thread(clipboard_watcher.get_if_changed)
        except Exception as exc:
            logger.debug("Clipboard skipped: %s", exc)

    # ── 6. Build PerceptionData ───────────────────────────────────────
    perception = PerceptionData(
        timestamp       = datetime.now().isoformat(),
        active_app      = active_app,
        window_title    = window_title,
        screen_text     = screen_text,
        vision_summary  = vision_summary,
        clipboard_text  = clipboard_text,
        cpu_percent     = res["cpu_percent"],
        ram_percent     = res["ram_percent"],
        ram_available_gb= res["ram_available_gb"],
        battery_percent = res.get("battery_percent"),
        battery_plugged = res.get("battery_plugged"),
        load_tier       = load_tier,       # type: ignore[arg-type]
    )

    # ── 7. Context Engine ─────────────────────────────────────────────
    context = context_engine.classify(perception)
    
    # ── 7b. Smart LLM Category Fallback (Qwen 1-3 word precision) ─────
    if context.activity != "Idle" and (active_app or window_title):
        cache_key = f"{active_app}::{window_title}"
        if cache_key in _LLM_CATEGORY_CACHE:
            context.activity = _LLM_CATEGORY_CACHE[cache_key]
        elif cache_key not in _LLM_CATEGORY_PENDING:
            _LLM_CATEGORY_PENDING.add(cache_key)
            asyncio.create_task(_fetch_llm_category(active_app or "", window_title or "", cache_key))

    # ── 8. Inference Engine ───────────────────────────────────────────
    inference = inference_engine.infer(context, perception)

    # ── 9. Observation Engine (sync pass) ─────────────────────────────
    observations = obs_engine.generate(context, inference, perception)

    # ── 9b. Async error recall check ─────────────────────────────────
    if inference.error_hint:
        import time as _time
        now = _time.monotonic()
        recall_obs = await obs_engine.check_error_recall(inference, perception, now)
        if recall_obs:
            observations = (observations + [recall_obs])[:2]

    # ── 10. Persist snapshot + timeline ──────────────────────────────
    await db.save_snapshot(perception)

    # Record timeline entry if not blocked/quiet
    if active_app and active_app != "[blocked]" and not settings.is_quiet_time():
        # Extract error hint from screen text
        error_hint_for_db: str | None = inference.error_hint

        # Extract website domain from window title (for browser apps)
        website: str | None = None
        browser_apps = {"chrome", "safari", "firefox", "edge", "brave", "arc"}
        if active_app and any(b in active_app.lower() for b in browser_apps):
            if window_title:
                import re
                m = re.search(r'([\w\-]+\.(com|org|net|io|dev|ai|co))', window_title, re.I)
                if m:
                    website = m.group(1).lower()

        await db.record_timeline(
            perception=perception,
            activity=context.activity,
            workflow=inference.workflow,
            error_hint=error_hint_for_db,
            website=website,
        )

        # Upsert website
        if website:
            await db.upsert_website(website, context=context.activity)

        # Upsert error
        if error_hint_for_db:
            await db.upsert_error(
                pattern=error_hint_for_db,
                app=active_app,
                context=context.activity,
            )

    # ── 11. Build broadcast payload ───────────────────────────────────
    payload = {
        "type":       "perception_update",
        "perception": perception.to_ws_dict(),
        "context": {
            "activity":   context.activity,
            "confidence": context.confidence,
            "app":        context.app,
            "detail":     context.detail,
        },
        "inference": {
            "workflow":               inference.workflow,
            "confidence":             inference.confidence,
            "signals":                inference.signals,
            "stuck":                  inference.stuck,
            "stuck_duration_minutes": inference.stuck_duration_minutes,
            "stuck_app":              inference.stuck_app,
            "stuck_window":           inference.stuck_window,
            "error_hint":             inference.error_hint,
        },
        "observations": [o.model_dump() for o in observations],
    }

    logger.debug(
        "tick | %-15s | %-20s | %-18s | load=%-6s | cpu=%4.1f%% | ram=%4.1f%%",
        (context.activity or "—")[:15],
        (inference.workflow or "—")[:20],
        (active_app or "—")[:18],
        load_tier,
        res["cpu_percent"],
        res["ram_percent"],
    )

    return payload


# ---------------------------------------------------------------------------
# Perception loop
# ---------------------------------------------------------------------------

async def perception_loop() -> None:
    global _latest_payload

    _cur = NeytreyadSettings.load()
    logger.info("Perception loop started (interval=%ds)", _cur.capture_interval)

    while True:
        try:
            payload          = await perception_tick()
            _latest_payload  = payload
            await broadcast(payload)
        except asyncio.CancelledError:
            logger.info("Perception loop cancelled")
            break
        except Exception as exc:
            logger.error("Perception tick error: %s", exc, exc_info=True)

        # Reload settings each tick
        _cur = NeytreyadSettings.load()
        _cur.save()
        screen_watcher._min_interval             = float(_cur.capture_interval)
        inference_engine._stuck_threshold_sec    = _cur.stuck_threshold_minutes * 60

        await asyncio.sleep(_cur.capture_interval)


# ---------------------------------------------------------------------------
# WebSocket broadcast
# ---------------------------------------------------------------------------

async def broadcast(data: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    payload = json.dumps(data)
    for ws in list(_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Active Recall Loop
# ---------------------------------------------------------------------------

_RECALL_SNAPSHOT_INTERVAL = 60        # 1 minute: take compressed WebP screenshot
_RECALL_SUMMARY_INTERVAL  = 5 * 60   # 5 minutes: run Qwen and save text summary

async def recall_loop() -> None:
    """
    Background loop for Active Recall.
    Every 1 min  → compressed WebP snapshot to disk.
    Every 5 mins → Qwen VL summary saved to DB (only if model installed).
    """
    last_summary_ts = 0.0
    tick = 0

    # Prune old snapshots once at startup
    await asyncio.to_thread(active_recall.prune_old_snapshots)

    while True:
        try:
            await asyncio.sleep(_RECALL_SNAPSHOT_INTERVAL)
            tick += 1

            # Grab latest context
            payload     = _latest_payload
            perception  = payload.get("perception", {})
            cur_app     = perception.get("active_app", "")
            cur_window  = perception.get("window_title", "")

            # 1. Visual snapshot every minute
            snap_path = await asyncio.to_thread(
                active_recall.take_snapshot,
                cur_app,
                cur_window or "",
            )

            # 2. Qwen summary every 5 minutes
            now_mono = asyncio.get_event_loop().time()
            if (now_mono - last_summary_ts) >= _RECALL_SUMMARY_INTERVAL:
                last_summary_ts = now_mono
                try:
                    # Use the screen image from the current perception tick
                    sd = await asyncio.to_thread(screen_watcher.get_screen_data)
                    img = sd.get("image")

                    summary_text: str | None = None

                    # Grab any audio transcript from the last 5 minutes
                    audio_transcript = audio_watcher.rolling_transcript

                    if img is not None and settings.vision_enabled and await vision.is_available():
                        ctx_hint = f"{cur_app} · {cur_window}"
                        if audio_transcript:
                            ctx_hint += f" | Audio: {audio_transcript[:300]}"
                        summary_text = await vision.analyze(
                            img,
                            context_hint=ctx_hint,
                            active_app=cur_app or "",
                            window_title=cur_window or "",
                            screen_text=audio_transcript[:500] if audio_transcript else "",
                        )

                    # Fallback to OCR text / audio transcript if Qwen not available
                    if not summary_text:
                        ctx = payload.get("context", {})
                        activity = ctx.get("activity", "")
                        if audio_transcript:
                            # Prefer audio transcript as the summary when available
                            summary_text = audio_transcript[:400]
                        elif activity or cur_app:
                            summary_text = f"{activity or 'Working'} in {cur_app}"
                            if cur_window:
                                summary_text += f" — {cur_window[:80]}"

                    if summary_text:
                        await db.save_recall_summary(
                            summary=summary_text,
                            app=cur_app or None,
                            window_title=cur_window or None,
                            snapshot_path=snap_path,
                        )
                        # Broadcast latest summary + live transcript to WebSocket clients
                        await broadcast({
                            "type": "recall_summary",
                            "summary": summary_text,
                            "app": cur_app,
                            "time": datetime.now().strftime("%H:%M"),
                            "snapshot": snap_path,
                            "transcript": audio_transcript or None,
                        })
                        logger.info("[recall] Summary: %s", summary_text[:80])

                except Exception as exc:
                    logger.debug("[recall] Summary generation failed: %s", exc)

        except asyncio.CancelledError:
            logger.info("Recall loop cancelled")
            break
        except Exception as exc:
            logger.error("[recall] Loop error: %s", exc, exc_info=True)



@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising Neytreya …")
    await db.init()
    loop_task   = asyncio.create_task(perception_loop())
    recall_task = asyncio.create_task(recall_loop())
    async def handle_system_state_request():
        return _latest_payload

    rexycore.on_system_state_request(handle_system_state_request)
    rexycore.start()

    # Start audio capture if enabled in settings
    if settings.audio_recall_enabled:
        await asyncio.to_thread(audio_watcher.start)

    print("Neytreya backend ready", flush=True)
    yield

    loop_task.cancel()
    recall_task.cancel()
    try:
        await asyncio.gather(loop_task, recall_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    await asyncio.to_thread(audio_watcher.stop)
    await rexycore.stop()
    logger.info("Neytreya backend stopped.")


app = FastAPI(title="Neytreya", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# HTTP endpoints — Core
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status":  "ok",
        "version": "2.0.0",
        "vision_available": await vision.is_available(),
        "rk_ai_available":  await rexycore.is_available(),
    }


@app.get("/settings")
async def get_settings():
    return settings.model_dump()


@app.post("/settings")
async def update_settings(payload: dict):
    global settings
    try:
        new = NeytreyadSettings(**{**settings.model_dump(), **payload})
        new.save()
        settings = new
        return {"status": "saved"}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/snapshots")
async def get_snapshots(limit: int = 50):
    rows = await db.get_recent_snapshots(limit=min(limit, 200))
    return {"snapshots": rows}


@app.get("/latest")
async def get_latest():
    return _latest_payload


@app.post("/rk-ai/ask")
async def ask_rk_ai(payload: dict):
    """Manually trigger RK AI hand-off with provided context."""
    from memory.models import ContextState, InferenceState
    try:
        ctx = ContextState(**payload.get("context", {}))
        inf = InferenceState(**payload.get("inference", {}))
        signals = payload.get("stuck_signals", [])
        result = await rexycore.send_context(ctx, inf, signals)
        return {"result": result}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# HTTP endpoints — Vision / System Info
# ---------------------------------------------------------------------------

@app.get("/vision/system-specs")
async def get_system_specs():
    """Return system RAM and platform info for dynamic model selection."""
    import platform as _platform
    import psutil
    from vision.qwen_vl import _is_apple_silicon, _get_tiers_for_system, recommend_model_for_ram

    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    available_gb = round(psutil.virtual_memory().available / (1024 ** 3), 1)
    sys = _platform.system()
    is_apple = _is_apple_silicon()

    tiers = _get_tiers_for_system()
    recommended = recommend_model_for_ram(available_gb)

    # Get installed models
    installed = await vision.get_installed_models()

    return {
        "platform":          sys,
        "is_apple_silicon":  is_apple,
        "ram_total_gb":      ram_gb,
        "ram_available_gb":  available_gb,
        "recommended_model": recommended,
        "tiers":             tiers,
        "installed_models":  installed,
    }


# ---------------------------------------------------------------------------
# HTTP endpoints — Recall
# ---------------------------------------------------------------------------

@app.get("/recall/recent")
async def recall_recent(limit: int = 40):
    """Return recent timeline entries."""
    data = await recall_engine.get_recent_timeline(limit=min(limit, 100))
    return {"entries": data}


@app.get("/recall/today")
async def recall_today():
    """Return today's activity summary."""
    return await recall_engine.get_today()


@app.get("/recall/yesterday")
async def recall_yesterday():
    """Return yesterday's activity summary."""
    return await recall_engine.get_yesterday()


@app.get("/recall/search")
async def recall_search(q: str = ""):
    """Search timeline, projects, websites, errors."""
    return await recall_engine.search(q)


@app.get("/recall/quick")
async def recall_quick(q: str = ""):
    """Quick recall endpoint for global shortcut overlay."""
    results = await recall_engine.search(q)
    
    if not results or not results.get('results'):
        return "I couldn't find anything matching that in your recent timeline."
        
    res_list = results['results'][:5]
    out = f"**Recall Results for '{q}'**\n\n"
    for r in res_list:
        icon = r.get('icon', '•')
        time = r.get('time', '')
        title = r.get('title', '') or r.get('activity', '')
        sub = r.get('subtitle', '') or r.get('app', '')
        out += f"{icon} **{title}** ({sub}) - {time}\n"
    
    return out

@app.get("/report/monthly")
async def report_monthly():
    """Aggregated stats for the monthly PDF report — uses real recall DB data."""
    from datetime import datetime, timedelta
    from collections import defaultdict

    today = datetime.now().date()
    app_totals: dict[str, float] = defaultdict(float)   # app name → hours
    stuck_total = 0
    days_active = 0

    # Walk back 30 days and collect timeline entries
    for offset in range(30):
        day = today - timedelta(days=offset)
        try:
            day_data = await recall_engine.get_timeline_for_date(str(day))
            entries = day_data.get("timeline", []) if day_data else []
        except Exception:
            entries = []

        if entries:
            days_active += 1
            # Each entry represents time spent — count distinct transitions
            prev_time = None
            for i, entry in enumerate(entries):
                app_name = entry.get("app") or "Unknown"
                # Estimate duration as gap to next entry (assume 2-min intervals)
                duration_h = 2 / 60.0
                app_totals[app_name] += duration_h
                if entry.get("stuck"):
                    stuck_total += 1

    # Build sorted app usage list
    sorted_apps = sorted(app_totals.items(), key=lambda x: x[1], reverse=True)
    app_usage = [{"name": name, "hours": round(hours, 1)} for name, hours in sorted_apps[:8]]
    total_hours = sum(app_totals.values())
    top_app = sorted_apps[0][0] if sorted_apps else "your apps"

    # Simple insight
    if total_hours > 0:
        top_pct = round((sorted_apps[0][1] / total_hours) * 100) if sorted_apps else 0
        insight = (
            f"Over the past 30 days Neytreya recorded {round(total_hours, 1)} hours of activity "
            f"across {days_active} active days. "
            f"Most of your time ({top_pct}%) was spent in {top_app}. "
            + (f"You hit {stuck_total} stuck events — moments where you were on the same screen for a while." if stuck_total else "No stuck events recorded.")
        )
    else:
        insight = "Not enough data yet — let Neytreya run for a few days to generate meaningful insights."

    return {
        "focus_time": f"{int(total_hours)}h {int((total_hours % 1) * 60)}m" if total_hours else "No data yet",
        "app_usage": app_usage,
        "top_websites": [],   # future: parse window titles for browser entries
        "stuck_events": stuck_total,
        "insights": insight,
        "days_active": days_active,
        "generated_at": datetime.now().strftime("%B %d, %Y at %H:%M"),
    }

@app.post("/tts/speak")
async def tts_speak(payload: dict):
    """Generate TTS using native OS speech synthesis."""
    text = payload.get("text", "")
    if not text:
        return {"ok": False, "error": "No text provided"}
    
    # Run in background so it doesn't block
    def speak_sync(txt: str):
        try:
            import sys
            import subprocess
            if sys.platform == "darwin":
                subprocess.Popen(["say", txt])
            elif sys.platform == "win32":
                ps_cmd = f"Add-Type -AssemblyName System.speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{txt.replace(chr(39), chr(39)+chr(39))}')"
                subprocess.Popen(["powershell", "-Command", ps_cmd])
        except Exception as e:
            logger.error("TTS failed: %s", e)
            
    asyncio.to_thread(speak_sync, text)
    
    return {"ok": True, "message": "Speaking..."}

@app.post("/recall/chat")
async def recall_chat(payload: dict):
    """Chat with the timeline using local Qwen VL or default LLM."""
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"ok": False, "error": "No prompt"}
        
    try:
        # Get today's timeline
        timeline = await recall_engine.get_today()
        entries = timeline.get("timeline", [])
        
        # Compress timeline
        compressed = []
        for e in entries:
            app = e.get("app", "Unknown")
            time = e.get("time", "")
            if not compressed or compressed[-1]["app"] != app:
                compressed.append({"app": app, "start": time, "end": time})
            else:
                compressed[-1]["end"] = time
                
        timeline_str = "Today's timeline:\\n"
        for c in compressed[-20:]: # Last 20 context switches
            timeline_str += f"- {c['app']}: from {c['start']} to {c['end']}\\n"
            
        sys_prompt = "You are Neytreya, an AI assistant. You have access to the user's timeline. Keep your answers extremely brief, in a nutshell, unless paragraphs are absolutely needed. Do not output markdown, just plain text so it can be spoken aloud naturally."
        full_prompt = f"{sys_prompt}\\n\\n{timeline_str}\\nUser asks: {prompt}"
        
        # Check if Ollama / vision is available
        if await vision.is_available():
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{vision.ollama_url}/api/generate",
                    json={
                        "model": settings.vision_model,
                        "prompt": full_prompt,
                        "stream": False
                    }
                )
                if resp.status_code == 200:
                    response = resp.json().get("response", "No response generated.")
                else:
                    err_txt = resp.text
                    response = f"Ollama Error ({resp.status_code}): {err_txt}"
        else:
            response = "Qwen model is not available to answer this right now."
            
        return {"ok": True, "response": response}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/recall/project/{name}")
async def recall_project(name: str):
    """Return history for a specific project."""
    return await recall_engine.get_project_history(name)

@app.get("/recall/active-timeline")
async def recall_active_timeline(date: str = ""):
    """Return visual snapshots + Qwen summaries for a date (defaults to today)."""
    import base64
    from perception.active_recall import RECALL_DIR
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    summaries = await db.get_recall_summaries_for_date(target_date)
    snapshots = await asyncio.to_thread(active_recall.get_snapshots_for_date, target_date)
    return {
        "date": target_date,
        "summaries": summaries,
        "snapshots": snapshots,
    }

@app.get("/recall/snapshot/{filename}")
async def recall_snapshot_image(filename: str):
    """Serve a recall snapshot as a base64 encoded WebP image."""
    from perception.active_recall import RECALL_DIR
    from fastapi.responses import Response
    filepath = RECALL_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".webp":
        return JSONResponse(status_code=404, content={"error": "Not found"})
    data = filepath.read_bytes()
    return Response(content=data, media_type="image/webp")


@app.get("/recall/transcript/live")
async def recall_transcript_live():
    """Return the current rolling audio transcript (last ~5 minutes)."""
    return {
        "running": audio_watcher.is_running,
        "transcript": audio_watcher.rolling_transcript,
    }


@app.post("/settings/audio-recall")
async def toggle_audio_recall(body: dict):
    """Enable or disable Audio Recall (starts/stops audiocap + whisper)."""
    enabled = bool(body.get("enabled", False))
    settings.audio_recall_enabled = enabled
    settings.save()
    if enabled and not audio_watcher.is_running:
        await asyncio.to_thread(audio_watcher.start)
    elif not enabled and audio_watcher.is_running:
        await asyncio.to_thread(audio_watcher.stop)
    return {"audio_recall_enabled": enabled, "running": audio_watcher.is_running}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info("WS client connected (%d total)", len(_ws_clients))

    if _latest_payload:
        try:
            await websocket.send_text(json.dumps(_latest_payload))
        except Exception:
            pass

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "settings_update":
                    await update_settings(msg.get("data", {}))
                    await websocket.send_text(
                        json.dumps({"type": "settings_ack", "status": "saved"})
                    )
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    finally:
        _ws_clients.discard(websocket)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=7432,
        reload=False,
        log_level="warning",
    )
