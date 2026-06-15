"""
core/automation_engine.py
--------------------------
Orchestrates the full messaging workflow:
    load contacts → open browser → wait for login
    → send to first contact (typed / link-pasted)
    → forward to all remaining contacts in random batches of 1-5
      using WhatsApp's native Forward dialog (phone-number search only)
    → fallback clipboard-paste for contacts not found in the forward dialog
    → write report → clean up.

Designed to run entirely in a background thread to keep the UI
responsive. All state is communicated back to the UI via callbacks.
"""

import random
import threading
import time
from datetime import datetime
from typing import Callable, List, Dict, Optional

from selenium.common.exceptions import WebDriverException

from config import (
    DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, DEFAULT_RETRY_COUNT, DEFAULT_RETRY_DELAY,
    SESSION_BATCH_SIZE, SESSION_BREAK_MIN, SESSION_BREAK_MAX, DAILY_MESSAGE_LIMIT,
    WARMUP_MSG_COUNT, WARMUP_DELAY_MIN, WARMUP_DELAY_MAX,
    OCCASIONAL_EVERY_N, OCCASIONAL_DELAY_MIN, OCCASIONAL_DELAY_MAX,
    DEEP_REST_THRESHOLD_MIN, DEEP_REST_THRESHOLD_MAX, DEEP_REST_MIN, DEEP_REST_MAX,
    FORWARD_BATCH_MIN, FORWARD_BATCH_MAX, WHATSAPP_MAX_FORWARD_CONTACTS,
)
from core.browser_manager import BrowserManager
from core.whatsapp_bot import WhatsAppBot
from utils.logger import get_logger
from utils.report_writer import ReportWriter

logger = get_logger(__name__)


class AutomationEngine:
    """
    Full automation lifecycle controller.

    Callbacks (all optional, called from the worker thread):
        on_status(message: str)
            General status update (displayed in the status bar).

        on_log(message: str, level: str)
            Log line for the UI console ("INFO", "ERROR", "WARNING", etc.).

        on_progress(current: int, total: int)
            Progress update for the progress bar.

        on_contact_result(contact: dict, status: str, error: str)
            Called after each contact attempt; status = "SUCCESS" | "FAILED" | "SKIPPED".

        on_complete(report_csv: str, report_txt: str)
            Called when the run finishes (pass or fail).
    """

    def __init__(
        self,
        contacts: List[Dict],
        browser: str,
        delay_min: float = DEFAULT_DELAY_MIN,
        delay_max: float = DEFAULT_DELAY_MAX,
        retry_count: int = DEFAULT_RETRY_COUNT,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        # ── Warm-up ────────────────────────────────────────────────────────────
        warmup_count: int = WARMUP_MSG_COUNT,
        warmup_min: float = WARMUP_DELAY_MIN,
        warmup_max: float = WARMUP_DELAY_MAX,
        # ── Occasional pause ───────────────────────────────────────────────────
        occasional_every_n: int = OCCASIONAL_EVERY_N,
        occasional_min: float = OCCASIONAL_DELAY_MIN,
        occasional_max: float = OCCASIONAL_DELAY_MAX,
        # ── Batch break ────────────────────────────────────────────────────────
        batch_break_min: float = SESSION_BREAK_MIN,
        batch_break_max: float = SESSION_BREAK_MAX,
        # ── Deep rest ──────────────────────────────────────────────────────────
        deep_rest_min: float = DEEP_REST_MIN,
        deep_rest_max: float = DEEP_REST_MAX,
        attachment_path: Optional[str] = None,
        # ── Forward batch ──────────────────────────────────────────────────────
        forward_batch_min: int = FORWARD_BATCH_MIN,
        forward_batch_max: int = FORWARD_BATCH_MAX,
        # ── Send mode ──────────────────────────────────────────────────────────
        mode: str = "known",               # "known" | "unknown"
        # ── Callbacks ──────────────────────────────────────────────────────────
        on_status: Optional[Callable] = None,
        on_log: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        on_contact_result: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ):
        self.contacts = contacts
        self.browser = browser
        self.mode = mode            # "known" | "unknown"
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.warmup_count = warmup_count
        self.warmup_min = warmup_min
        self.warmup_max = warmup_max
        self.occasional_every_n = occasional_every_n
        self.occasional_min = occasional_min
        self.occasional_max = occasional_max
        self.batch_break_min = batch_break_min
        self.batch_break_max = batch_break_max
        self.deep_rest_min = deep_rest_min
        self.deep_rest_max = deep_rest_max
        self.forward_batch_min = forward_batch_min
        self.forward_batch_max = forward_batch_max
        self.attachment_path = attachment_path

        # Callbacks
        self._on_status = on_status or (lambda m: None)
        self._on_log = on_log or (lambda m, l: None)
        self._on_progress = on_progress or (lambda c, t: None)
        self._on_contact_result = on_contact_result or (lambda c, s, e: None)
        self._on_complete = on_complete or (lambda csv, txt: None)

        # Control flags
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()          # not paused by default

        self._worker_thread: Optional[threading.Thread] = None
        self._browser_manager: Optional[BrowserManager] = None
        self._bot: Optional[WhatsAppBot] = None
        self._report: Optional[ReportWriter] = None

        # Counters
        self.total = len(contacts)
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self._typed_count = 0
        self._forwarded_count = 0
        self._fallback_count = 0
        self._newchat_count = 0     # NEW_CHAT_PASTE sends (unknown mode)

        # ── Session-level forward mode flags ────────────────────────────────────────
        # True  → use WhatsApp forward dialog for remaining contacts
        # False → disabled this session; use paste for every remaining contact
        self._use_forward: bool = True
        # Set to True when first message was sent by paste (forward needs typed anchor)
        self._fallback_mode: bool = False
        # Consecutive all-FAILED forward batches before disabling forward
        self._forward_fail_streak: int = 0
        self._FORWARD_FAIL_STREAK_MAX: int = 2

    # ── Public control API ──────────────────────────────────────────────────────

    def start(self):
        """Spawn the background worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Automation is already running.")
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run, name="AutomationWorker", daemon=True
        )
        self._worker_thread.start()

    def stop(self):
        """Signal the worker to stop after the current message."""
        logger.info("Stop requested by user.")
        self._stop_event.set()
        self._pause_event.set()

    def pause(self):
        """Pause after the next message is sent."""
        logger.info("Pause requested.")
        self._pause_event.clear()

    def resume(self):
        """Resume from a paused state."""
        logger.info("Resuming automation.")
        self._pause_event.set()

    @property
    def is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    # ── Worker ──────────────────────────────────────────────────────────────────

    def _run(self):
        """Main worker body — runs in the background thread."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._report = ReportWriter(session_id)

        try:
            self._setup_browser()
            if self._stop_event.is_set():
                return

            if not self._login():
                self._on_status("Login failed or timed out.")
                return

            self._send_all_messages()

        except Exception as e:
            logger.exception("Fatal error in automation engine: %s", e)
            self._on_log(f"FATAL ERROR: {e}", "ERROR")
            self._on_status("Automation crashed — see logs.")
        finally:
            self._teardown()

    def _setup_browser(self):
        """Initialise browser and create the bot."""
        self._on_status(f"Starting {self.browser}…")
        self._on_log(f"Launching {self.browser} browser…", "INFO")

        self._browser_manager = BrowserManager(browser=self.browser)
        driver = self._browser_manager.create_driver()
        self._bot = WhatsAppBot(driver, progress_callback=self._on_status)

        self._bot.open_whatsapp()

    def _login(self) -> bool:
        """Wait for WhatsApp login; returns True on success."""
        if self._bot.is_logged_in():
            self._on_log("Already logged in via saved browser profile.", "INFO")
            self._on_status("Already logged in ✓")
            return True

        self._on_status("Please scan the QR code in the browser…")
        self._on_log("Waiting for QR code scan…", "INFO")
        return self._bot.wait_for_login()

    # ── Core messaging orchestrator ────────────────────────────────────────────

    def _send_all_messages(self):
        """
        Entry point dispatched by _run().
        Routes to the correct send strategy based on self.mode.
        """
        mode_label = "[KNOWN/FORWARD]" if self.mode == "known" else "[UNKNOWN/NEWCHAT]"
        self._on_log(f"{mode_label} Starting send — {self.total} contacts.", "INFO")

        if self.mode == "unknown":
            self._send_unknown_mode()
        else:
            self._send_known_mode()

    # ── Mode A: Known Contacts (forward-based) ─────────────────────────────────

    def _send_known_mode(self):
        """
        Known-contacts messaging workflow:

        1. Send the first contact's message by typing (or pasting URLs inline).
        2. For all remaining contacts, use WhatsApp's Forward dialog:
           - Right-click the last sent message → Forward.
           - Search each phone number in the dialog, tick it.
           - Send in random batches of FORWARD_BATCH_MIN–FORWARD_BATCH_MAX.
        3. For contacts not found in the forward dialog, fall back to
           clipboard-pasting the same message into their individual chat.
        4. Track and log every send with method tag (TYPED / FORWARDED / FALLBACK_PASTE).
        5. Prevent duplicate sends via sent_set.
        """
        if not self.contacts:
            self._on_log("No contacts to process.", "WARNING")
            return

        total = self.total
        sent_set: set = set()

        # Dedup check — warn if duplicates exist in the Excel file
        seen_phones: set = set()
        for c in self.contacts:
            if c["phone"] in seen_phones:
                self._on_log(
                    f"  [SKIP/DUP] Duplicate phone +{c['phone']} in Excel — will be skipped.",
                    "WARNING",
                )
            seen_phones.add(c["phone"])

        # ── Daily / session limit safeguard ───────────────────────────────────
        if DAILY_MESSAGE_LIMIT > 0 and total > DAILY_MESSAGE_LIMIT:
            self._on_log(
                f"[DAILY LIMIT] Capping run at {DAILY_MESSAGE_LIMIT} contacts.",
                "WARNING",
            )

        # ── Step 1: First contact — type / inline-link-paste ──────────────────
        first = self.contacts[0]
        message = first["message"]   # read message ONCE from Excel data

        self._pause_event.wait()
        if self._stop_event.is_set():
            return

        self._on_status(f"Sending first message to {first['name']} (1/{total})…")
        self._on_log(f"[1/{total}] First send (typed) to {first['name']} (+{first['phone']})", "INFO")
        self._on_progress(1, total)

        if self.attachment_path:
            ok = self._attempt_send_file(first["phone"], message, first["name"])
        else:
            ok = self._attempt_send_typed(first["phone"], message, first["name"])

        if ok:
            sent_set.add(first["phone"])
            self.success_count += 1
            self._typed_count += 1
            self._on_contact_result(first, "SUCCESS", "")
            self._report.write_record(
                first["name"], first["phone"], message, "SUCCESS",
                method="TYPED",
            )
            self._on_log(f"  ✓ Sent (TYPED) to {first['name']}", "INFO")
        else:
            # ── Paste fallback for first contact ────────────────────────────────
            self._on_log(
                f"  [WARN] Typed send failed for {first['name']} — trying paste fallback.",
                "WARNING",
            )
            ok = self._attempt_send_paste(first["phone"], message, first["name"])
            if ok:
                sent_set.add(first["phone"])
                self.success_count += 1
                self._fallback_count += 1
                self._on_contact_result(first, "SUCCESS", "")
                self._report.write_record(
                    first["name"], first["phone"], message, "SUCCESS",
                    method="TYPED_PASTE_FALLBACK",
                )
                self._on_log(
                    f"  ✓ Sent (PASTE fallback) to {first['name']}. "
                    "Forward may not work — switching to paste-only mode.",
                    "WARNING",
                )
                # Forward requires a "typed" anchor message — disable for this session
                self._use_forward = False
                self._fallback_mode = True
                self._on_log(
                    "[MODE] Typed anchor unavailable — paste-only mode for remaining contacts.",
                    "WARNING",
                )
            else:
                self.failed_count += 1
                self._on_contact_result(first, "FAILED", "First send failed (typed + paste)")
                self._report.write_record(
                    first["name"], first["phone"], message, "FAILED",
                    error="First send failed (typed + paste)", method="TYPED",
                )
                self._on_log(f"  ✗ Failed first send to {first['name']} (both typed and paste)", "ERROR")

        # ── Step 2: Remaining contacts via forward batches ────────────────────
        # Deep-rest threshold
        next_batch_break = random.randint(15, 25)
        deep_rest_threshold = random.randint(
            DEEP_REST_THRESHOLD_MIN, DEEP_REST_THRESHOLD_MAX
        )
        deep_rest_done = False
        processed_count = 1   # first contact already done

        # Build de-duplicated remaining list (skip already-sent + Excel dupes)
        remaining: List[Dict] = []
        _seen_for_remaining: set = set(sent_set)
        for c in self.contacts[1:]:
            if c["phone"] not in _seen_for_remaining:
                remaining.append(c)
                _seen_for_remaining.add(c["phone"])
            else:
                # Duplicate — skip immediately
                self.skipped_count += 1
                self._on_contact_result(c, "SKIPPED", "Duplicate phone")
                self._report.write_record(
                    c["name"], c["phone"], message, "SKIPPED",
                    error="Duplicate phone number", method="SKIPPED",
                )
                self._on_log(
                    f"  [SKIP] Duplicate +{c['phone']} ({c['name']}) — skipped.", "WARNING"
                )

        while remaining and not self._stop_event.is_set():
            # ── Daily limit ───────────────────────────────────────────────────
            if DAILY_MESSAGE_LIMIT > 0 and processed_count >= DAILY_MESSAGE_LIMIT:
                self._on_log(
                    f"[DAILY LIMIT] {DAILY_MESSAGE_LIMIT} messages reached.", "WARNING"
                )
                self._on_status("Daily limit reached — session ended for today.")
                break

            # ── Browser health check ──────────────────────────────────────────
            if not self._is_browser_alive():
                self._on_log("[FATAL] Browser session died — stopping.", "ERROR")
                self._on_status("Browser crashed — automation stopped.")
                break

            # ── Block detection ───────────────────────────────────────────────
            block_reason = self._bot.detect_whatsapp_block()
            if block_reason:
                self._on_log(
                    f"[BLOCK] WhatsApp block detected: {block_reason}. Pausing…", "ERROR"
                )
                self._on_status(f"⛔ Blocked: {block_reason} — click RESUME to continue.")
                self.pause()              # clears _pause_event
                self._pause_event.wait()  # waits until user resumes
                if self._stop_event.is_set():
                    break
                # Cool-down after resuming from a block
                cool_down = random.uniform(60, 180)
                self._on_log(
                    f"  [Block cool-down] Waiting {cool_down:.0f}s after resume…", "WARNING"
                )
                self._interruptible_sleep(cool_down)

            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            # Hard-clamp batch size to WhatsApp's forward limit
            effective_batch_max = min(self.forward_batch_max, WHATSAPP_MAX_FORWARD_CONTACTS)
            batch_size = random.randint(self.forward_batch_min, effective_batch_max)
            batch = remaining[:batch_size]
            batch_phones = [c["phone"] for c in batch]
            batch_names = {c["phone"]: c["name"] for c in batch}

            # ── Anti-detection: ~10% chance to use paste even if forward is on ──
            # Real users occasionally navigate directly to a chat instead of forwarding.
            use_paste_this_batch = self._use_forward and random.random() < 0.10

            if use_paste_this_batch:
                self._on_status(
                    f"Paste-sending to {len(batch)} contact(s) "
                    f"({processed_count + 1}–{processed_count + len(batch)}/{total})…"
                )
                self._on_log(
                    f"  [PASTE-RANDOM] Human-variation paste to batch of {len(batch)}: "
                    + ", ".join(f"+{p}" for p in batch_phones),
                    "INFO",
                )
            else:
                self._on_status(
                    f"Forwarding to {len(batch)} contact(s) "
                    f"({processed_count + 1}–{processed_count + len(batch)}/{total})…"
                )
                self._on_log(
                    f"  [FORWARD] Batch of {len(batch)}: "
                    + ", ".join(f"+{p}" for p in batch_phones),
                    "INFO",
                )

            # ── Return to first chat before opening forward dialog ─────────────
            # Fallback sends (from the previous batch) navigate to other chats.
            # We must be back on the first contact's chat so the right-click
            # lands on that sent message bubble.
            if processed_count > 1:   # skip on very first batch (already there)
                self._on_log("  [NAV] Returning to first chat for forward…", "INFO")
                if not self._bot.return_to_first_chat():
                    self._on_log(
                        "  [WARN] Could not return to first chat — skipping batch.", "WARNING"
                    )
                    # Mark batch as fallback and continue
                    for c in batch:
                        fallback_contacts_pre = batch  # handle below
                    remaining = [c for c in remaining if c["phone"] not in sent_set]
                    continue

            # ── Attempt the forward action (or skip if in paste-only mode) ────
            if not self._use_forward:
                # paste-only mode: treat entire batch as fallback
                forward_results = {p: "FALLBACK_NEEDED" for p in batch_phones}
                self._on_log(
                    "  [MODE] Paste-only mode — skipping forward dialog.", "WARNING"
                )
            else:
                forward_results = self._attempt_forward_batch(batch_phones, message)

                # ── Graceful degradation: disable forward after repeated failures ──
                all_failed = all(
                    v == "FAILED" for v in forward_results.values()
                )

                if all_failed:
                    self._forward_fail_streak += 1
                    if self._forward_fail_streak >= self._FORWARD_FAIL_STREAK_MAX:
                        self._use_forward = False
                        self._on_log(
                            f"[MODE] Forward flow failed {self._FORWARD_FAIL_STREAK_MAX} batches "
                            "in a row — switching to paste-only mode for this session.",
                            "WARNING",
                        )
                        self._on_status("Forward disabled — using paste mode for remaining contacts.")
                else:
                    self._forward_fail_streak = 0   # reset streak on any success

            fallback_contacts: List[Dict] = []
            for c in batch:
                phone = c["phone"]
                result = forward_results.get(phone, "FAILED")
                processed_count += 1
                self._on_progress(processed_count, total)

                if result == "FORWARDED":
                    sent_set.add(phone)
                    self.success_count += 1
                    self._forwarded_count += 1
                    self._on_contact_result(c, "SUCCESS", "")
                    self._report.write_record(
                        c["name"], phone, message, "SUCCESS", method="FORWARDED"
                    )
                    self._on_log(f"  ✓ Forwarded to {c['name']} (+{phone})", "INFO")

                elif result == "FALLBACK_NEEDED":
                    fallback_contacts.append(c)

                else:  # "FAILED"
                    self.failed_count += 1
                    self._on_contact_result(c, "FAILED", "Forward failed")
                    self._report.write_record(
                        c["name"], phone, message, "FAILED",
                        error="Forward failed", method="FORWARDED",
                    )
                    self._on_log(f"  ✗ Forward failed for {c['name']} (+{phone})", "ERROR")

            # ── Fallback: clipboard-paste for contacts not in forward list ─────
            if fallback_contacts:
                # Return to first chat first (forward dialog may have left us elsewhere)
                # then for each fallback, open their chat → paste → come back
                for c in fallback_contacts:
                    phone = c["phone"]
                    self._on_status(f"Fallback paste-send to {c['name']} (+{phone})…")
                    self._on_log(
                        f"  [FALLBACK] Not in forward list — paste-send to {c['name']} (+{phone})",
                        "WARNING",
                    )

                    ok = self._attempt_send_paste(phone, message, c["name"])
                    if ok:
                        sent_set.add(phone)
                        self.success_count += 1
                        self._fallback_count += 1
                        self._on_contact_result(c, "SUCCESS", "")
                        self._report.write_record(
                            c["name"], phone, message, "SUCCESS", method="FALLBACK_PASTE"
                        )
                        self._on_log(f"  ✓ Fallback paste-sent to {c['name']}", "INFO")
                    else:
                        self.failed_count += 1
                        self._on_contact_result(c, "FAILED", "Fallback paste failed")
                        self._report.write_record(
                            c["name"], phone, message, "FAILED",
                            error="Fallback paste failed", method="FALLBACK_PASTE",
                        )
                        self._on_log(f"  ✗ Fallback failed for {c['name']} (+{phone})", "ERROR")

            # Update remaining (remove sent)
            remaining = [c for c in remaining if c["phone"] not in sent_set]

            if not remaining or self._stop_event.is_set():
                break

            # ── Deep rest ──────────────────────────────────────────────────────
            if not deep_rest_done and processed_count >= deep_rest_threshold:
                deep_rest_done = True
                if processed_count > 45 and random.random() < 0.2:
                    self._on_log("  [Session End] Simulating natural end of day…", "WARNING")
                    self._on_status("Session organically ended for safety.")
                    break
                deep_rest = random.uniform(self.deep_rest_min, self.deep_rest_max)
                self._on_log(
                    f"  [Deep rest] {deep_rest / 60:.0f}-min break after {processed_count} messages.",
                    "INFO",
                )
                self._on_status(f"Deep rest — resuming in ~{deep_rest / 60:.0f} min…")
                self._interruptible_sleep(deep_rest)

            # ── Batch long-break ───────────────────────────────────────────────
            elif processed_count >= next_batch_break:
                next_batch_break = processed_count + random.randint(15, 25)
                long_break = random.uniform(self.batch_break_min, self.batch_break_max)
                self._on_log(
                    f"  [Batch break] Resting {long_break / 60:.1f} min…", "INFO"
                )
                self._interruptible_sleep(long_break)

            # ── Per-batch anti-spam delay ──────────────────────────────────────
            else:
                if processed_count <= self.warmup_count:
                    delay = random.uniform(self.warmup_min, self.warmup_max)
                    self._on_log(f"  [Warm-up] Waiting {delay:.1f}s…", "INFO")
                elif processed_count % self.occasional_every_n == 0:
                    delay = random.uniform(self.occasional_min, self.occasional_max)
                    self._on_log(f"  [Occasional pause] Waiting {delay:.1f}s…", "INFO")
                else:
                    delay = random.uniform(self.delay_min, self.delay_max)
                    self._on_log(f"  Waiting {delay:.1f}s…", "INFO")
                self._interruptible_sleep(delay)

        # ── Final summary ──────────────────────────────────────────────────────
        self._report.write_summary(
            total, self.success_count, self.failed_count, self.skipped_count,
            typed=self._typed_count,
            forwarded=self._forwarded_count,
            fallback=self._fallback_count,
            mode="known",
        )
        self._on_progress(total, total)
        self._on_status(
            f"[KNOWN] Done — {self.success_count} sent "
            f"({self._typed_count} typed, {self._forwarded_count} forwarded, "
            f"{self._fallback_count} paste-fallback), "
            f"{self.failed_count} failed."
        )
        self._on_log(f"[KNOWN/FORWARD] Run complete: {self.success_count}/{total} sent.", "INFO")
        self._on_complete(self._report.csv_file, self._report.txt_file)

    # ── Mode B: Unknown Contacts (new-chat + paste) ────────────────────────────

    def _send_unknown_mode(self):
        """
        Unknown-contacts messaging workflow:

        For EVERY contact:
          1. Click New Chat (via _search_and_open_chat).
          2. Search / open by phone number.
          3. Clipboard-paste the full message (or attach file).
          4. Send.

        No forward dialog is used at all.
        All anti-ban delays (warmup, occasional, batch break, deep rest) still apply.
        Method tag in report: NEW_CHAT_PASTE.
        """
        if not self.contacts:
            self._on_log("[UNKNOWN] No contacts to process.", "WARNING")
            return

        total = self.total
        sent_set: set = set()

        # Dedup warning
        seen_phones: set = set()
        for c in self.contacts:
            if c["phone"] in seen_phones:
                self._on_log(
                    f"  [SKIP/DUP] Duplicate phone +{c['phone']} in Excel — will be skipped.",
                    "WARNING",
                )
            seen_phones.add(c["phone"])

        if DAILY_MESSAGE_LIMIT > 0 and total > DAILY_MESSAGE_LIMIT:
            self._on_log(
                f"[DAILY LIMIT] Capping run at {DAILY_MESSAGE_LIMIT} contacts.", "WARNING"
            )

        # Build deduplicated list
        contacts_deduped: List[Dict] = []
        _seen: set = set()
        for c in self.contacts:
            if c["phone"] not in _seen:
                contacts_deduped.append(c)
                _seen.add(c["phone"])
            else:
                self.skipped_count += 1
                self._on_contact_result(c, "SKIPPED", "Duplicate phone")
                self._report.write_record(
                    c["name"], c["phone"], c["message"], "SKIPPED",
                    error="Duplicate phone number", method="SKIPPED",
                )
                self._on_log(
                    f"  [SKIP] Duplicate +{c['phone']} ({c['name']}) — skipped.", "WARNING"
                )

        # ── Anti-ban thresholds ────────────────────────────────────────────────
        next_batch_break = random.randint(15, 25)
        deep_rest_threshold = random.randint(
            DEEP_REST_THRESHOLD_MIN, DEEP_REST_THRESHOLD_MAX
        )
        deep_rest_done = False
        processed_count = 0

        for idx, contact in enumerate(contacts_deduped):
            if self._stop_event.is_set():
                break

            # Daily limit
            if DAILY_MESSAGE_LIMIT > 0 and processed_count >= DAILY_MESSAGE_LIMIT:
                self._on_log(
                    f"[DAILY LIMIT] {DAILY_MESSAGE_LIMIT} messages reached.", "WARNING"
                )
                self._on_status("Daily limit reached — session ended for today.")
                break

            # Browser health
            if not self._is_browser_alive():
                self._on_log("[FATAL] Browser session died — stopping.", "ERROR")
                self._on_status("Browser crashed — automation stopped.")
                break

            # Block detection
            block_reason = self._bot.detect_whatsapp_block()
            if block_reason:
                self._on_log(
                    f"[BLOCK] WhatsApp block detected: {block_reason}. Pausing…", "ERROR"
                )
                self._on_status(f"⛔ Blocked: {block_reason} — click RESUME to continue.")
                self.pause()
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break
                cool_down = random.uniform(60, 180)
                self._on_log(
                    f"  [Block cool-down] Waiting {cool_down:.0f}s after resume…", "WARNING"
                )
                self._interruptible_sleep(cool_down)

            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            phone   = contact["phone"]
            name    = contact["name"]
            message = contact["message"]
            processed_count += 1
            self._on_progress(processed_count, total)
            self._on_status(
                f"[UNKNOWN] Sending to {name} ({processed_count}/{total})…"
            )
            self._on_log(
                f"  [{processed_count}/{total}] [UNKNOWN/NEWCHAT] → {name} (+{phone})", "INFO"
            )

            if self.attachment_path:
                ok = self._attempt_send_file_via_new_chat(
                    phone, message, name
                )
                method_tag = "NEW_CHAT_FILE"
            else:
                ok = self._attempt_send_via_new_chat(phone, message, name)
                method_tag = "NEW_CHAT_PASTE"

            if ok:
                sent_set.add(phone)
                self.success_count += 1
                self._newchat_count += 1
                self._on_contact_result(contact, "SUCCESS", "")
                self._report.write_record(
                    name, phone, message, "SUCCESS", method=method_tag
                )
                self._on_log(f"  ✓ [{method_tag}] Sent to {name}", "INFO")
            else:
                self.failed_count += 1
                self._on_contact_result(contact, "FAILED", "NewChat send failed")
                self._report.write_record(
                    name, phone, message, "FAILED",
                    error="NewChat send failed", method=method_tag,
                )
                self._on_log(f"  ✗ [{method_tag}] Failed for {name} (+{phone})", "ERROR")

            if self._stop_event.is_set():
                break

            # ── Anti-ban delays ────────────────────────────────────────────────
            if not deep_rest_done and processed_count >= deep_rest_threshold:
                deep_rest_done = True
                if processed_count > 45 and random.random() < 0.2:
                    self._on_log(
                        "  [Session End] Simulating natural end of day…", "WARNING"
                    )
                    self._on_status("Session organically ended for safety.")
                    break
                deep_rest = random.uniform(self.deep_rest_min, self.deep_rest_max)
                self._on_log(
                    f"  [Deep rest] {deep_rest / 60:.0f}-min break after {processed_count} messages.",
                    "INFO",
                )
                self._on_status(f"Deep rest — resuming in ~{deep_rest / 60:.0f} min…")
                self._interruptible_sleep(deep_rest)

            elif processed_count >= next_batch_break:
                next_batch_break = processed_count + random.randint(15, 25)
                long_break = random.uniform(self.batch_break_min, self.batch_break_max)
                self._on_log(
                    f"  [Batch break] Resting {long_break / 60:.1f} min…", "INFO"
                )
                self._interruptible_sleep(long_break)

            else:
                if processed_count <= self.warmup_count:
                    delay = random.uniform(self.warmup_min, self.warmup_max)
                    self._on_log(f"  [Warm-up] Waiting {delay:.1f}s…", "INFO")
                elif processed_count % self.occasional_every_n == 0:
                    delay = random.uniform(self.occasional_min, self.occasional_max)
                    self._on_log(f"  [Occasional pause] Waiting {delay:.1f}s…", "INFO")
                else:
                    delay = random.uniform(self.delay_min, self.delay_max)
                    self._on_log(f"  Waiting {delay:.1f}s…", "INFO")
                self._interruptible_sleep(delay)

        # ── Final summary ──────────────────────────────────────────────────────
        self._report.write_summary(
            total, self.success_count, self.failed_count, self.skipped_count,
            new_chat=self._newchat_count,
            mode="unknown",
        )
        self._on_progress(total, total)
        self._on_status(
            f"[UNKNOWN] Done — {self.success_count} sent "
            f"({self._newchat_count} via New Chat), "
            f"{self.failed_count} failed."
        )
        self._on_log(
            f"[UNKNOWN/NEWCHAT] Run complete: {self.success_count}/{total} sent.", "INFO"
        )
        self._on_complete(self._report.csv_file, self._report.txt_file)

    # ── Attempt helpers ────────────────────────────────────────────────────────

    def _is_browser_alive(self) -> bool:
        """
        Quick check: return True if the WebDriver session is still alive.
        An 'invalid session id' means Chrome has crashed or been closed;
        retrying in that state only spams identical errors.
        """
        try:
            _ = self._bot.driver.current_url
            return True
        except Exception:
            return False

    def _attempt_send_typed(self, phone: str, message: str, name: str = "") -> bool:
        """
        Send message to *phone* by typing / inline-pasting URLs.
        Retries up to self.retry_count times. Aborts immediately if browser dies.
        """
        attempts = self.retry_count + 1
        for attempt in range(1, attempts + 1):
            if not self._is_browser_alive():
                logger.error("Browser session dead — aborting send for +%s", phone)
                return False
            try:
                ok = self._bot.send_message(phone, message, name=name)
                if ok:
                    return True
                logger.warning("send_message returned False for +%s (attempt %d)", phone, attempt)
            except Exception as e:
                logger.warning("Attempt %d/%d failed for +%s: %s", attempt, attempts, phone, e)
            if attempt < attempts:
                self._on_log(f"  Retrying {name} (attempt {attempt + 1}/{attempts})…", "WARNING")
                self._interruptible_sleep(self.retry_delay)
        return False

    def _attempt_send_paste(self, phone: str, message: str, name: str = "") -> bool:
        """
        Send message to *phone* via clipboard paste only.
        Retries up to self.retry_count times. Aborts immediately if browser dies.
        """
        attempts = self.retry_count + 1
        for attempt in range(1, attempts + 1):
            if not self._is_browser_alive():
                logger.error("Browser session dead — aborting paste-send for +%s", phone)
                return False
            try:
                ok = self._bot.send_message_paste(phone, message, name=name)
                if ok:
                    return True
                logger.warning("send_message_paste returned False for +%s (attempt %d)", phone, attempt)
            except Exception as e:
                logger.warning("Paste attempt %d/%d failed for +%s: %s", attempt, attempts, phone, e)
            if attempt < attempts:
                self._on_log(f"  Retrying fallback paste for {name} (attempt {attempt + 1}/{attempts})…", "WARNING")
                self._interruptible_sleep(self.retry_delay)
        return False

    def _attempt_send_file(self, phone: str, message: str, name: str = "") -> bool:
        """Send an attachment to *phone*. Retries up to self.retry_count times."""
        attempts = self.retry_count + 1
        for attempt in range(1, attempts + 1):
            if not self._is_browser_alive():
                logger.error("Browser session dead — aborting file send for +%s", phone)
                return False
            try:
                ok = self._bot.send_file(phone, message, self.attachment_path, name=name)
                if ok:
                    return True
            except Exception as e:
                logger.warning("File attempt %d/%d failed for +%s: %s", attempt, attempts, phone, e)
            if attempt < attempts:
                self._interruptible_sleep(self.retry_delay)
        return False

    def _attempt_send_via_new_chat(self, phone: str, message: str, name: str = "") -> bool:
        """
        Send via New Chat + clipboard paste, with retry on failure.
        Used exclusively in Unknown-contacts mode.
        """
        attempts = self.retry_count + 1
        for attempt in range(1, attempts + 1):
            if not self._is_browser_alive():
                logger.error("[UNKNOWN] Browser dead — aborting NewChat send for +%s", phone)
                return False
            try:
                ok = self._bot.send_via_new_chat(phone, message, name=name)
                if ok:
                    return True
                logger.warning("[UNKNOWN] send_via_new_chat returned False for +%s (attempt %d)", phone, attempt)
            except Exception as e:
                logger.warning("[UNKNOWN] NewChat attempt %d/%d failed for +%s: %s", attempt, attempts, phone, e)
            if attempt < attempts:
                self._on_log(
                    f"  [UNKNOWN] Retrying {name} (attempt {attempt + 1}/{attempts})…", "WARNING"
                )
                self._interruptible_sleep(self.retry_delay)
        return False

    def _attempt_send_file_via_new_chat(self, phone: str, message: str, name: str = "") -> bool:
        """
        Send a file via New Chat, with retry on failure.
        Used in Unknown-contacts mode when an attachment_path is set.
        """
        attempts = self.retry_count + 1
        for attempt in range(1, attempts + 1):
            if not self._is_browser_alive():
                logger.error("[UNKNOWN] Browser dead — aborting NewChat file send for +%s", phone)
                return False
            try:
                ok = self._bot.send_file_via_new_chat(
                    phone, message, self.attachment_path, name=name
                )
                if ok:
                    return True
                logger.warning("[UNKNOWN] send_file_via_new_chat returned False for +%s (attempt %d)", phone, attempt)
            except Exception as e:
                logger.warning("[UNKNOWN] NewChat file attempt %d/%d failed for +%s: %s", attempt, attempts, phone, e)
            if attempt < attempts:
                self._interruptible_sleep(self.retry_delay)
        return False

    def _attempt_forward_batch(self, phones: List[str], message: str) -> Dict[str, str]:
        """
        Try to forward the last sent message to *phones* via the Forward dialog.
        Retries the entire batch once on total failure.

        Returns:
            Dict mapping phone → "FORWARDED" | "FALLBACK_NEEDED" | "FAILED"
        """
        for attempt in range(1, self.retry_count + 2):
            try:
                results = self._bot.forward_message_to_contacts(phones)
                # If at least one was forwarded or fell back, treat as a usable result
                if any(v in ("FORWARDED", "FALLBACK_NEEDED") for v in results.values()):
                    return results
                logger.warning("Forward batch returned all FAILED (attempt %d)", attempt)
            except Exception as e:
                logger.warning("Forward batch error (attempt %d): %s", attempt, e)
            if attempt < self.retry_count + 2:
                self._interruptible_sleep(self.retry_delay)
        # All retries exhausted — mark everything as fallback
        return {p: "FALLBACK_NEEDED" for p in phones}

    # ── Utility ────────────────────────────────────────────────────────────────

    def _interruptible_sleep(self, seconds: float):
        """Sleep in small increments so stop/pause events are respected."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._stop_event.is_set():
                return
            self._pause_event.wait(timeout=0.25)
            time.sleep(0.1)

    def _teardown(self):
        """Clean up browser resources."""
        if self._browser_manager:
            self._browser_manager.quit()
