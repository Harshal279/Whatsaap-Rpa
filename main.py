"""
main.py
-------
Application entry point for WhatsApp RPA Automator.

Run modes:
    python main.py           — Desktop UI (customtkinter)
    python main.py --web     — Web UI (Flask + SocketIO, opens browser)
    python web_app.py        — Web UI directly
"""

import sys
import os
from pathlib import Path

# ── Make sure the app's own packages are importable ──────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Suppress webdriver-manager download noise in console ─────────────────────
os.environ.setdefault("WDM_LOG", "0")
os.environ.setdefault("WDM_LOG_LEVEL", "0")

from utils.logger import get_logger

logger = get_logger("main")


def main_desktop():
    """Launch the customtkinter desktop UI."""
    logger.info("Starting WhatsApp RPA Automator (Desktop UI)…")

    try:
        import customtkinter as ctk
    except ImportError:
        print(
            "[ERROR] customtkinter not installed.\n"
            "Run:  pip install -r requirements.txt"
        )
        sys.exit(1)

    try:
        from ui.main_window import MainWindow
    except ImportError as e:
        print(f"[ERROR] Failed to import MainWindow: {e}")
        sys.exit(1)

    app = MainWindow()
    app.mainloop()
    logger.info("Application closed.")


def main_web():
    """Launch the Flask + SocketIO web UI."""
    logger.info("Starting WhatsApp RPA Automator (Web UI)…")
    try:
        import web_app  # noqa: F401 — runs the server via __name__ guard
        from web_app import app, socketio, open_browser
        import threading
        threading.Thread(target=open_browser, daemon=True).start()
        socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
    except ImportError as e:
        print(f"[ERROR] Failed to start web UI: {e}")
        print("Run:  pip install flask flask-socketio flask-cors")
        sys.exit(1)


if __name__ == "__main__":
    if "--web" in sys.argv:
        main_web()
    else:
        main_desktop()

