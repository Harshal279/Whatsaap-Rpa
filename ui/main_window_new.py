"""
ui/main_window.py  (Testing Phase - Basic UI)
----------------------------------------------
Simplified, basic UI for testing phase. No fancy styling or animations.
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

from config import SUPPORTED_BROWSERS, DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, DEFAULT_RETRY_COUNT, ENABLE_ATTACHMENTS
from core.automation_engine import AutomationEngine
from utils.excel_reader import read_contacts, detect_duplicates, ExcelValidationError
from utils.logger import get_logger

logger = get_logger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


class MainWindow(ctk.CTk):

    APP_TITLE = "WhatsApp RPA Automator"
    APP_VERSION = "1"

    def __init__(self):
        super().__init__()
        self._contacts: List[Dict] = []
        self._engine: Optional[AutomationEngine] = None
        self._is_paused = False
        self._attachment_path: Optional[str] = None
        self._last_csv: str = ""

        self._configure_window()
        self._build_ui()
        self._log("Ready. Load Excel file and click START.", "INFO")

    def _configure_window(self):
        self.title(self.APP_TITLE)
        self.geometry("1000x700")
        self.minsize(900, 600)
        self.configure(fg_color="#2b2b2b")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Title bar
        title_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", height=50)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)

        ctk.CTkLabel(
            title_frame,
            text=self.APP_TITLE,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=10)

        # Main body
        body = ctk.CTkFrame(self, fg_color="#2b2b2b")
        body.pack(fill="both", expand=True, padx=10, pady=10)
        body.columnconfigure(0, weight=0, minsize=280)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left panel
        self._build_left_panel(body)

        # Right panel
        self._build_right_panel(body)

    def _build_left_panel(self, parent):
        """Build left sidebar with controls."""
        left = ctk.CTkScrollableFrame(parent, fg_color="#353535")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        # === EXCEL SECTION ===
        ctk.CTkLabel(
            left, text="EXCEL FILE",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(fill="x", padx=10, pady=(10, 5))

        self._excel_path_var = ctk.StringVar(value="No file selected")
        path_lbl = ctk.CTkLabel(
            left,
            textvariable=self._excel_path_var,
            font=ctk.CTkFont(size=10),
            text_color="#aaaaaa",
            wraplength=250,
            justify="left",
        )
        path_lbl.pack(fill="x", padx=10, pady=0)

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(8, 0))
        btn_frame.columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_frame,
            text="Browse File",
            command=self._browse_excel,
            fg_color="#22C55E",
            hover_color="#16A34A",
            text_color="#000000",
            font=ctk.CTkFont(size=11),
            height=32,
            corner_radius=4,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            btn_frame,
            text="Reload",
            command=self._reload_excel,
            fg_color="#444444",
            hover_color="#555555",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11),
            height=32,
            corner_radius=4,
        ).grid(row=0, column=1, sticky="ew")

        self._contact_count_lbl = ctk.CTkLabel(
            left,
            text="0 contacts loaded",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#4ADE80",
        )
        self._contact_count_lbl.pack(fill="x", padx=10, pady=(8, 12))

        # Separator
        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # === BROWSER SECTION ===
        ctk.CTkLabel(
            left, text="BROWSER",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(fill="x", padx=10, pady=(10, 5))

        self._browser_var = ctk.StringVar(value=SUPPORTED_BROWSERS[0])
        ctk.CTkOptionMenu(
            left,
            values=SUPPORTED_BROWSERS,
            variable=self._browser_var,
            fg_color="#444444",
            dropdown_fg_color="#353535",
            text_color="#ffffff",
            font=ctk.CTkFont(size=11),
            height=32,
            corner_radius=4,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))

        self._dedup_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            left,
            text="Remove duplicate numbers",
            variable=self._dedup_var,
            font=ctk.CTkFont(size=11),
            checkbox_height=18,
            checkbox_width=18,
        ).pack(anchor="w", padx=10, pady=(0, 12))

        # Separator
        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # === SETTINGS SECTION ===
        ctk.CTkLabel(
            left, text="SETTINGS",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(fill="x", padx=10, pady=(10, 8))

        # Delay
        ctk.CTkLabel(
            left, text="Message Delay (sec)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#aaaaaa",
        ).pack(fill="x", padx=10, pady=(0, 4))

        delay_row = ctk.CTkFrame(left, fg_color="transparent")
        delay_row.pack(fill="x", padx=10, pady=(0, 10))
        delay_row.columnconfigure((0, 1), weight=1)

        for label, var_name, default in [
            ("Min", "_delay_min_var", str(DEFAULT_DELAY_MIN)),
            ("Max", "_delay_max_var", str(DEFAULT_DELAY_MAX)),
        ]:
            ctk.CTkLabel(delay_row, text=label, font=ctk.CTkFont(size=9)).grid(
                row=0, column=(0 if label == "Min" else 1), sticky="w"
            )
            var = ctk.StringVar(value=default)
            setattr(self, var_name, var)

            ctk.CTkEntry(
                delay_row,
                textvariable=var,
                width=60,
                height=28,
                fg_color="#1a1a1a",
                border_color="#555555",
                border_width=1,
                font=ctk.CTkFont(size=11),
                justify="center",
            ).grid(row=1, column=(0 if label == "Min" else 1), sticky="ew", padx=(0, 4))

        # Retry
        ctk.CTkLabel(
            left, text="Retry Count",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#aaaaaa",
        ).pack(fill="x", padx=10, pady=(0, 4))

        self._retry_var = ctk.StringVar(value=str(DEFAULT_RETRY_COUNT))
        ctk.CTkEntry(
            left,
            textvariable=self._retry_var,
            width=60,
            height=28,
            fg_color="#1a1a1a",
            border_color="#555555",
            border_width=1,
            font=ctk.CTkFont(size=11),
            justify="center",
        ).pack(anchor="w", padx=10, pady=(0, 12))

        # Separator
        ctk.CTkFrame(left, fg_color="#444444", height=1).pack(fill="x", padx=0, pady=5)

        # === ACTION BUTTONS ===
        self._start_btn = ctk.CTkButton(
            left,
            text="START",
            command=self._start_automation,
            fg_color="#22C55E",
            hover_color="#16A34A",
            text_color="#000000",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=42,
            corner_radius=4,
        )
        self._start_btn.pack(fill="x", padx=10, pady=(12, 8))

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))
        btn_row.columnconfigure((0, 1), weight=1)

        self._pause_btn = ctk.CTkButton(
            btn_row,
            text="PAUSE",
            command=self._toggle_pause,
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#000000",
            font=ctk.CTkFont(size=10, weight="bold"),
            height=36,
            corner_radius=4,
            state="disabled",
        )
        self._pause_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._stop_btn = ctk.CTkButton(
            btn_row,
            text="STOP",
            command=self._stop_automation,
            fg_color="#ef4444",
            hover_color="#dc2626",
            text_color="#ffffff",
            font=ctk.CTkFont(size=10, weight="bold"),
            height=36,
            corner_radius=4,
            state="disabled",
        )
        self._stop_btn.grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(
            left,
            text="Reports",
            command=self._export_report,
            fg_color="#444444",
            hover_color="#555555",
            text_color="#60A5FA",
            font=ctk.CTkFont(size=11),
            height=32,
            corner_radius=4,
        ).pack(fill="x", padx=10, pady=(0, 12))

    def _build_right_panel(self, parent):
        """Build right side with results and console."""
        right = ctk.CTkFrame(parent, fg_color="#2b2b2b")
        right.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)

        # Stats bar
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
                frm,
                text=initial,
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color="#22C55E",
            )
            val_lbl.pack()

            ctk.CTkLabel(
                frm,
                text=label,
                font=ctk.CTkFont(size=9),
                text_color="#aaaaaa",
            ).pack()

            self._stat_labels[label] = val_lbl

        # Progress bar
        self._progress_bar = ctk.CTkProgressBar(
            right,
            fg_color="#444444",
            progress_color="#22C55E",
            height=6,
            corner_radius=2,
        )
        self._progress_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(0, 5))
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
        self._tab_view.grid(row=1, column=0, sticky="nsew")

        # Results tab
        t1 = self._tab_view.add("Results")
        t1.columnconfigure(0, weight=1)
        t1.rowconfigure(0, weight=1)

        self._results_text = ctk.CTkTextbox(
            t1,
            fg_color="#1a1a1a",
            text_color="#ffffff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=0,
            state="disabled",
            wrap="word",
        )
        self._results_text.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Console tab
        t2 = self._tab_view.add("Console")
        t2.columnconfigure(0, weight=1)
        t2.rowconfigure(0, weight=1)

        self._console_text = ctk.CTkTextbox(
            t2,
            fg_color="#0a0a0a",
            text_color="#ffffff",
            font=ctk.CTkFont(family="Consolas", size=10),
            border_width=0,
            state="disabled",
            wrap="word",
        )
        self._console_text.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        btn_frame = ctk.CTkFrame(t2, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="e", padx=8, pady=8)

        ctk.CTkButton(
            btn_frame,
            text="Clear",
            command=self._clear_console,
            fg_color="#444444",
            hover_color="#555555",
            text_color="#aaaaaa",
            font=ctk.CTkFont(size=10),
            height=28,
            width=80,
            corner_radius=4,
        ).pack()

    # ═══════════════════════════════════════════════════════════════
    # Event Handlers
    # ═══════════════════════════════════════════════════════════════

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
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

    def _start_automation(self):
        if not self._contacts:
            messagebox.showwarning("No Contacts", "Load an Excel file first.")
            return
        if self._engine and self._engine.is_running:
            messagebox.showinfo("Running", "Automation is already running.")
            return

        try:
            delay_min = float(self._delay_min_var.get())
            delay_max = float(self._delay_max_var.get())
            retry = int(self._retry_var.get())
        except ValueError:
            messagebox.showerror("Invalid Settings", "Delay and retry must be numbers.")
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
            attachment_path=self._attachment_path,
            on_status=lambda m: self.after(0, self._log, m, "INFO"),
            on_log=lambda m, l: self.after(0, self._log, m, l),
            on_progress=lambda c, t: self.after(0, self._on_progress, c, t),
            on_contact_result=lambda c, s, e: self.after(0, self._on_contact_result, c, s, e),
            on_complete=lambda cv, tx: self.after(0, self._on_complete, cv, tx),
        )
        self._engine.start()
        self._log("Automation started!", "SUCCESS")

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
            self._log("Paused — click RESUME to continue.", "WARNING")

    def _stop_automation(self):
        if self._engine:
            self._engine.stop()
            self._set_running_state(False)
            self._log("Stop requested. Finishing current task…", "WARNING")

    def _export_report(self):
        from config import REPORTS_DIR
        os.startfile(str(REPORTS_DIR))

    # ═══════════════════════════════════════════════════════════════
    # Engine Callbacks
    # ═══════════════════════════════════════════════════════════════

    def _on_progress(self, current: int, total: int):
        if total > 0:
            self._progress_bar.set(current / total)

    def _on_contact_result(self, contact: dict, status: str, error: str):
        name = contact.get("name", "?")
        phone = contact.get("phone", "?")
        result = f"{name:20} | +{phone:12} | {status}"
        
        self._results_text.configure(state="normal")
        self._results_text._textbox.insert("end", result + "\n")
        self._results_text.configure(state="disabled")
        self._results_text._textbox.see("end")

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

    # ═══════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════

    def _log(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        text = f"[{ts}] {message}"

        self._console_text.configure(state="normal")
        self._console_text._textbox.insert("end", text + "\n")
        self._console_text.configure(state="disabled")
        self._console_text._textbox.see("end")

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
