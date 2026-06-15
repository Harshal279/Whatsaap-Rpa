"""
ui/widgets.py  (v2 — completely reengineered)
----------------------------------------------
Premium, high-contrast, modern widget library for WhatsApp RPA Automator.

Design system:
  • Deep navy background with bright green WhatsApp-inspired accent
  • All labels use text_primary (#F1F5F9) or text_muted (#CBD5E1) — never dim
  • Cards use glowing left-border accent strips
  • Console uses a true terminal-style background with vivid level colours
  • ContactTable rows use alternating row shading for legibility
"""

import customtkinter as ctk
from config import THEME


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _label(parent, text, size=13, weight="normal", color=None, anchor="w", **kw):
    """Quick helper to build a CTkLabel with sane defaults."""
    return ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(family="Segoe UI", size=size, weight=weight),
        text_color=color or THEME["text_primary"],
        anchor=anchor,
        **kw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SectionCard  — glowing-accent card with icon + title header
# ─────────────────────────────────────────────────────────────────────────────

class SectionCard(ctk.CTkFrame):
    """
    Premium card with a thin top accent bar and bold header.
    Pack child widgets directly into this frame.
    """

    def __init__(self, master, title: str, accent_color: str | None = None, **kwargs):
        kwargs.setdefault("fg_color", THEME["surface"])
        kwargs.setdefault("corner_radius", 12)
        super().__init__(master, **kwargs)

        accent = accent_color or THEME["accent"]

        # Top accent bar (3 px)
        ctk.CTkFrame(self, height=3, fg_color=accent, corner_radius=0).pack(
            fill="x", padx=0, pady=(0, 0)
        )

        # Header label
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=THEME["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))

        # Separator
        ctk.CTkFrame(self, height=1, fg_color=THEME["border"]).pack(
            fill="x", padx=14, pady=(0, 8)
        )


# ─────────────────────────────────────────────────────────────────────────────
# StatusPill  — animated pill-shaped status indicator
# ─────────────────────────────────────────────────────────────────────────────

class StatusPill(ctk.CTkFrame):
    """
    A pill-shaped status indicator with coloured dot + label.
    Replaces the old StatusBadge label.
    """

    _CONFIG = {
        "READY":   {"dot": "#60A5FA", "bg": "#1E3A5F", "label": "READY"},
        "RUNNING": {"dot": "#22C55E", "bg": "#14532D", "label": "RUNNING"},
        "PAUSED":  {"dot": "#FBBF24", "bg": "#451A03", "label": "PAUSED"},
        "STOPPED": {"dot": "#94A3B8", "bg": "#1E293B", "label": "STOPPED"},
        "DONE":    {"dot": "#4ADE80", "bg": "#14532D", "label": "DONE"},
        "ERROR":   {"dot": "#F87171", "bg": "#450A0A", "label": "ERROR"},
    }

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "#1E3A5F")
        kwargs.setdefault("corner_radius", 20)
        super().__init__(master, **kwargs)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=14, pady=6)

        self._dot = ctk.CTkLabel(
            inner, text="*",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#60A5FA",
        )
        self._dot.pack(side="left", padx=(0, 6))

        self._lbl = ctk.CTkLabel(
            inner, text="READY",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#F1F5F9",
        )
        self._lbl.pack(side="left")

    def set_status(self, status: str):
        cfg = self._CONFIG.get(status.upper(), self._CONFIG["READY"])
        self.configure(fg_color=cfg["bg"])
        self._dot.configure(text_color=cfg["dot"])
        self._lbl.configure(text=cfg["label"])


# Keep old name as alias so main_window.py can import either
StatusBadge = StatusPill


# ─────────────────────────────────────────────────────────────────────────────
# StatCard  — animated metric card (number + label + accent bar)
# ─────────────────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """A single metric card with a large number, subtitle, and coloured top bar."""

    def __init__(self, master, label: str, value: str = "0",
                 accent: str = "#22C55E", **kwargs):
        kwargs.setdefault("fg_color", THEME["surface"])
        kwargs.setdefault("corner_radius", 14)
        super().__init__(master, **kwargs)

        # Top accent bar
        ctk.CTkFrame(self, height=4, fg_color=accent, corner_radius=2).pack(
            fill="x", padx=0, pady=(0, 0)
        )

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=(8, 12))

        self._val_lbl = ctk.CTkLabel(
            inner,
            text=value,
            font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"),
            text_color=accent,
        )
        self._val_lbl.pack(anchor="w")

        ctk.CTkLabel(
            inner,
            text=label.upper(),
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=THEME["text_muted"],
        ).pack(anchor="w")

    def set_value(self, value: str):
        self._val_lbl.configure(text=value)


# ─────────────────────────────────────────────────────────────────────────────
# ConsoleFrame  — terminal-style log viewer
# ─────────────────────────────────────────────────────────────────────────────

class ConsoleFrame(ctk.CTkFrame):
    """
    Terminal-style scrollable log console with vivid per-level colours.
    Background is near-black (#090D13) for maximum contrast.
    """

    # All colours are WCAG AA compliant against the dark background
    _LEVEL_COLORS = {
        "DEBUG":    "#64748B",   # slate-500 — subtle
        "INFO":     "#E2E8F0",   # slate-200 — crisp white
        "WARNING":  "#FCD34D",   # amber-300 — vivid yellow
        "ERROR":    "#FB7185",   # rose-400  — vivid red-pink
        "CRITICAL": "#FF4444",   # bright red
        "SUCCESS":  "#4ADE80",   # green-400 — vivid green
    }

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "#090D13")
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)

        # Subtle header bar
        hdr = ctk.CTkFrame(self, fg_color="#111827", corner_radius=0, height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="* * *",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#374151",
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            hdr, text="LIVE CONSOLE",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#4B5563",
        ).pack(side="left")

        self._text = ctk.CTkTextbox(
            self,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=16),
            fg_color="#090D13",
            text_color="#E2E8F0",
            border_width=0,
            state="disabled",
        )
        self._text.pack(fill="both", expand=True, padx=0, pady=0)

        for level, color in self._LEVEL_COLORS.items():
            self._text._textbox.tag_configure(level, foreground=color)

        # Prefix tags (bold timestamps)
        self._text._textbox.tag_configure(
            "TS", foreground="#374151",
            font=("Consolas", 14)
        )

    def append(self, message: str, level: str = "INFO"):
        level_key = level.upper() if level.upper() in self._LEVEL_COLORS else "INFO"
        self._text.configure(state="normal")
        self._text._textbox.insert("end", message + "\n", level_key)
        self._text.configure(state="disabled")
        self._text._textbox.see("end")

    def clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
# ContactTable  — high-contrast scrollable results table
# ─────────────────────────────────────────────────────────────────────────────

class ContactTable(ctk.CTkScrollableFrame):
    """
    Alternating-row results table with status pills.
    Columns: #  |  Name  |  Phone  |  Status
    """

    _COL_WIDTHS = [44, 180, 170, 110]
    _HEADERS    = ["#", "Name", "Phone", "Status"]

    # Row background colours (alternating)
    _ROW_BG = ["#111827", "#0F172A"]

    _STATUS_CFG = {
        "SUCCESS": {"fg": "#4ADE80", "bg": "#14532D"},
        "FAILED":  {"fg": "#FB7185", "bg": "#450A0A"},
        "SKIPPED": {"fg": "#FCD34D", "bg": "#451A03"},
    }

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "#0A0F1A")
        kwargs.setdefault("scrollbar_button_color", "#1E293B")
        kwargs.setdefault("scrollbar_fg_color", "#0A0F1A")
        super().__init__(master, **kwargs)

        self._row_count = 0
        self._render_header()

    def _render_header(self):
        hdr_frame = ctk.CTkFrame(self, fg_color="#1E293B", corner_radius=8)
        hdr_frame.grid(
            row=0, column=0, columnspan=len(self._HEADERS),
            sticky="ew", padx=4, pady=(4, 2)
        )
        for col, (header, width) in enumerate(zip(self._HEADERS, self._COL_WIDTHS)):
            ctk.CTkLabel(
                hdr_frame,
                text=header,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color="#94A3B8",
                width=width,
                anchor="w",
            ).grid(row=0, column=col, padx=(10, 4), pady=8, sticky="w")

    def add_row(self, name: str, phone: str, status: str):
        self._row_count += 1
        row_idx = self._row_count
        bg = self._ROW_BG[row_idx % 2]

        status_cfg = self._STATUS_CFG.get(
            status.upper(), {"fg": "#E2E8F0", "bg": "#1E293B"}
        )

        # Row container
        row_frame = ctk.CTkFrame(self, fg_color=bg, corner_radius=6)
        row_frame.grid(
            row=row_idx, column=0, columnspan=len(self._HEADERS),
            sticky="ew", padx=4, pady=1
        )

        # # column
        ctk.CTkLabel(
            row_frame, text=str(row_idx),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#475569", width=self._COL_WIDTHS[0], anchor="w",
        ).grid(row=0, column=0, padx=(10, 4), pady=6, sticky="w")

        # Name
        ctk.CTkLabel(
            row_frame, text=name,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#E2E8F0", width=self._COL_WIDTHS[1], anchor="w",
        ).grid(row=0, column=1, padx=(0, 4), pady=6, sticky="w")

        # Phone
        ctk.CTkLabel(
            row_frame, text=f"+{phone}",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#94A3B8", width=self._COL_WIDTHS[2], anchor="w",
        ).grid(row=0, column=2, padx=(0, 4), pady=6, sticky="w")

        # Status pill
        pill = ctk.CTkFrame(
            row_frame, fg_color=status_cfg["bg"],
            corner_radius=12, width=self._COL_WIDTHS[3], height=26,
        )
        pill.grid(row=0, column=3, padx=(0, 8), pady=6, sticky="w")
        pill.pack_propagate(False)

        ctk.CTkLabel(
            pill, text=status.upper(),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=status_cfg["fg"],
        ).pack(expand=True)

    def clear(self):
        for w in self.winfo_children():
            w.destroy()
        self._row_count = 0
        self._render_header()


# ─────────────────────────────────────────────────────────────────────────────
# LabeledEntry  — input field with floating label above
# ─────────────────────────────────────────────────────────────────────────────

class LabeledEntry(ctk.CTkFrame):
    """An entry widget with a descriptive label above it."""

    def __init__(self, master, label: str, textvariable=None,
                 width=None, placeholder="", **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        ctk.CTkLabel(
            self, text=label,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#94A3B8",
            anchor="w",
        ).pack(fill="x", pady=(0, 3))

        entry_kw = dict(
            fg_color="#111827",
            border_color="#334155",
            border_width=1,
            text_color="#F1F5F9",
            placeholder_text_color="#475569",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            height=38,
            corner_radius=8,
        )
        if textvariable:
            entry_kw["textvariable"] = textvariable
        if placeholder:
            entry_kw["placeholder_text"] = placeholder
        if width:
            entry_kw["width"] = width

        self._entry = ctk.CTkEntry(self, **entry_kw)
        self._entry.pack(fill="x" if not width else None)

    @property
    def entry(self):
        return self._entry
