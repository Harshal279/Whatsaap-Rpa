"""
utils/settings_manager.py
--------------------------
Persists user-configurable settings to a JSON file so they survive restarts.
"""

import json
from pathlib import Path

from config import (
    BASE_DIR,
    DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, DEFAULT_RETRY_COUNT, DEFAULT_RETRY_DELAY,
    WARMUP_MSG_COUNT, WARMUP_DELAY_MIN, WARMUP_DELAY_MAX,
    OCCASIONAL_EVERY_N, OCCASIONAL_DELAY_MIN, OCCASIONAL_DELAY_MAX,
    SESSION_BREAK_MIN, SESSION_BREAK_MAX,
    DEEP_REST_MIN, DEEP_REST_MAX,
)

SETTINGS_FILE = BASE_DIR / "user_settings.json"

DEFAULTS = {
    "delay_min":       DEFAULT_DELAY_MIN,
    "delay_max":       DEFAULT_DELAY_MAX,
    "warmup_count":    WARMUP_MSG_COUNT,
    "warmup_min":      WARMUP_DELAY_MIN,
    "warmup_max":      WARMUP_DELAY_MAX,
    "occasional_n":    OCCASIONAL_EVERY_N,
    "occasional_min":  OCCASIONAL_DELAY_MIN,
    "occasional_max":  OCCASIONAL_DELAY_MAX,
    "batch_break_min": SESSION_BREAK_MIN,
    "batch_break_max": SESSION_BREAK_MAX,
    "deep_rest_min":   DEEP_REST_MIN,
    "deep_rest_max":   DEEP_REST_MAX,
    "retry":           DEFAULT_RETRY_COUNT,
    "retry_delay":     DEFAULT_RETRY_DELAY,
    "forward_batch_min": 1,
    "forward_batch_max": 5,
}


def load_settings() -> dict:
    """Load settings from disk. Falls back to defaults for any missing key."""
    settings = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key in DEFAULTS:
                if key in saved:
                    settings[key] = saved[key]
        except Exception:
            pass  # corrupt file — use defaults silently
    return settings


def save_settings(settings: dict) -> None:
    """Write settings dict to disk."""
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[settings_manager] Could not save settings: {e}")
