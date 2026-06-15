"""
ui/main_window.py
-----------------
Main application window for WhatsApp RPA Automator.
Settings are hidden behind a gear-icon popup dialog.
"""

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional, List, Dict

import customtkinter as ctk

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    SUPPORTED_BROWSERS,
    DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, DEFAULT_RETRY_COUNT,
    WARMUP_MSG_COUNT, WARMUP_DELAY_MIN, WARMUP_DELAY_MAX,
    OCCASIONAL_EVERY_N, OCCASIONAL_DELAY_MIN, OCCASIONAL_DELAY_MAX,
    SESSION_BREAK_MIN, SESSION_BREAK_MAX,
    DEEP_REST_MIN, DEEP_REST_MAX,
    DEFAULT_RETRY_DELAY, ENABLE_ATTACHMENTS,
)
from core.automation_engine import AutomationEngine
from utils.excel_reader import read_contacts, detect_duplicates, ExcelValidationError
from utils.logger import get_logger
from utils.settings_manager import load_settings, save_settings

logger = get_logger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


# ─────────────────────────────────────────────────────────────────────────────
# Settings Dialog
# ─────────────────────────────────────────────────────────────────────────────

class SettingsDialog(ctk.CTkToplevel):
    """
    Modal popup that exposes all configurable delay settings.
    Call .show() to open; reads/writes back to the parent MainWindow vars.
    """

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self._parent = parent
        self.title("⚙  Settings")
        self.geometry("520x720")
        self.resizable(False, True)
        self.configure(fg_color="#1a1a1a")
        self.grab_set()          # modal
        self.focus_set()
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Snapshot current values so Cancel can revert them
        p = parent
        self._snapshot = {
            "delay_min":       p._delay_min_var.get(),
            "delay_max":       p._delay_max_var.get(),
            "warmup_count":    p._warmup_count_var.get(),
            "warmup_min":      p._warmup_min_var.get(),
            "warmup_max":      p._warmup_max_var.get(),
            "occasional_n":    p._occasional_n_var.get(),
            "occasional_min":  p._occasional_min_var.get(),
            "occasional_max":  p._occasional_max_var.get(),
            "batch_min":       p._batch_break_min_var.get(),
            "batch_max":       p._batch_break_max_var.get(),
            "deep_min":        p._deep_rest_min_var.get(),
            "deep_max":        p._deep_rest_max_var.get(),
            "retry":           p._retry_var.get(),
            "retry_delay":     p._retry_delay_var.get(),
            "fwd_batch_min":   p._forward_batch_min_var.get(),
            "fwd_batch_max":   p._forward_batch_max_var.get(),
        }
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Header ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="#111111", corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="⚙  Delay Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#F1F5F9",
        ).pack(side="left", padx=18, pady=14)

        # ── Scrollable body ────────────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(self, fg_color="#1a1a1a")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        def section(title):
            ctk.CTkFrame(body, fg_color="#2a2a2a", height=1).pack(
                fill="x", padx=0, pady=(14, 0))
            ctk.CTkLabel(
                body, text=title,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#cccccc", anchor="w",
            ).pack(fill="x", padx=16, pady=(8, 2))

        def entry_row(parent_frame, label, var, desc=""):
            frm = ctk.CTkFrame(parent_frame, fg_color="transparent")
            frm.pack(fill="x", padx=16, pady=(4, 0))
            ctk.CTkLabel(
                frm, text=label,
                font=ctk.CTkFont(size=13),
                text_color="#aaaaaa", anchor="w", width=200,
            ).pack(side="left")
            ctk.CTkEntry(
                frm, textvariable=var,
                width=100, height=30,
                fg_color="#222222",
                border_color="#444444", border_width=1,
                font=ctk.CTkFont(size=14), justify="center",
            ).pack(side="right")

        def minmax_row(parent_frame, min_var, max_var, disabled=False):
            frm = ctk.CTkFrame(parent_frame, fg_color="transparent")
            frm.pack(fill="x", padx=16, pady=(4, 0))
            frm.columnconfigure((0, 1), weight=1)
            state = "disabled" if disabled else "normal"
            text_color = "#555555" if disabled else "#aaaaaa"
            for col, (lbl, var) in enumerate([("Min (sec)", min_var), ("Max (sec)", max_var)]):
                inner = ctk.CTkFrame(frm, fg_color="transparent")
                inner.grid(row=0, column=col, sticky="ew", padx=(0, 8 if col == 0 else 0))
                ctk.CTkLabel(
                    inner, text=lbl,
                    font=ctk.CTkFont(size=13), text_color=text_color, anchor="w",
                ).pack(anchor="w")
                ctk.CTkEntry(
                    inner, textvariable=var,
                    height=30, fg_color="#222222",
                    border_color="#444444", border_width=1,
                    font=ctk.CTkFont(size=14), justify="center",
                    state=state,
                ).pack(fill="x")

        p = self._parent

        # 1 ── Standard Delay ──────────────────────────────────────────────────
        section("Standard Delay")
        ctk.CTkLabel(body, text="Applied to most messages.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        minmax_row(body, p._delay_min_var, p._delay_max_var)

        # 2 ── Warm-up Delay ───────────────────────────────────────────────────
        section("Warm-up Delay  (first N messages)")
        ctk.CTkLabel(body, text="Extra-long delays at the very start of a session.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        entry_row(body, "Number of warm-up messages", p._warmup_count_var)
        minmax_row(body, p._warmup_min_var, p._warmup_max_var)

        # 3 ── Occasional Pause ────────────────────────────────────────────────
        section("Occasional Pause  (every Nth message)")
        ctk.CTkLabel(body, text="Fires a longer pause once every N messages.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        entry_row(body, "Trigger every N messages", p._occasional_n_var)
        minmax_row(body, p._occasional_min_var, p._occasional_max_var)

        # 4 ── Batch Break ─────────────────────────────────────────────────────
        section("Batch Break  (every 15–25 messages)")
        ctk.CTkLabel(body, text="Short session rest after a randomised batch.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        minmax_row(body, p._batch_break_min_var, p._batch_break_max_var)

        # 5 ── Deep Rest ───────────────────────────────────────────────────────
        section("Deep Rest  (triggers after 30–70 messages)")
        ctk.CTkLabel(body, text="Simulates end-of-day break to avoid spam detection.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        minmax_row(body, p._deep_rest_min_var, p._deep_rest_max_var)

        # 6 ── Forward Batch ───────────────────────────────────────────────────
        is_unknown = (p._mode_var.get() == "Unknown Contacts")
        section("Forward Batch")
        lbl = "Forward size (Disabled in Unknown Mode)" if is_unknown else "Randomised batch size for native forward."
        ctk.CTkLabel(body, text=lbl,
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        minmax_row(body, p._forward_batch_min_var, p._forward_batch_max_var, disabled=is_unknown)

        # 7 ── Retry ───────────────────────────────────────────────────────────
        section("Retry")
        ctk.CTkLabel(body, text="How many retries and how long to wait between them.",
                     font=ctk.CTkFont(size=12), text_color="#666666", anchor="w",
                     ).pack(fill="x", padx=16)
        entry_row(body, "Retry count", p._retry_var)
        entry_row(body, "Retry delay (sec)", p._retry_delay_var)

        # bottom padding
        ctk.CTkFrame(body, fg_color="transparent", height=12).pack()

        # ── Footer buttons ─────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color="#111111", corner_radius=0, height=56)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        # Save — green, right side
        ctk.CTkButton(
            footer, text="Save",
            command=self._save,
            fg_color="#22C55E", hover_color="#16A34A",
            text_color="#000000",
            font=ctk.CTkFont(size=14, weight="bold"),
            width=100, height=36, corner_radius=6,
        ).pack(side="right", padx=14, pady=10)

        # Cancel — grey, next to Save
        ctk.CTkButton(
            footer, text="Cancel",
            command=self._cancel,
            fg_color="#333333", hover_color="#444444",
            text_color="#aaaaaa",
            font=ctk.CTkFont(size=13),
            width=90, height=36, corner_radius=6,
        ).pack(side="right", padx=(0, 6), pady=10)

        # Reset Defaults — left side
        ctk.CTkButton(
            footer, text="Reset Defaults",
            command=self._reset_defaults,
            fg_color="transparent", hover_color="#2a2a2a",
            text_color="#666666",
            font=ctk.CTkFont(size=13),
            width=120, height=36, corner_radius=6,
            border_width=1, border_color="#333333",
        ).pack(side="left", padx=14, pady=10)

    def _save(self):
        """Validate all fields, persist to disk, then close."""
        p = self._parent
        fields = [
            p._delay_min_var, p._delay_max_var,
            p._warmup_count_var, p._warmup_min_var, p._warmup_max_var,
            p._occasional_n_var, p._occasional_min_var, p._occasional_max_var,
            p._batch_break_min_var, p._batch_break_max_var,
            p._deep_rest_min_var, p._deep_rest_max_var,
            p._retry_var, p._retry_delay_var,
            p._forward_batch_min_var, p._forward_batch_max_var,
        ]
        for var in fields:
            try:
                float(var.get())
            except ValueError:
                from tkinter import messagebox
                messagebox.showerror(
                    "Invalid Value",
                    f"'{var.get()}' is not a valid number. Please fix it before saving.",
                    parent=self,
                )
                return

        # Persist to disk
        save_settings({
            "delay_min":       float(p._delay_min_var.get()),
            "delay_max":       float(p._delay_max_var.get()),
            "warmup_count":    int(float(p._warmup_count_var.get())),
            "warmup_min":      float(p._warmup_min_var.get()),
            "warmup_max":      float(p._warmup_max_var.get()),
            "occasional_n":    int(float(p._occasional_n_var.get())),
            "occasional_min":  float(p._occasional_min_var.get()),
            "occasional_max":  float(p._occasional_max_var.get()),
            "batch_break_min": float(p._batch_break_min_var.get()),
            "batch_break_max": float(p._batch_break_max_var.get()),
            "deep_rest_min":   float(p._deep_rest_min_var.get()),
            "deep_rest_max":   float(p._deep_rest_max_var.get()),
            "retry":           int(float(p._retry_var.get())),
            "retry_delay":     float(p._retry_delay_var.get()),
            "forward_batch_min": int(float(p._forward_batch_min_var.get())),
            "forward_batch_max": int(float(p._forward_batch_max_var.get())),
        })
        self.destroy()

    def _cancel(self):
        """Revert all vars to the snapshot taken when the dialog opened."""
        p = self._parent
        p._delay_min_var.set(self._snapshot["delay_min"])
        p._delay_max_var.set(self._snapshot["delay_max"])
        p._warmup_count_var.set(self._snapshot["warmup_count"])
        p._warmup_min_var.set(self._snapshot["warmup_min"])
        p._warmup_max_var.set(self._snapshot["warmup_max"])
        p._occasional_n_var.set(self._snapshot["occasional_n"])
        p._occasional_min_var.set(self._snapshot["occasional_min"])
        p._occasional_max_var.set(self._snapshot["occasional_max"])
        p._batch_break_min_var.set(self._snapshot["batch_min"])
        p._batch_break_max_var.set(self._snapshot["batch_max"])
        p._deep_rest_min_var.set(self._snapshot["deep_min"])
        p._deep_rest_max_var.set(self._snapshot["deep_max"])
        p._retry_var.set(self._snapshot["retry"])
        p._retry_delay_var.set(self._snapshot["retry_delay"])
        p._forward_batch_min_var.set(self._snapshot["fwd_batch_min"])
        p._forward_batch_max_var.set(self._snapshot["fwd_batch_max"])
        self.destroy()

    def _reset_defaults(self):
        p = self._parent
        p._delay_min_var.set(str(DEFAULT_DELAY_MIN))
        p._delay_max_var.set(str(DEFAULT_DELAY_MAX))
        p._warmup_count_var.set(str(WARMUP_MSG_COUNT))
        p._warmup_min_var.set(str(WARMUP_DELAY_MIN))
        p._warmup_max_var.set(str(WARMUP_DELAY_MAX))
        p._occasional_n_var.set(str(OCCASIONAL_EVERY_N))
        p._occasional_min_var.set(str(OCCASIONAL_DELAY_MIN))
        p._occasional_max_var.set(str(OCCASIONAL_DELAY_MAX))
        p._batch_break_min_var.set(str(SESSION_BREAK_MIN))
        p._batch_break_max_var.set(str(SESSION_BREAK_MAX))
        p._deep_rest_min_var.set(str(DEEP_REST_MIN))
        p._deep_rest_max_var.set(str(DEEP_REST_MAX))
        p._retry_var.set(str(DEFAULT_RETRY_COUNT))
        p._retry_delay_var.set(str(DEFAULT_RETRY_DELAY))
        p._forward_batch_min_var.set("1")
        p._forward_batch_max_var.set("5")


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(ctk.CTk):

    APP_TITLE = "WhatsApp RPA Automator"
    APP_VERSION = "2.0"

    def __init__(self):
        super().__init__()
        self._contacts: List[Dict] = []
        self._engine: Optional[AutomationEngine] = None
        self._is_paused = False
        self._attachment_path: Optional[str] = None
        self._last_csv: str = ""
        self._settings_win: Optional[SettingsDialog] = None

        # ── Load persisted settings (falls back to config defaults) ─────────
        s = load_settings()

        # ── Settings vars (shared with SettingsDialog) ──────────────────────
        self._delay_min_var       = ctk.StringVar(value=str(s["delay_min"]))
        self._delay_max_var       = ctk.StringVar(value=str(s["delay_max"]))
        self._warmup_count_var    = ctk.StringVar(value=str(s["warmup_count"]))
        self._warmup_min_var      = ctk.StringVar(value=str(s["warmup_min"]))
        self._warmup_max_var      = ctk.StringVar(value=str(s["warmup_max"]))
        self._occasional_n_var    = ctk.StringVar(value=str(s["occasional_n"]))
        self._occasional_min_var  = ctk.StringVar(value=str(s["occasional_min"]))
        self._occasional_max_var  = ctk.StringVar(value=str(s["occasional_max"]))
        self._batch_break_min_var = ctk.StringVar(value=str(s["batch_break_min"]))
        self._batch_break_max_var = ctk.StringVar(value=str(s["batch_break_max"]))
        self._deep_rest_min_var   = ctk.StringVar(value=str(s["deep_rest_min"]))
        self._deep_rest_max_var   = ctk.StringVar(value=str(s.get("deep_rest_max", DEEP_REST_MAX)))
        self._retry_var           = ctk.StringVar(value=str(s.get("retry", DEFAULT_RETRY_COUNT)))
        self._retry_delay_var     = ctk.StringVar(value=str(s.get("retry_delay", DEFAULT_RETRY_DELAY)))
        self._forward_batch_min_var = ctk.StringVar(value=str(s.get("forward_batch_min", 1)))
        self._forward_batch_max_var = ctk.StringVar(value=str(s.get("forward_batch_max", 5)))

        self._configure_window()
        self._build_ui()
        self._log("Ready. Load Excel file and click START.", "INFO")

    def _configure_window(self):
        self.title(self.APP_TITLE)
        self.geometry("1000x700")
        self.minsize(900, 600)
        self.configure(fg_color="#2b2b2b")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.iconbitmap(default="")

    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────────────
        title_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", height=50)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        ctk.CTkLabel(
            title_frame,
            text=self.APP_TITLE,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=10)

        # ── Main body ──────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="#2b2b2b")
        body.pack(fill="both", expand=True, padx=10, pady=10)
        body.columnconfigure(0, weight=0, minsize=270)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_left_panel(body)
        self._build_right_panel(body)

    # ── Left panel ─────────────────────────────────────────────────────────────

    def _build_left_panel(self, parent):
        left = ctk.CTkScrollableFrame(parent, fg_color="#353535")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        # ── Excel section ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            left, text="EXCEL FILE",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(fill="x", padx=10, pady=(10, 5))

        self._excel_path_var = ctk.StringVar(value="No file selected")
        ctk.CTkLabel(
            left,
            textvariable=self._excel_path_var,
            font=ctk.CTkFont(size=14),
            text_color="#aaaaaa",
            wraplength=240,
            justify="left",
        ).pack(fill="x", padx=10, pady=0)

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(8, 0))
        btn_frame.columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_frame, text="Browse File",
            command=self._browse_excel,
            fg_color="#22C55E", hover_color="#16A34A",
            text_color="#000000",
            font=ctk.CTkFont(size=15),
            height=34, corner_radius=6,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="Reload",
            command=self._reload_excel,
            fg_color="#444444", hover_color="#555555",
            text_color="#ffffff",
            font=ctk.CTkFont(size=15),
            height=34, corner_radius=6,
        ).grid(row=0, column=1, sticky="ew")

        self._contact_count_lbl = ctk.CTkLabel(
            left,
            text="0 contacts loaded",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#4ADE80",
        )
        self._contact_count_lbl.pack(fill="x", padx=10, pady=(8, 12))

        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # ── Browser section ────────────────────────────────────────────────────
        ctk.CTkLabel(
            left, text="BROWSER",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(fill="x", padx=10, pady=(10, 5))

        self._browser_var = ctk.StringVar(value=SUPPORTED_BROWSERS[0])
        ctk.CTkOptionMenu(
            left,
            values=SUPPORTED_BROWSERS,
            variable=self._browser_var,
            fg_color="#444444",
            dropdown_fg_color="#353535",
            text_color="#ffffff",
            font=ctk.CTkFont(size=15),
            height=34, corner_radius=6, anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))

        self._dedup_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            left,
            text="Remove duplicate numbers",
            variable=self._dedup_var,
            font=ctk.CTkFont(size=15),
            checkbox_height=18, checkbox_width=18,
        ).pack(anchor="w", padx=10, pady=(0, 12))

        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # ── Mode section ───────────────────────────────────────────────────────
        ctk.CTkLabel(
            left, text="SENDING MODE",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(fill="x", padx=10, pady=(10, 5))

        self._mode_var = ctk.StringVar(value="Known Contacts")
        ctk.CTkSegmentedButton(
            left,
            values=["Known Contacts", "Unknown Contacts"],
            variable=self._mode_var,
            command=self._on_mode_change,
            font=ctk.CTkFont(size=14),
            height=34,
            selected_color="#22C55E",
            selected_hover_color="#16A34A",
        ).pack(fill="x", padx=10, pady=(0, 4))
        
        self._mode_desc_lbl = ctk.CTkLabel(
            left,
            text="Uses Forward dialog. Best for existing contacts.",
            font=ctk.CTkFont(size=12),
            text_color="#aaaaaa",
        )
        self._mode_desc_lbl.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # ── Attachment section ─────────────────────────────────────────────────
        if ENABLE_ATTACHMENTS:
            ctk.CTkLabel(
                left, text="ATTACHMENT (Optional)",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(fill="x", padx=10, pady=(10, 4))

            self._attach_name_var = ctk.StringVar(value="No file selected")
            ctk.CTkLabel(
                left,
                textvariable=self._attach_name_var,
                font=ctk.CTkFont(size=12),
                text_color="#aaaaaa",
                wraplength=235,
                justify="left",
            ).pack(fill="x", padx=10, pady=(0, 4))

            attach_btn_frame = ctk.CTkFrame(left, fg_color="transparent")
            attach_btn_frame.pack(fill="x", padx=10, pady=(0, 8))
            attach_btn_frame.columnconfigure((0, 1), weight=1)

            ctk.CTkButton(
                attach_btn_frame, text="📎  Browse File",
                command=self._browse_attachment,
                fg_color="#1E293B", hover_color="#334155",
                text_color="#60A5FA",
                font=ctk.CTkFont(size=14),
                height=34, corner_radius=6,
            ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

            self._attach_clear_btn = ctk.CTkButton(
                attach_btn_frame, text="✕  Clear",
                command=self._clear_attachment,
                fg_color="#444444", hover_color="#555555",
                text_color="#aaaaaa",
                font=ctk.CTkFont(size=14),
                height=34, corner_radius=6,
                state="disabled",
            )
            self._attach_clear_btn.grid(row=0, column=1, sticky="ew")

            ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # ── Settings gear button ───────────────────────────────────────────────
        settings_row = ctk.CTkFrame(left, fg_color="transparent")
        settings_row.pack(fill="x", padx=10, pady=(10, 6))
        settings_row.columnconfigure(0, weight=1)
        settings_row.columnconfigure(1, weight=0)

        ctk.CTkLabel(
            settings_row, text="Delay Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#F1F5F9", anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            settings_row,
            text="⚙",
            command=self._open_settings,
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#94A3B8",
            font=ctk.CTkFont(size=18),
            width=36, height=36,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # ── Action buttons ─────────────────────────────────────────────────────
        self._start_btn = ctk.CTkButton(
            left,
            text="START",
            command=self._start_automation,
            fg_color="#22C55E", hover_color="#16A34A",
            text_color="#000000",
            font=ctk.CTkFont(size=18, weight="bold"),
            height=46, corner_radius=6,
        )
        self._start_btn.pack(fill="x", padx=10, pady=(10, 8))

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        btn_row.columnconfigure((0, 1), weight=1)

        self._pause_btn = ctk.CTkButton(
            btn_row, text="PAUSE",
            command=self._toggle_pause,
            fg_color="#f59e0b", hover_color="#d97706",
            text_color="#000000",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=38, corner_radius=6, state="disabled",
        )
        self._pause_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._stop_btn = ctk.CTkButton(
            btn_row, text="STOP",
            command=self._stop_automation,
            fg_color="#ef4444", hover_color="#dc2626",
            text_color="#ffffff",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=38, corner_radius=6, state="disabled",
        )
        self._stop_btn.grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(
            left, text="📂  Reports",
            command=self._export_report,
            fg_color="#444444", hover_color="#555555",
            text_color="#60A5FA",
            font=ctk.CTkFont(size=15),
            height=34, corner_radius=6,
        ).pack(fill="x", padx=10, pady=(0, 12))

    # ── Right panel ────────────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        right = ctk.CTkFrame(parent, fg_color="#2b2b2b")
        right.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)   # stats bar
        right.rowconfigure(1, weight=0)   # progress bar
        right.rowconfigure(2, weight=1)   # tabs

        # ─ Stats bar ────────────────────────────────────────────────────
        stats_frame = ctk.CTkFrame(right, fg_color="#1a1a1a", height=80)
        stats_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        stats_frame.pack_propagate(False)
        stats_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self._stat_labels = {}
        for label, initial in [("TOTAL", "0"), ("SENT", "0"), ("FAILED", "0"), ("SKIPPED", "0")]:
            col = ["TOTAL", "SENT", "FAILED", "SKIPPED"].index(label)
            frm = ctk.CTkFrame(stats_frame, fg_color="transparent")
            frm.grid(row=0, column=col, padx=4, pady=10)

            val_lbl = ctk.CTkLabel(
                frm, text=initial,
                font=ctk.CTkFont(size=26, weight="bold"),
                text_color="#22C55E",
            )
            val_lbl.pack()

            ctk.CTkLabel(
                frm, text=label,
                font=ctk.CTkFont(size=13),
                text_color="#aaaaaa",
            ).pack()

            self._stat_labels[label] = val_lbl

        # ─ Progress bar (dedicated row, no overlap) ──────────────────────────
        self._progress_bar = ctk.CTkProgressBar(
            right, fg_color="#444444",
            progress_color="#22C55E",
            height=6, corner_radius=2,
        )
        self._progress_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 2))
        self._progress_bar.set(0)

        # Tabs
        self._tab_view = ctk.CTkTabview(
            right,
            fg_color="#353535",
            segmented_button_fg_color="#1a1a1a",
            segmented_button_selected_color="#22C55E",
            text_color="#ffffff",
            corner_radius=0,
        )
        self._tab_view.grid(row=2, column=0, sticky="nsew")

        # Results tab
        t1 = self._tab_view.add("Results")
        t1.columnconfigure(0, weight=1)
        t1.rowconfigure(0, weight=1)
        self._results_text = ctk.CTkTextbox(
            t1, fg_color="#1a1a1a", text_color="#ffffff",
            font=ctk.CTkFont(family="Consolas", size=15),
            border_width=0, state="disabled", wrap="word",
        )
        self._results_text.grid(row=0, column=0, sticky="nsew")

        # Console tab
        t2 = self._tab_view.add("Console")
        t2.columnconfigure(0, weight=1)
        t2.rowconfigure(0, weight=1)
        self._console_text = ctk.CTkTextbox(
            t2, fg_color="#0a0a0a", text_color="#ffffff",
            font=ctk.CTkFont(family="Consolas", size=15),
            border_width=0, state="disabled", wrap="word",
        )
        self._console_text.grid(row=0, column=0, sticky="nsew")

        # Configure color tags for log levels (called once after widget is created)
        self._console_text._textbox.tag_configure("INFO",    foreground="#F1F5F9")
        self._console_text._textbox.tag_configure("SUCCESS", foreground="#4ADE80")
        self._console_text._textbox.tag_configure("WARNING", foreground="#FCD34D")
        self._console_text._textbox.tag_configure("ERROR",   foreground="#FB7185")

        btn_frame = ctk.CTkFrame(t2, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="e", padx=8, pady=8)
        ctk.CTkButton(
            btn_frame, text="Clear",
            command=self._clear_console,
            fg_color="#444444", hover_color="#555555",
            text_color="#aaaaaa",
            font=ctk.CTkFont(size=14),
            height=28, width=80, corner_radius=4,
        ).pack()

    # ══════════════════════════════════════════════════════════════════════════
    # Settings popup
    # ══════════════════════════════════════════════════════════════════════════

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus_set()
            return
        self._settings_win = SettingsDialog(self)

    # ══════════════════════════════════════════════════════════════════════════
    # Event Handlers
    # ══════════════════════════════════════════════════════════════════════════

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Select Contact File",
            filetypes=[
                ("All supported files", "*.xlsx *.xls *.csv"),
                ("Excel files", "*.xlsx *.xls"),
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._load_excel(path)

    def _reload_excel(self):
        path = self._excel_path_var.get()
        if path and path != "No file selected" and os.path.isfile(path):
            self._load_excel(path)
        else:
            messagebox.showwarning("No File", "Browse and select an Excel file first.")

    def _load_excel(self, path: str):
        try:
            contacts = read_contacts(path)
            if self._dedup_var.get():
                before = len(contacts)
                contacts = detect_duplicates(contacts)
                removed = before - len(contacts)
                if removed:
                    self._log(f"Removed {removed} duplicate(s).", "WARNING")

            self._contacts = contacts
            self._excel_path_var.set(Path(path).name)
            n = len(contacts)
            self._contact_count_lbl.configure(text=f"{n} contacts loaded")
            self._stat_labels["TOTAL"].configure(text=str(n))
            self._log(f"Loaded {n} contacts from '{Path(path).name}'", "SUCCESS")

        except (FileNotFoundError, ValueError, ExcelValidationError) as e:
            messagebox.showerror("Excel Error", str(e))
            self._log(f"Excel error: {e}", "ERROR")

    def _on_mode_change(self, value):
        if value == "Known Contacts":
            self._mode_desc_lbl.configure(text="Uses Forward dialog. Best for existing contacts.")
            self.title(f"{self.APP_TITLE} — Known Mode")
        else:
            self._mode_desc_lbl.configure(text="Uses New Chat + Paste. Best for brand new numbers.")
            self.title(f"{self.APP_TITLE} — Unknown Mode")

    def _start_automation(self):
        if not self._contacts:
            messagebox.showwarning("No Contacts", "Load an Excel file first.")
            return
        if self._engine and self._engine.is_running:
            messagebox.showinfo("Running", "Automation is already running.")
            return

        try:
            delay_min     = float(self._delay_min_var.get())
            delay_max     = float(self._delay_max_var.get())
            retry         = int(self._retry_var.get())
            retry_delay   = float(self._retry_delay_var.get())
            warmup_count  = int(self._warmup_count_var.get())
            warmup_min    = float(self._warmup_min_var.get())
            warmup_max    = float(self._warmup_max_var.get())
            occ_n         = int(self._occasional_n_var.get())
            occ_min       = float(self._occasional_min_var.get())
            occ_max       = float(self._occasional_max_var.get())
            batch_min     = float(self._batch_break_min_var.get())
            batch_max     = float(self._batch_break_max_var.get())
            deep_min      = float(self._deep_rest_min_var.get())
            deep_max      = float(self._deep_rest_max_var.get())
            fwd_batch_min = int(float(self._forward_batch_min_var.get()))
            fwd_batch_max = int(float(self._forward_batch_max_var.get()))
        except ValueError:
            messagebox.showerror("Invalid Settings", "All delay and retry fields must be numbers.")
            return

        if delay_min > delay_max:
            messagebox.showerror("Invalid Delay", "Min delay cannot exceed max delay.")
            return

        self._reset_results()
        self._reset_counters()
        self._is_paused = False
        self._set_running_state(True)

        self._engine = AutomationEngine(
            contacts=self._contacts,
            browser=self._browser_var.get(),
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
            attachment_path=self._attachment_path,
            mode="known" if self._mode_var.get() == "Known Contacts" else "unknown",
            on_status=lambda m: self.after(0, self._log, m, "INFO"),
            on_log=lambda m, l: self.after(0, self._log, m, l),
            on_progress=lambda c, t: self.after(0, self._on_progress, c, t),
            on_contact_result=lambda c, s, e: self.after(0, self._on_contact_result, c, s, e),
            on_complete=lambda cv, tx: self.after(0, self._on_complete, cv, tx),
        )
        self._engine.start()
        mode_label = "Known (Forward)" if self._mode_var.get() == "Known Contacts" else "Unknown (New Chat+Paste)"
        self._log(f"Automation started! Mode: {mode_label}", "SUCCESS")

    def _toggle_pause(self):
        if not self._engine:
            return
        if self._is_paused:
            self._engine.resume()
            self._is_paused = False
            self._pause_btn.configure(text="PAUSE")
            self._log("Resumed.", "INFO")
        else:
            self._engine.pause()
            self._is_paused = True
            self._pause_btn.configure(text="RESUME")
            done = self._engine.success_count + self._engine.failed_count
            total = self._engine.total
            self._log(
                f"Paused at contact {done}/{total} — click RESUME to continue.",
                "WARNING",
            )

    def _stop_automation(self):
        if self._engine:
            self._engine.stop()
            self._set_running_state(False)
            self._log("Stop requested. Finishing current task…", "WARNING")

    def _browse_attachment(self):
        path = filedialog.askopenfilename(
            title="Select Attachment File",
            filetypes=[
                ("All supported", "*.pdf *.jpg *.jpeg *.png *.gif *.mp4 *.mp3 *.docx *.xlsx *.zip"),
                ("Images",        "*.jpg *.jpeg *.png *.gif *.webp"),
                ("Videos",        "*.mp4 *.avi *.mov *.mkv"),
                ("Documents",     "*.pdf *.docx *.xlsx *.pptx *.txt"),
                ("Audio",         "*.mp3 *.ogg *.wav *.aac"),
                ("All files",     "*.*"),
            ],
        )
        if path:
            self._attachment_path = path
            self._attach_name_var.set(Path(path).name)
            self._attach_clear_btn.configure(state="normal")
            self._log(f"Attachment set: {Path(path).name}", "INFO")

    def _clear_attachment(self):
        self._attachment_path = None
        self._attach_name_var.set("No file selected")
        self._attach_clear_btn.configure(state="disabled")
        self._log("Attachment cleared.", "INFO")

    def _export_report(self):
        from config import REPORTS_DIR
        os.startfile(str(REPORTS_DIR))

    # ══════════════════════════════════════════════════════════════════════════
    # Engine Callbacks
    # ══════════════════════════════════════════════════════════════════════════

    def _on_progress(self, current: int, total: int):
        if total > 0:
            self._progress_bar.set(current / total)

    def _on_contact_result(self, contact: dict, status: str, error: str):
        name = contact.get("name", "?")
        phone = contact.get("phone", "?")
        result = f"{name:20} | +{phone:12} | {status}"

        self._results_text.configure(state="normal")
        self._results_text.insert("end", result + "\n")
        self._results_text.configure(state="disabled")
        self._results_text.see("end")

        key_map = {"SUCCESS": "SENT", "FAILED": "FAILED", "SKIPPED": "SKIPPED"}
        card_key = key_map.get(status.upper())
        if card_key:
            cur = int(self._stat_labels[card_key].cget("text"))
            self._stat_labels[card_key].configure(text=str(cur + 1))

        self._tab_view.set("Results")

    def _on_complete(self, csv_path: str, txt_path: str):
        self._last_csv = csv_path
        self._set_running_state(False)
        self._progress_bar.set(1.0)
        self._log(f"Report saved: {csv_path}", "SUCCESS")
        messagebox.showinfo(
            "Done!",
            f"Automation complete!\nReport: {csv_path}",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        
        # Prepend mode tag if missing, to clearly indicate context
        mode = "KNOWN" if self._mode_var.get() == "Known Contacts" else "UNKNOWN"
        if not (message.startswith("[KNOWN]") or message.startswith("[UNKNOWN]")):
            message = f"[{mode}] {message}"
            
        text = f"[{ts}] {message}"
        # Map level to console color tag
        tag = level.upper() if level.upper() in ("INFO", "SUCCESS", "WARNING", "ERROR") else "INFO"
        self._console_text.configure(state="normal")
        self._console_text._textbox.insert("end", text + "\n", tag)
        self._console_text.configure(state="disabled")
        self._console_text._textbox.see("end")
        # If a block banner is detected, auto-switch to Console for visibility
        if "⛔ Blocked:" in message:
            self._tab_view.set("Console")

    def _clear_console(self):
        self._console_text.configure(state="normal")
        self._console_text.delete("1.0", "end")
        self._console_text.configure(state="disabled")

    def _reset_results(self):
        self._results_text.configure(state="normal")
        self._results_text.delete("1.0", "end")
        self._results_text.configure(state="disabled")

    def _set_running_state(self, running: bool):
        self._start_btn.configure(state="disabled" if running else "normal")
        self._pause_btn.configure(state="normal" if running else "disabled")
        self._stop_btn.configure(state="normal" if running else "disabled")

    def _reset_counters(self):
        for key in ("SENT", "FAILED", "SKIPPED"):
            self._stat_labels[key].configure(text="0")
        self._progress_bar.set(0)

    def _on_close(self):
        if self._engine and self._engine.is_running:
            if not messagebox.askyesno("Quit", "Automation is running. Stop and quit?"):
                return
            self._engine.stop()
        self.destroy()
