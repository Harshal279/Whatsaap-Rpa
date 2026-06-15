"""
web_app.py
----------
Flask + SocketIO web server for WhatsApp RPA Automator.

Replaces the customtkinter UI with a browser-based interface.
All core automation logic (core/, utils/) is untouched.

Run with:
    python web_app.py
"""

import os
import sys
import base64
import threading
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Make sure the app's own packages are importable ──────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("WDM_LOG", "0")
os.environ.setdefault("WDM_LOG_LEVEL", "0")

# ── Production vs development detection ────────────────────────────────────────────
# On Render: PYTHON_ENV=production  → use eventlet (required by gunicorn)
# Locally:   no env var              → use threading (simpler, no install needed)
_IS_PRODUCTION = os.environ.get("PYTHON_ENV", "").lower() == "production"
_ASYNC_MODE = "eventlet" if _IS_PRODUCTION else "threading"

if _IS_PRODUCTION:
    import eventlet
    eventlet.monkey_patch()

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from config import (
    SUPPORTED_BROWSERS, REPORTS_DIR,
    DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, DEFAULT_RETRY_COUNT, DEFAULT_RETRY_DELAY,
    WARMUP_MSG_COUNT, WARMUP_DELAY_MIN, WARMUP_DELAY_MAX,
    OCCASIONAL_EVERY_N, OCCASIONAL_DELAY_MIN, OCCASIONAL_DELAY_MAX,
    SESSION_BREAK_MIN, SESSION_BREAK_MAX,
    DEEP_REST_MIN, DEEP_REST_MAX,
    ENABLE_ATTACHMENTS,
    FORWARD_BATCH_MIN, FORWARD_BATCH_MAX,
    DAILY_MESSAGE_LIMIT, QR_WAIT_TIMEOUT,
)
from core.automation_engine import AutomationEngine
from utils.excel_reader import read_contacts, detect_duplicates, ExcelValidationError
from utils.settings_manager import load_settings, save_settings
from utils.logger import get_logger

logger = get_logger("web_app")

# ── Flask + SocketIO setup ────────────────────────────────────────────────────
WEB_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "whatsapp-rpa-secret-2024")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB max upload

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=_ASYNC_MODE)

# ── Global state ──────────────────────────────────────────────────────────────
_engine: Optional[AutomationEngine] = None
_contacts = []
_attachment_path: Optional[str] = None
_is_paused = False
_engine_lock = threading.Lock()
_waiting_for_qr = False    # True between browser open and login confirmation
_login_confirmed = False   # True once WhatsApp login is detected


# ── Helper: emit log to all connected clients ─────────────────────────────────
def _emit_log(message: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    socketio.emit("log", {
        "message": message,
        "level": level.upper(),
        "timestamp": ts,
    })
    # Track QR / login state from log messages
    global _waiting_for_qr, _login_confirmed
    if "scan the QR" in message or "Waiting" in message:
        _waiting_for_qr = True
        _login_confirmed = False
        socketio.emit("qr_waiting", {"waiting": True})
    if "login confirmed" in message.lower() or "Already logged in" in message:
        _waiting_for_qr = False
        _login_confirmed = True
        socketio.emit("qr_waiting", {"waiting": False})


def _emit_progress(current: int, total: int):
    percent = round((current / total) * 100, 1) if total > 0 else 0
    socketio.emit("progress", {"current": current, "total": total, "percent": percent})


def _emit_contact_result(contact: dict, status: str, error: str):
    socketio.emit("contact_result", {
        "name": contact.get("name", "?"),
        "phone": contact.get("phone", "?"),
        "status": status,
        "error": error,
    })


def _emit_status(message: str):
    socketio.emit("status", {"message": message})


def _emit_complete(csv_path: str, txt_path: str):
    socketio.emit("complete", {
        "csv_path": str(csv_path),
        "txt_path": str(txt_path),
        "csv_filename": Path(csv_path).name if csv_path else "",
        "txt_filename": Path(txt_path).name if txt_path else "",
    })
    socketio.emit("engine_state", {"running": False, "paused": False})


# ── Routes: Serve frontend ────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


# ── API: Upload Excel ─────────────────────────────────────────────────────────
@app.route("/api/upload-excel", methods=["POST"])
def upload_excel():
    global _contacts

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    save_path = UPLOAD_DIR / f.filename
    f.save(str(save_path))

    try:
        contacts = read_contacts(save_path)
        dedup = request.form.get("dedup", "false").lower() == "true"
        if dedup:
            before = len(contacts)
            contacts = detect_duplicates(contacts)
            removed = before - len(contacts)
            if removed:
                _emit_log(f"Removed {removed} duplicate(s).", "WARNING")

        _contacts = contacts
        return jsonify({
            "count": len(contacts),
            "filename": f.filename,
            "preview": contacts[:5],   # first 5 rows for display
        })
    except (FileNotFoundError, ValueError, ExcelValidationError) as e:
        return jsonify({"error": str(e)}), 400


# ── API: Upload Attachment ────────────────────────────────────────────────────
@app.route("/api/upload-attachment", methods=["POST"])
def upload_attachment():
    global _attachment_path

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    save_path = UPLOAD_DIR / f.filename
    f.save(str(save_path))
    _attachment_path = str(save_path)

    return jsonify({"filename": f.filename, "path": str(save_path)})


# ── API: Clear Attachment ─────────────────────────────────────────────────────
@app.route("/api/clear-attachment", methods=["POST"])
def clear_attachment():
    global _attachment_path
    _attachment_path = None
    return jsonify({"ok": True})


# ── API: Screenshot (for QR display on Render) ──────────────────────────────────────
@app.route("/api/screenshot", methods=["GET"])
def get_screenshot():
    """Capture the current browser window and return it as a PNG.
    Used by the web UI to show the WhatsApp QR code when running on Render."""
    if not _engine or not _engine._browser_manager or not _engine._browser_manager.driver:
        return jsonify({"error": "No active browser"}), 404
    try:
        driver = _engine._browser_manager.driver
        png_bytes = driver.get_screenshot_as_png()
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        return jsonify({"image": f"data:image/png;base64,{b64}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/qr-status", methods=["GET"])
def qr_status():
    """Return whether the browser is waiting for QR scan."""
    return jsonify({
        "waiting": _waiting_for_qr,
        "logged_in": _login_confirmed,
        "has_browser": bool(
            _engine and _engine._browser_manager
            and _engine._browser_manager.driver
        ),
    })


# ── API: Settings ─────────────────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(force=True)
    try:
        validated = {
            "delay_min":         float(data["delay_min"]),
            "delay_max":         float(data["delay_max"]),
            "warmup_count":      int(float(data["warmup_count"])),
            "warmup_min":        float(data["warmup_min"]),
            "warmup_max":        float(data["warmup_max"]),
            "occasional_n":      int(float(data["occasional_n"])),
            "occasional_min":    float(data["occasional_min"]),
            "occasional_max":    float(data["occasional_max"]),
            "batch_break_min":   float(data["batch_break_min"]),
            "batch_break_max":   float(data["batch_break_max"]),
            "deep_rest_min":     float(data["deep_rest_min"]),
            "deep_rest_max":     float(data["deep_rest_max"]),
            "retry":             int(float(data["retry"])),
            "retry_delay":       float(data["retry_delay"]),
            "forward_batch_min": int(float(data["forward_batch_min"])),
            "forward_batch_max": int(float(data["forward_batch_max"])),
        }
    except (KeyError, ValueError) as e:
        return jsonify({"error": f"Invalid field: {e}"}), 400

    save_settings(validated)
    return jsonify({"ok": True})


# ── API: Automation Control ───────────────────────────────────────────────────
@app.route("/api/start", methods=["POST"])
def start_automation():
    global _engine, _is_paused

    if not _contacts:
        return jsonify({"error": "No contacts loaded. Upload an Excel file first."}), 400

    with _engine_lock:
        if _engine and _engine.is_running:
            return jsonify({"error": "Automation is already running."}), 409

    data = request.get_json(force=True) or {}
    s = load_settings()

    try:
        delay_min       = float(data.get("delay_min",       s["delay_min"]))
        delay_max       = float(data.get("delay_max",       s["delay_max"]))
        retry           = int(data.get("retry",             s["retry"]))
        retry_delay     = float(data.get("retry_delay",     s["retry_delay"]))
        warmup_count    = int(data.get("warmup_count",      s["warmup_count"]))
        warmup_min      = float(data.get("warmup_min",      s["warmup_min"]))
        warmup_max      = float(data.get("warmup_max",      s["warmup_max"]))
        occ_n           = int(data.get("occasional_n",      s["occasional_n"]))
        occ_min         = float(data.get("occasional_min",  s["occasional_min"]))
        occ_max         = float(data.get("occasional_max",  s["occasional_max"]))
        batch_min       = float(data.get("batch_break_min", s["batch_break_min"]))
        batch_max       = float(data.get("batch_break_max", s["batch_break_max"]))
        deep_min        = float(data.get("deep_rest_min",   s["deep_rest_min"]))
        deep_max        = float(data.get("deep_rest_max",   s["deep_rest_max"]))
        fwd_batch_min   = int(float(data.get("forward_batch_min", s["forward_batch_min"])))
        fwd_batch_max   = int(float(data.get("forward_batch_max", s["forward_batch_max"])))
        browser         = data.get("browser",   SUPPORTED_BROWSERS[0])
        mode_raw        = data.get("mode",       "known")
        mode            = "known" if mode_raw == "known" else "unknown"
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid parameter: {e}"}), 400

    if delay_min > delay_max:
        return jsonify({"error": "Min delay cannot exceed max delay."}), 400

    _is_paused = False

    _engine = AutomationEngine(
        contacts=list(_contacts),
        browser=browser,
        delay_min=delay_min,
        delay_max=delay_max,
        retry_count=retry,
        retry_delay=retry_delay,
        warmup_count=warmup_count,
        warmup_min=warmup_min,
        warmup_max=warmup_max,
        occasional_every_n=occ_n,
        occasional_min=occ_min,
        occasional_max=occ_max,
        batch_break_min=batch_min,
        batch_break_max=batch_max,
        deep_rest_min=deep_min,
        deep_rest_max=deep_max,
        forward_batch_min=fwd_batch_min,
        forward_batch_max=fwd_batch_max,
        attachment_path=_attachment_path,
        mode=mode,
        on_status=_emit_status,
        on_log=_emit_log,
        on_progress=_emit_progress,
        on_contact_result=_emit_contact_result,
        on_complete=_emit_complete,
    )
    _engine.start()
    socketio.emit("engine_state", {"running": True, "paused": False})
    mode_label = "Known (Forward)" if mode == "known" else "Unknown (New Chat+Paste)"
    _emit_log(f"Automation started! Mode: {mode_label}", "SUCCESS")

    return jsonify({"ok": True, "mode": mode_label})


@app.route("/api/pause", methods=["POST"])
def pause_automation():
    global _is_paused
    if not _engine or not _engine.is_running:
        return jsonify({"error": "Not running"}), 400
    _engine.pause()
    _is_paused = True
    done = _engine.success_count + _engine.failed_count
    total = _engine.total
    _emit_log(f"Paused at contact {done}/{total} — click RESUME to continue.", "WARNING")
    socketio.emit("engine_state", {"running": True, "paused": True})
    return jsonify({"ok": True})


@app.route("/api/resume", methods=["POST"])
def resume_automation():
    global _is_paused
    if not _engine:
        return jsonify({"error": "No engine"}), 400
    _engine.resume()
    _is_paused = False
    _emit_log("Resumed.", "INFO")
    socketio.emit("engine_state", {"running": True, "paused": False})
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop_automation():
    if not _engine:
        return jsonify({"error": "Not running"}), 400
    _engine.stop()
    _emit_log("Stop requested. Finishing current task…", "WARNING")
    socketio.emit("engine_state", {"running": False, "paused": False})
    return jsonify({"ok": True})


# ── API: Status ───────────────────────────────────────────────────────────────
@app.route("/api/status", methods=["GET"])
def get_status():
    running = bool(_engine and _engine.is_running)
    return jsonify({
        "running": running,
        "paused": _is_paused,
        "contacts_loaded": len(_contacts),
        "attachment": _attachment_path,
        "supported_browsers": SUPPORTED_BROWSERS,
        "attachments_enabled": ENABLE_ATTACHMENTS,
    })

# ── API: Live config (re-reads config.py every time) ────────────────────────
@app.route("/api/config", methods=["GET"])
def get_config():
    """
    Returns the current values of config.py constants.
    Re-imports config each call so changes to config.py are reflected
    without restarting the server.
    """
    import importlib
    import config as _cfg
    importlib.reload(_cfg)   # pick up any edits the user made to config.py

    return jsonify({
        # Feature flags
        "enable_attachments": _cfg.ENABLE_ATTACHMENTS,
        "supported_browsers": _cfg.SUPPORTED_BROWSERS,

        # Delay defaults
        "delay_min":          _cfg.DEFAULT_DELAY_MIN,
        "delay_max":          _cfg.DEFAULT_DELAY_MAX,
        "warmup_count":       _cfg.WARMUP_MSG_COUNT,
        "warmup_min":         _cfg.WARMUP_DELAY_MIN,
        "warmup_max":         _cfg.WARMUP_DELAY_MAX,
        "occasional_n":       _cfg.OCCASIONAL_EVERY_N,
        "occasional_min":     _cfg.OCCASIONAL_DELAY_MIN,
        "occasional_max":     _cfg.OCCASIONAL_DELAY_MAX,
        "batch_break_min":    _cfg.SESSION_BREAK_MIN,
        "batch_break_max":    _cfg.SESSION_BREAK_MAX,
        "deep_rest_min":      _cfg.DEEP_REST_MIN,
        "deep_rest_max":      _cfg.DEEP_REST_MAX,
        "forward_batch_min":  _cfg.FORWARD_BATCH_MIN,
        "forward_batch_max":  _cfg.FORWARD_BATCH_MAX,
        "retry":              _cfg.DEFAULT_RETRY_COUNT,
        "retry_delay":        _cfg.DEFAULT_RETRY_DELAY,

        # Limits
        "daily_message_limit": _cfg.DAILY_MESSAGE_LIMIT,
        "qr_wait_timeout":     _cfg.QR_WAIT_TIMEOUT,
    })


@app.route("/api/reports", methods=["GET"])
def list_reports():
    files = []
    for f in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if f.is_file() and f.suffix in (".csv", ".txt"):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return jsonify(files)


@app.route("/api/reports/<filename>", methods=["GET"])
def download_report(filename: str):
    safe = Path(filename).name  # strip any path traversal
    filepath = REPORTS_DIR / safe
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(filepath), as_attachment=True, download_name=safe)


# ── SocketIO events ───────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    running = bool(_engine and _engine.is_running)
    emit("engine_state", {"running": running, "paused": _is_paused})
    logger.info("Web client connected.")


@socketio.on("disconnect")
def on_disconnect():
    logger.info("Web client disconnected.")


# ── Entry point ───────────────────────────────────────────────────────────────
def open_browser():
    """Open the default browser after a short delay to let the server start."""
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    logger.info("Starting WhatsApp RPA Web Server…")
    print("\n" + "=" * 60)
    print("  WhatsApp RPA Automator — Web UI")
    print(f"  Open: http://localhost:{PORT}")
    print("=" * 60 + "\n")

    # Auto-open browser only when running locally
    if not _IS_PRODUCTION:
        threading.Thread(target=open_browser, daemon=True).start()

    socketio.run(
        app,
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
