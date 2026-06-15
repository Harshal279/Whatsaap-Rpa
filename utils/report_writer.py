"""
utils/report_writer.py
----------------------
Handles writing delivery reports to CSV and TXT files.
Provides an append-safe writer so records are saved incrementally
(no data loss if the application crashes mid-run).
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from config import REPORTS_DIR, REPORT_COLUMNS


class ReportWriter:
    """
    Thread-safe incremental delivery report writer.

    Writes one row per contact to both a CSV file and a plain-text
    summary log. Files are named with the session timestamp so each
    automation run creates its own report.
    """

    def __init__(self, session_id: str | None = None):
        ts = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path: Path = REPORTS_DIR / f"report_{ts}.csv"
        self.txt_path: Path = REPORTS_DIR / f"report_{ts}.txt"

        self._csv_initialized = False
        self._init_files()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _init_files(self):
        """Create CSV with header row and TXT with a header block."""
        # CSV
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
                writer.writeheader()
            self._csv_initialized = True

        # TXT
        if not self.txt_path.exists():
            with open(self.txt_path, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write(" WhatsApp RPA - Delivery Report\n")
                f.write(f" Session started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")

    # ── Public API ────────────────────────────────────────────────────────────

    def write_record(
        self,
        name: str,
        phone: str,
        message: str,
        status: str,           # "SUCCESS" | "FAILED" | "SKIPPED"
        error: str = "",
        method: str = "",      # "TYPED" | "FORWARDED" | "FALLBACK_PASTE" | "NEW_CHAT_PASTE" | "SKIPPED" | ""
    ):
        """
        Append a single delivery record to both report files.

        Args:
            name:    Contact name.
            phone:   Phone number (digits only).
            message: The message that was (attempted to be) sent.
            status:  Outcome of the send attempt.
            error:   Error message (empty on success).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record: Dict[str, Any] = {
            "Timestamp": timestamp,
            "Name": name,
            "Phone": phone,
            "Message": message[:60] + (".." if len(message) > 60 else ""),
            "Status": status,
            "Method": method,
            "Error": error,
        }

        # CSV
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
            writer.writerow(record)

        # TXT
        status_icon = {"SUCCESS": "+", "FAILED": "-", "SKIPPED": "o"}.get(status, "?")
        line = (
            f"[{timestamp}] {status_icon} {status:<8} | "
            f"{name:<20} | +{phone}\n"
        )
        if error:
            line += f"              Error: {error}\n"

        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write(line)

    def write_summary(self, total: int, success: int, failed: int, skipped: int,
                       typed: int = 0, forwarded: int = 0, fallback: int = 0,
                       new_chat: int = 0, mode: str = "known"):
        """Append a final summary block to the TXT report."""
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write(" SUMMARY\n")
            f.write("=" * 60 + "\n")
            f.write(f" Mode            : {'Known Contacts (Forward)' if mode == 'known' else 'Unknown Contacts (New Chat+Paste)'}\n")
            f.write(f" Total contacts  : {total}\n")
            f.write(f" Messages sent   : {success}\n")
            if mode == "known":
                f.write(f"   ├ via Typed    : {typed}\n")
                f.write(f"   ├ via Forward  : {forwarded}\n")
                f.write(f"   └ via Paste FB : {fallback}\n")
            else:
                f.write(f"   └ via NewChat  : {new_chat}\n")
            f.write(f" Failed          : {failed}\n")
            f.write(f" Skipped         : {skipped}\n")
            f.write(f" Completed at    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n")

    @property
    def csv_file(self) -> str:
        return str(self.csv_path)

    @property
    def txt_file(self) -> str:
        return str(self.txt_path)
