"""
config.py
---------
Central configuration for WhatsApp RPA application.
All constants, defaults, and paths are defined here.
"""

import os
from pathlib import Path

# ── Directory Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"
ASSETS_DIR = BASE_DIR / "assets"
BROWSER_PROFILES_DIR = BASE_DIR / "browser_profiles"

# Ensure directories exist
for _dir in [LOGS_DIR, REPORTS_DIR, ASSETS_DIR, BROWSER_PROFILES_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ── WhatsApp Settings ──────────────────────────────────────────────────────────
WHATSAPP_WEB_URL = "https://web.whatsapp.com"
QR_WAIT_TIMEOUT = 120        # seconds to wait for QR code scan
MESSAGE_SEND_TIMEOUT = 30    # seconds to wait for message box to appear
PAGE_LOAD_TIMEOUT = 60       # seconds for initial page load

# ── Automation Defaults ────────────────────────────────────────────────────────
DEFAULT_DELAY_MIN = 45       # standard delay min between messages (seconds)
DEFAULT_DELAY_MAX = 95       # standard delay max between messages (seconds)
DEFAULT_RETRY_COUNT = 2      # number of retries for failed messages
DEFAULT_RETRY_DELAY = 35     # wait before retrying (seconds)

# ── Warm-up Delays (first N messages) ──────────────────────────────────────────
WARMUP_MSG_COUNT     = 8     # how many messages to treat as "warm-up"
WARMUP_DELAY_MIN     = 90    # warm-up delay lower bound (seconds)
WARMUP_DELAY_MAX     = 180   # warm-up delay upper bound (seconds)

# ── Occasional Longer Pause (every Nth message) ────────────────────────────────
OCCASIONAL_EVERY_N   = 7     # fire a longer pause every N messages
OCCASIONAL_DELAY_MIN = 180   # occasional pause lower bound (seconds)
OCCASIONAL_DELAY_MAX = 300   # occasional pause upper bound (seconds)

# ── Session / Safety Limits ────────────────────────────────────────────────────
SESSION_BATCH_SIZE   = 20    # take a long break after every N messages
SESSION_BREAK_MIN    = 300   # long-break lower bound (seconds) — 5 min
SESSION_BREAK_MAX    = 600   # long-break upper bound (seconds) — 10 min
DAILY_MESSAGE_LIMIT  = 30    # hard cap per session (0 = unlimited)

# ── Deep Rest ──────────────────────────────────────────────────────────────────
DEEP_REST_THRESHOLD_MIN = 30    # fire deep rest after at least this many msgs
DEEP_REST_THRESHOLD_MAX = 70    # fire deep rest before this many msgs
DEEP_REST_MIN           = 1800  # deep rest lower bound (seconds) — 30 min
DEEP_REST_MAX           = 5400  # deep rest upper bound (seconds) — 90 min

# ── Forward Messaging ─────────────────────────────────────────────────────────
FORWARD_BATCH_MIN           = 5     # min contacts per forward action (randomised)
FORWARD_BATCH_MAX           = 5     # max contacts per forward action (randomised)
FORWARD_SEARCH_WAIT         = 2.5   # seconds to wait for results in forward dialog
FORWARD_DIALOG_TIMEOUT      = 15    # seconds to wait for the forward dialog to open
WHATSAPP_MAX_FORWARD_CONTACTS = 5   # hard limit enforced by WhatsApp — do not exceed

# ── Features ───────────────────────────────────────────────────────────────────
ENABLE_ATTACHMENTS   = False   # Set to False to hide the attachment UI card

# ── Browser Options ────────────────────────────────────────────────────────────
# On Linux (Render / Docker) only Chrome is available.
# On Windows, Edge and Brave are also supported.
if os.name == "nt":
    SUPPORTED_BROWSERS = ["Chrome", "Edge", "Brave"]
else:
    SUPPORTED_BROWSERS = ["Chrome"]

# Windows-only Brave paths (not used on Linux/Render)
if os.name == "nt":
    BRAVE_PATHS = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
else:
    BRAVE_PATHS = []   # Brave not available on Linux

# ── Excel Column Names ─────────────────────────────────────────────────────────
EXCEL_COL_NAME = "Name"
EXCEL_COL_PHONE = "Phone"
EXCEL_COL_MESSAGE = "Message"

# ── UI Theme Colors ────────────────────────────────────────────────────────────
# All colours are WCAG-AA contrast-compliant on the dark background.
THEME = {
    # ── Backgrounds ─────────────────────────────────────────────
    "bg_primary":   "#080C14",   # deepest bg (root window)
    "bg_secondary": "#0D1321",   # sidebar, navbar
    "bg_card":      "#111827",   # card fill (old; kept for compat)
    "surface":      "#111827",   # card / panel surfaces
    "surface_hi":   "#1E293B",   # elevated surface (hover states)

    # ── Accent / brand colours ───────────────────────────────────
    "accent":        "#22C55E",  # WhatsApp green-500
    "accent_dark":   "#16A34A",  # green-600 (hover)
    "accent_glow":   "#4ADE80",  # green-400 (glow/highlight)
    "accent_red":    "#FB7185",  # rose-400
    "accent_red_dk": "#E11D48",  # rose-600
    "accent_yellow": "#FCD34D",  # amber-300
    "accent_blue":   "#60A5FA",  # blue-400

    # ── Text ─────────────────────────────────────────────────────
    "text_primary":  "#F1F5F9",  # slate-100  — main labels  WCAG AAA
    "text_muted":    "#94A3B8",  # slate-400  — secondary    WCAG AA
    "text_secondary":"#94A3B8",  # alias kept for backwards-compat

    # ── Borders / dividers ───────────────────────────────────────
    "border":        "#1E293B",  # slate-800

    # ── Semantic ─────────────────────────────────────────────────
    "success": "#14532D",
    "error":   "#450A0A",
    "warning": "#451A03",
}

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE = LOGS_DIR / "whatsapp_rpa.log"

# ── Report ─────────────────────────────────────────────────────────────────────
REPORT_COLUMNS = ["Timestamp", "Name", "Phone", "Message", "Status", "Method", "Error"]
