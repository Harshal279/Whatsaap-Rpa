"""
core/whatsapp_bot.py
--------------------
Core automation engine for WhatsApp Web messaging.

Responsibilities:
- Navigate to WhatsApp Web and wait for QR scan.
- Open a specific chat via phone number search.
- Type and send a message.
  * Plain text is typed character-by-character (human-like).
  * URL segments are clipboard-pasted so links are sent exactly.
- Forward the last sent message using WhatsApp's native Forward flow:
    Step 1: Hover over the message bubble -> click the dropdown chevron
    Step 2: Click "Forward" in the context menu
    Step 3: Click the ">>" button in the "1 selected" selection-mode bar
    Step 4: In the "Forward message to" dialog:
            search each phone number, tick the result, repeat, then click Send
- Handle image/document attachments.
- Detect WhatsApp block/rate-limit banners and signal the caller.

All XPath selectors are sourced from core.selectors (single source of truth).
"""

import os
import re
import time
import random
from pathlib import Path
from typing import Optional, Callable, Dict, List

import pyperclip

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
)

from config import (
    WHATSAPP_WEB_URL,
    QR_WAIT_TIMEOUT,
    MESSAGE_SEND_TIMEOUT,
    FORWARD_SEARCH_WAIT,
    FORWARD_DIALOG_TIMEOUT,
    WHATSAPP_MAX_FORWARD_CONTACTS,
)
from core.selectors import Selectors, SelectorHelper
from core.exceptions import BlockedError, ChatNotFoundError, ForwardFlowError
from utils.logger import get_logger, log_exception

logger = get_logger(__name__)

# Regex to detect URLs inside messages
_URL_RE = re.compile(r'(https?://\S+|www\.\S+)', re.IGNORECASE)


class WhatsAppBot:
    """
    High-level WhatsApp Web automation bot.

    All public methods are intentionally kept synchronous so they can be
    called from a background thread managed by the UI layer.
    """

    def __init__(self, driver, progress_callback: Optional[Callable] = None):
        """
        Args:
            driver:            A live Selenium WebDriver instance.
            progress_callback: Optional callable(step: str) for UI updates.
        """
        self.driver = driver
        self._progress = progress_callback or (lambda s: None)
        # Phone of the first contact — the "anchor" chat kept open for forwarding
        self._first_chat_phone: str = ""

    # ── Public ─────────────────────────────────────────────────────────────────

    def open_whatsapp(self):
        """Navigate to WhatsApp Web."""
        logger.info("Opening WhatsApp Web…")
        self._progress("Opening WhatsApp Web…")
        self.driver.get(WHATSAPP_WEB_URL)

    def wait_for_login(self) -> bool:
        """Block until QR scan or already logged in. Returns True on success."""
        self._progress("Waiting for QR code scan…")
        logger.info("Waiting up to %d seconds for WhatsApp login…", QR_WAIT_TIMEOUT)
        try:
            WebDriverWait(self.driver, QR_WAIT_TIMEOUT).until(
                EC.presence_of_element_located(
                    (By.XPATH, SelectorHelper.joined(Selectors.LOGGED_IN))
                )
            )
            logger.info("WhatsApp login confirmed.")
            self._progress("WhatsApp logged in ✓")
            return True
        except TimeoutException:
            logger.error("QR code scan timed out after %d seconds.", QR_WAIT_TIMEOUT)
            return False

    def is_logged_in(self) -> bool:
        """Quick non-blocking check whether WhatsApp is already logged in."""
        try:
            self.driver.find_element(
                By.XPATH, SelectorHelper.joined(Selectors.LOGGED_IN)
            )
            return True
        except NoSuchElementException:
            return False

    def detect_whatsapp_block(self) -> Optional[str]:
        """
        Check if WhatsApp is showing a block / error banner.

        Returns a human-readable reason string if a block is detected,
        or None if the session is clear.
        """
        checks = [
            (Selectors.MSG_NOT_SENT_BANNER, "Message not sent"),
            (Selectors.TRYING_TO_CONNECT,   "Trying to connect"),
            (Selectors.RATE_LIMIT_BANNER,    "Rate limited / temporarily blocked"),
        ]
        for selector_list, reason in checks:
            for xpath in selector_list:
                try:
                    els = self.driver.find_elements(By.XPATH, xpath)
                    if any(e.is_displayed() for e in els):
                        logger.warning("Block banner detected: %s (xpath=%s)", reason, xpath)
                        return reason
                except Exception:
                    pass
        return None

    def send_message(self, phone: str, message: str, name: str = "") -> bool:
        """
        Open the chat for *phone* and send *message*.

        Plain text is typed character-by-character. URL segments inside the
        message are clipboard-pasted so the link is transmitted exactly.

        After the first successful send, this chat is remembered as the
        'anchor' chat for subsequent forward actions.

        Returns True on success, False on failure.
        """
        logger.debug("Opening chat for +%s", phone)
        if not self._search_and_open_chat(phone, name):
            logger.error("Failed to open chat for +%s", phone)
            return False

        try:
            self._human_random_actions()
            chat_box = self._wait_for_chat_box()
            if chat_box is None:
                raise TimeoutException("Chat input box not found.")

            self._type_message_with_link_paste(chat_box, message)
            chat_box.send_keys(Keys.ENTER)
            time.sleep(random.uniform(0.8, 2.0))
            self._human_random_actions()

            # Remember as anchor chat for all forward actions
            if not self._first_chat_phone:
                self._first_chat_phone = phone

            logger.info("Message sent to +%s", phone)
            return True

        except TimeoutException as e:
            logger.error("Timeout while sending to +%s: %s", phone, e)
            return False
        except WebDriverException as e:
            logger.error("WebDriver error for +%s: %s", phone, e)
            return False
        except Exception as e:
            log_exception(logger, f"Unexpected error sending to +{phone}", e)
            return False

    def return_to_first_chat(self) -> bool:
        """
        Navigate back to the first contact's chat so the sent message bubble
        is visible and can be right-clicked for the next forward action.

        Retries twice with increasing delays; verifies the chat input box is
        present after navigating so we are genuinely inside the chat.
        """
        if not self._first_chat_phone:
            logger.warning("return_to_first_chat: no anchor chat recorded.")
            return False

        for attempt in range(2):
            logger.debug(
                "Returning to anchor chat +%s (attempt %d/2)",
                self._first_chat_phone, attempt + 1,
            )
            if self._search_and_open_chat(self._first_chat_phone, ""):
                time.sleep(random.uniform(1.0, 1.8))
                # Verify we are actually inside the correct chat
                if self._wait_for_chat_box(timeout=5) is not None:
                    logger.debug("Anchor chat confirmed open.")
                    return True
                logger.warning(
                    "Search succeeded but chat box not found — retrying (attempt %d/2).",
                    attempt + 1,
                )
            time.sleep(random.uniform(1.5, 2.5))

        logger.warning(
            "Failed to return to anchor chat +%s after 2 attempts.",
            self._first_chat_phone,
        )
        return False

    def send_message_paste(self, phone: str, message: str, name: str = "") -> bool:
        """
        Open the chat for *phone* and send *message* via full clipboard paste.

        Used for fallback contacts not found in the forward dialog.
        Returns True on success, False on failure.
        """
        logger.debug("Fallback paste-send to +%s", phone)
        if not self._search_and_open_chat(phone, name):
            logger.error("Failed to open chat (fallback paste) for +%s", phone)
            return False

        try:
            self._human_random_actions()
            chat_box = self._wait_for_chat_box()
            if chat_box is None:
                raise TimeoutException("Chat input box not found.")

            self._clipboard_paste(chat_box, message)
            chat_box.send_keys(Keys.ENTER)
            time.sleep(random.uniform(0.8, 2.0))
            self._human_random_actions()
            logger.info("Fallback paste-sent to +%s", phone)
            return True

        except Exception as e:
            log_exception(logger, f"Fallback paste failed for +{phone}", e)
            return False

    def send_via_new_chat(self, phone: str, message: str, name: str = "") -> bool:
        """
        Unknown-contacts mode: Click New Chat → search phone number →
        open chat → clipboard-paste full message → send.

        Does NOT use the Forward dialog — reliable for brand-new numbers
        that are not yet saved in the user's WhatsApp contacts.

        Anti-detection notes:
          - Uses _search_and_open_chat() (which already clicks New Chat button).
          - Full message is pasted via clipboard (fast, avoids per-char timing leaks).
          - Random pre/post human micro-actions are applied.
          - Caller (AutomationEngine) is responsible for inter-message delays.

        Returns True on success, False on failure.
        """
        logger.debug("[UNKNOWN/NEWCHAT] Opening new chat for +%s (%s)", phone, name)
        if not self._search_and_open_chat(phone, name):
            logger.error("[UNKNOWN/NEWCHAT] Could not open chat for +%s", phone)
            return False

        try:
            self._human_random_actions()
            chat_box = self._wait_for_chat_box()
            if chat_box is None:
                raise TimeoutException("[UNKNOWN/NEWCHAT] Chat input box not found.")

            # Small pre-send pause — mimics reading the chat before typing
            time.sleep(random.uniform(0.4, 1.2))

            self._clipboard_paste(chat_box, message)
            time.sleep(random.uniform(0.3, 0.8))   # brief "review" before hitting send
            chat_box.send_keys(Keys.ENTER)
            time.sleep(random.uniform(0.9, 2.2))
            self._human_random_actions()

            logger.info("[UNKNOWN/NEWCHAT] Message sent to +%s (%s)", phone, name)
            return True

        except Exception as e:
            log_exception(logger, f"[UNKNOWN/NEWCHAT] Failed for +{phone}", e)
            return False

    def send_file_via_new_chat(
        self, phone: str, message: str, file_path: str, name: str = ""
    ) -> bool:
        """
        Unknown-contacts mode with attachment: Click New Chat → search phone →
        open chat → attach file → paste caption → send.

        Used when an attachment_path is set and mode == "unknown".
        Returns True on success, False on failure.
        """
        if not os.path.isfile(file_path):
            logger.error("[UNKNOWN/NEWCHAT] Attachment not found: %s", file_path)
            return False

        logger.debug("[UNKNOWN/NEWCHAT] Opening new chat (with file) for +%s (%s)", phone, name)
        if not self._search_and_open_chat(phone, name):
            logger.error("[UNKNOWN/NEWCHAT] Could not open chat for +%s (file send)", phone)
            return False

        try:
            self._wait_for_chat_box()
            self._human_random_actions(skip_clip=True)

            ok = self._attach_and_send_file(file_path, message)
            if ok:
                logger.info("[UNKNOWN/NEWCHAT] File sent to +%s: %s", phone, file_path)
            return ok

        except Exception as e:
            log_exception(logger, f"[UNKNOWN/NEWCHAT] File send failed for +{phone}", e)
            return False

    def forward_message_to_contacts(self, phones: List[str]) -> Dict[str, str]:
        """
        Forward the last sent message to a batch of contacts using WhatsApp's
        native 4-step Forward flow.

        WhatsApp enforces a hard limit of 5 contacts per forward action.
        If more than 5 phones are provided, the list is silently clamped.

        Retries the entire flow up to 3 times on step-1 failures,
        refreshing the anchor chat between attempts.

        Args:
            phones: List of digits-only phone numbers for this batch.

        Returns:
            Dict mapping each phone to:
              "FORWARDED"       - ticked and sent via forward dialog
              "FALLBACK_NEEDED" - not found in dialog; needs individual send
              "FAILED"          - unexpected error
        """
        # ── Hard-clamp to WhatsApp's 5-contact limit ──────────────────────────
        if len(phones) > WHATSAPP_MAX_FORWARD_CONTACTS:
            logger.warning(
                "WhatsApp allows max %d contacts per forward. Clamping %d → %d.",
                WHATSAPP_MAX_FORWARD_CONTACTS, len(phones), WHATSAPP_MAX_FORWARD_CONTACTS,
            )
            phones = phones[:WHATSAPP_MAX_FORWARD_CONTACTS]

        results: Dict[str, str] = {p: "FALLBACK_NEEDED" for p in phones}

        for attempt in range(3):
            forwarded_any = False
            try:
                # ── Step 1: Hover over last sent message, click chevron ────────
                if not self._hover_and_open_message_menu():
                    logger.warning(
                        "Could not open message context menu (attempt %d/3). "
                        "Refreshing anchor chat and retrying.", attempt + 1,
                    )
                    self._press_escape()
                    # Navigate back to anchor and wait
                    if self._first_chat_phone:
                        self._search_and_open_chat(self._first_chat_phone, "")
                        time.sleep(random.uniform(2.5, 4.0))
                    continue

                time.sleep(random.uniform(0.4, 0.7))

                # ── Step 2: Click "Forward" in the context menu ────────────────
                if not self._click_forward_in_context_menu():
                    logger.error("Forward option not found in context menu (attempt %d/3).", attempt + 1)
                    self._press_escape()
                    time.sleep(1.0)
                    continue

                time.sleep(random.uniform(0.6, 1.0))

                # ── Step 3: Click the ">>" button in the selection-mode bar ────
                if not self._click_selection_mode_forward_btn():
                    logger.error("Selection-mode forward button not found (attempt %d/3).", attempt + 1)
                    self._press_escape()
                    time.sleep(1.0)
                    continue

                time.sleep(random.uniform(0.6, 1.0))

                # ── Step 4: Wait for "Forward message to" dialog ───────────────
                try:
                    WebDriverWait(self.driver, FORWARD_DIALOG_TIMEOUT).until(
                        EC.presence_of_element_located(
                            (By.XPATH, SelectorHelper.joined(Selectors.FORWARD_DIALOG))
                        )
                    )
                    logger.info("Forward dialog opened.")
                except TimeoutException:
                    logger.error(
                        "Forward dialog did not open within %ds (attempt %d/3).",
                        FORWARD_DIALOG_TIMEOUT, attempt + 1,
                    )
                    continue

                time.sleep(0.8)

                # ── Step 4a-c: Search each phone number, tick the match ────────
                for phone in phones:
                    try:
                        found = self._select_forward_contact_by_phone(phone)
                        if found:
                            results[phone] = "FORWARDED"
                            forwarded_any = True
                            logger.info("Ticked +%s in forward dialog.", phone)
                        else:
                            logger.info("+%s not found in forward dialog → fallback.", phone)
                    except Exception as e:
                        log_exception(logger, f"Error selecting +{phone} in forward dialog", e)
                        results[phone] = "FAILED"

                # ── Step 4d: Click the Send button ────────────────────────────
                if forwarded_any:
                    sent_ok = self._click_forward_send_button()
                    if sent_ok:
                        time.sleep(random.uniform(1.0, 1.5))
                        logger.info("Forward send confirmed — dialog closed.")
                        return results  # success — exit retry loop
                    else:
                        logger.error(
                            "Forward send button failed — dialog still open. "
                            "Escaping and marking batch as fallback (attempt %d/3).",
                            attempt + 1,
                        )
                        self._press_escape()
                        time.sleep(0.5)
                        for p in list(results.keys()):
                            if results[p] == "FORWARDED":
                                results[p] = "FALLBACK_NEEDED"
                        # Don't retry — send button failure usually means dialog closed
                        return results
                else:
                    self._press_escape()
                    return results  # no matches found — no point retrying

            except Exception as e:
                log_exception(logger, f"forward_message_to_contacts error (attempt {attempt+1}/3)", e)
                self._press_escape()
                time.sleep(1.5)

        logger.error("forward_message_to_contacts: all 3 attempts exhausted.")
        return results

    def send_file(self, phone: str, message: str, file_path: str, name: str = "") -> bool:
        """
        Send a file (image or document) with an optional caption to *phone*.
        Returns True on success, False on failure.
        """
        if not os.path.isfile(file_path):
            logger.error("Attachment not found: %s", file_path)
            return False

        if not self._search_and_open_chat(phone, name):
            logger.error("Failed to open chat for file send to +%s", phone)
            return False

        try:
            self._wait_for_chat_box()
            self._human_random_actions(skip_clip=True)

            ok = self._attach_and_send_file(file_path, message)
            if ok:
                # Remember anchor for forward actions (same as send_message)
                if not self._first_chat_phone:
                    self._first_chat_phone = phone
                logger.info("File sent to +%s: %s", phone, file_path)
            return ok

        except Exception as e:
            log_exception(logger, f"Failed to send file to +{phone}", e)
            return False

    # ── Private: attachment helpers ───────────────────────────────────────────

    def _attach_and_send_file(self, file_path: str, caption: str) -> bool:
        """
        Shared attachment flow used by send_file() and send_file_via_new_chat().

        Steps:
          1. Click the paperclip / Attach button to open the picker menu.
          2. Locate the hidden file <input> and make it interactable via JS
             (WhatsApp marks it display:none — direct send_keys would fail).
          3. Send the absolute file path to the input.
          4. Wait for the media preview to appear (up to 8 s).
          5. Optionally paste a caption into the caption box.
          6. Click the media Send button.

        Returns True on success, False on any unrecoverable failure.
        """
        abs_path = os.path.abspath(file_path)
        logger.debug("_attach_and_send_file: %s", abs_path)

        try:
            # ── Step 1: Click the attach / paperclip button ───────────────────
            clip = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.ATTACH_CLIP))
                )
            )
            clip.click()
            time.sleep(random.uniform(0.5, 1.0))

            # ── Step 2: Make the hidden file input interactable via JS ─────────
            # WhatsApp Web uses hidden <input type="file"> elements that are
            # blocked from direct interaction. We un-hide them with JS so that
            # Selenium's send_keys() can reach them.
            try:
                self.driver.execute_script("""
                    var inputs = document.querySelectorAll('input[type="file"]');
                    inputs.forEach(function(inp) {
                        inp.style.display = 'block';
                        inp.style.visibility = 'visible';
                        inp.style.opacity = '1';
                        inp.removeAttribute('hidden');
                    });
                """)
                time.sleep(0.3)
            except Exception as js_err:
                logger.debug("JS un-hide step warning (non-fatal): %s", js_err)

            # ── Step 3: Locate the input and send the file path ───────────────
            # Try the "Documents" input first (accept="*"), then any file input.
            file_input = None
            for xpath in Selectors.ATTACH_FILE_INPUT:
                try:
                    inputs = self.driver.find_elements(By.XPATH, xpath)
                    for inp in inputs:
                        try:
                            inp.send_keys(abs_path)
                            file_input = inp
                            logger.debug("File path sent via XPath: %s", xpath)
                            break
                        except Exception:
                            continue
                    if file_input:
                        break
                except Exception:
                    continue

            if file_input is None:
                # JS fallback: send_keys via JS value + change event
                logger.warning("XPath file input not found — trying JS DataTransfer fallback.")
                try:
                    self.driver.execute_script("""
                        var inp = document.querySelector('input[type="file"]');
                        if (!inp) return false;
                        // Can't set .files directly cross-origin, but we can
                        // trigger the native file dialog hack via nativeInputValueSetter.
                        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, arguments[0]);
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    """, abs_path)
                except Exception as e2:
                    logger.error("JS file injection also failed: %s", e2)
                    return False

            # ── Step 4: Wait for the media preview dialog to appear ───────────
            try:
                WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located(
                        (By.XPATH, SelectorHelper.joined(Selectors.SEND_MEDIA_BTN))
                    )
                )
                logger.debug("Media preview / send button detected.")
            except TimeoutException:
                logger.warning("Media send button not found in 8s — proceeding anyway.")
            time.sleep(random.uniform(0.8, 1.5))

            # ── Step 5: Paste caption if provided ────────────────────────────
            if caption:
                try:
                    caption_box = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, SelectorHelper.joined(Selectors.MEDIA_CAPTION_BOX))
                        )
                    )
                    caption_box.click()
                    time.sleep(0.3)
                    self._clipboard_paste(caption_box, caption)
                    time.sleep(random.uniform(0.3, 0.6))
                    logger.debug("Caption pasted into media preview.")
                except (TimeoutException, NoSuchElementException):
                    logger.debug("Caption box not found — sending without caption.")

            # ── Step 6: Click the media Send button ───────────────────────────
            send_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.SEND_MEDIA_BTN))
                )
            )
            send_btn.click()
            time.sleep(random.uniform(1.5, 3.0))
            logger.info("_attach_and_send_file: file sent successfully.")
            return True

        except Exception as e:
            log_exception(logger, "_attach_and_send_file failed", e)
            # Try pressing Escape to dismiss any open picker/preview before returning
            self._press_escape()
            return False

    # ── Private: forward step helpers ─────────────────────────────────────────

    def _hover_and_open_message_menu(self) -> bool:
        """
        Step 1 — Find the last outgoing message and open its context menu.

        Uses a tiered JS strategy that prefers messages with delivery ticks
        (double/single checkmarks) as the most reliable anchor, then falls
        back to message-out class, then to any data-id row.
        """
        try:
            # ── Scroll the main panel aggressively to bottom ─────────────────
            self.driver.execute_script("""
                var main = document.querySelector('#main');
                if (main) {
                    main.scrollTo(0, 999999);
                    var panel = main.querySelector(
                        '[data-testid="conversation-panel-messages"],'
                        + '[data-testid="msg-container"],'
                        + 'div[role="region"],'
                        + '.copyable-area'
                    );
                    if (panel) panel.scrollTo(0, 999999);
                } else {
                    window.scrollTo(0, document.body.scrollHeight);
                }
            """)
            time.sleep(1.2)

            # ── JS: find last sent message, tick-first priority ───────────────
            target = self.driver.execute_script("""
                // 1. Last message-out with a double-tick (delivered/read)
                var el = document.querySelector(
                    'div[data-id] [data-testid="msg-dblchk"]'
                );
                if (el) {
                    var p = el.closest('div[data-id]');
                    if (p) return p;
                }

                // 2. Last message-out with single tick (sent but not yet delivered)
                el = document.querySelector('div[data-id] [data-testid="msg-check"]');
                if (el) {
                    var p = el.closest('div[data-id]');
                    if (p) return p;
                }

                // 3. Any message-out div with a msg-time stamp
                el = document.querySelector('div[data-id] [data-testid="msg-time"]');
                if (el) {
                    var p = el.closest('div[data-id]');
                    if (p) return p;
                }

                // 4. Last visible .message-out element
                var outs = Array.from(
                    document.querySelectorAll('div.message-out, [class*="message-out"]')
                ).filter(function(d) { return d.offsetParent !== null; });
                if (outs.length > 0) return outs[outs.length - 1];

                // 5. Last div[role="row"] inside #main (generic row fallback)
                var rows = document.querySelectorAll('#main div[role="row"]');
                if (rows.length > 0) return rows[rows.length - 1];

                // 6. Last data-id element
                var dataIds = document.querySelectorAll('[data-id]');
                return dataIds.length > 0 ? dataIds[dataIds.length - 1] : null;
            """)

            if target is None:
                logger.error("_hover_and_open_message_menu: no message bubble found.")
                return False

            logger.debug(
                "Found message target: tag=%s data-id=%s",
                self.driver.execute_script("return arguments[0].tagName;", target),
                self.driver.execute_script(
                    "return arguments[0].getAttribute('data-id') || 'none';", target
                ),
            )

            # ── Scroll target into center of viewport ─────────────────────────
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'nearest'});",
                target,
            )
            time.sleep(0.5)

            # ── Dispatch JS mouse events to trigger the hover overlay ─────────
            self.driver.execute_script("""
                var el = arguments[0];
                ['mouseenter', 'mouseover', 'mousemove'].forEach(function(ev) {
                    el.dispatchEvent(new MouseEvent(ev, {bubbles: true, cancelable: true}));
                });
            """, target)
            time.sleep(0.6)

            # ── Move Selenium cursor onto the element ─────────────────────────
            ActionChains(self.driver).move_to_element(target).pause(0.6).perform()
            time.sleep(0.4)

            # ── Click the chevron dropdown button ─────────────────────────────
            for selector in Selectors.MSG_DROPDOWN_CHEVRON_GLOBAL:
                try:
                    chevron = self.driver.find_element(By.XPATH, selector)
                    if chevron.is_displayed():
                        ActionChains(self.driver).move_to_element(chevron).click(chevron).perform()
                        logger.debug("Clicked chevron via XPath: %s", selector)
                        return True
                except NoSuchElementException:
                    continue

            # ── JS click on any visible chevron ───────────────────────────────
            clicked = self.driver.execute_script("""
                var testids = ['down-context', 'msg-action-down'];
                for (var t = 0; t < testids.length; t++) {
                    var chevrons = document.querySelectorAll(
                        '[data-testid="' + testids[t] + '"]'
                    );
                    for (var i = 0; i < chevrons.length; i++) {
                        var rect = chevrons[i].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            chevrons[i].click();
                            return 'js-click:' + testids[t];
                        }
                    }
                }
            """)
            if clicked:
                logger.debug("Clicked message dropdown chevron via JS: %s", clicked)
                return True

            # ── Ultimate fallback: right-click ────────────────────────────
            logger.debug("Chevron not found; right-clicking message.")
            ActionChains(self.driver).context_click(target).perform()
            return True

        except Exception as e:
            log_exception(logger, "_hover_and_open_message_menu failed", e)
            return False

    def _click_forward_in_context_menu(self) -> bool:
        """Step 2 — Click the 'Forward' option in the open context menu."""
        try:
            forward_item = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.CONTEXT_FORWARD))
                )
            )
            forward_item.click()
            logger.debug("Clicked 'Forward' in context menu.")
            return True
        except TimeoutException:
            pass

        # JS fallback — search by visible text
        try:
            clicked = self.driver.execute_script("""
                var items = document.querySelectorAll('li, div[role="button"], span');
                for (var i = 0; i < items.length; i++) {
                    var text = items[i].innerText || items[i].textContent || '';
                    if (text.trim() === 'Forward') {
                        items[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                logger.debug("Clicked 'Forward' in context menu via JS.")
                return True
        except Exception as e:
            log_exception(logger, "_click_forward_in_context_menu JS fallback error", e)

        logger.error("'Forward' menu item not visible after 3s.")
        return False

    def _click_selection_mode_forward_btn(self) -> bool:
        """
        Step 3 — Click the ">>" forward-arrow button that appears in the
        selection-mode bar after clicking Forward in the context menu.
        """
        try:
            fwd_btn = WebDriverWait(self.driver, 8).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.SELECTION_FORWARD_BTN))
                )
            )
            fwd_btn.click()
            logger.debug("Clicked selection-mode forward ('>>') button.")
            return True
        except TimeoutException:
            logger.error("Selection-mode forward button not found within 8s.")
            return False

    def _select_forward_contact_by_phone(self, phone: str) -> bool:
        """
        Step 4a-c — In the open 'Forward message to' dialog, type *phone* into
        the search box and tick the first matching contact row.
        """
        try:
            # ── Locate the search box ─────────────────────────────────────
            search = self._safe_find(Selectors.FORWARD_DIALOG_SEARCH, timeout=7)

            if search is None:
                logger.error("Forward dialog search box NOT found for +%s.", phone)
                return False

            # ── Clear and type the phone number ───────────────────────────
            search.click()
            time.sleep(0.3)

            # Clear via JS (works for both input and contenteditable)
            self.driver.execute_script(
                "arguments[0].textContent=''; arguments[0].value='';", search
            )
            search.send_keys(Keys.CONTROL, 'a')
            search.send_keys(Keys.DELETE)
            time.sleep(0.2)

            # ── Anti-detection: occasionally search only the last 6-8 digits ──
            # This mimics how a real user might type — they don't always type
            # the full country code every single time.
            if len(phone) > 8 and random.random() < 0.40:
                digits = random.randint(6, 8)
                query = phone[-digits:]
                logger.debug(
                    "Partial-phone search for +%s: using last %d digits ('%s').",
                    phone, digits, query,
                )
            else:
                query = phone

            logger.debug("Typing '%s' in forward dialog search box.", query)
            for char in query:
                search.send_keys(char)
                time.sleep(random.uniform(0.05, 0.14))

            # Wait for results to appear
            time.sleep(FORWARD_SEARCH_WAIT)

            # ── Find result rows via JS ────────────────────────────────────
            rows = self.driver.execute_script("""
                var dialog = document.querySelector(
                    '[data-testid="contact-picker"],'
                    + '[data-testid="forward-compose"],'
                    + 'div[role="dialog"]'
                );
                if (!dialog) return [];
                var items = Array.from(dialog.querySelectorAll(
                    '[role="listitem"], [data-testid="cell-frame-container"], '
                    + '[role="option"], li'
                ));
                return items.filter(function(el) {
                    return el.offsetHeight > 0 && el.offsetWidth > 0;
                });
            """)

            if not rows:
                # XPath fallback
                rows = self.driver.find_elements(
                    By.XPATH, SelectorHelper.joined(Selectors.FORWARD_RESULT_ROW)
                )
                rows = [r for r in rows if r.is_displayed()]

            # Filter out section headers / non-contact rows
            SKIP_TEXTS = {
                "my status", "status", "recent chats", "my contacts",
                "contacts on whatsapp", "groups",
            }
            valid_rows = []
            for row in rows:
                try:
                    text = (row.text or self.driver.execute_script(
                        "return arguments[0].innerText || '';", row
                    )).strip().lower()

                    if any(skip in text for skip in SKIP_TEXTS):
                        continue
                    if not text:
                        continue
                    # Rows with checkboxes are actual contacts
                    has_checkbox = self.driver.execute_script(
                        "return arguments[0].querySelector('input[type=\"checkbox\"], "
                        "[role=\"checkbox\"]') !== null;", row
                    )
                    if not has_checkbox:
                        continue
                    valid_rows.append(row)
                except Exception:
                    valid_rows.append(row)

            logger.debug(
                "Forward dialog results for +%s: %d valid rows found.", phone, len(valid_rows)
            )

            if not valid_rows:
                # No result — clear search so next phone starts clean
                search.send_keys(Keys.CONTROL, 'a')
                search.send_keys(Keys.DELETE)
                self.driver.execute_script(
                    "arguments[0].textContent=''; arguments[0].value='';", search
                )
                return False

            # Tick the first matching valid row
            valid_rows[0].click()
            time.sleep(random.uniform(0.3, 0.6))
            logger.debug("Ticked first valid result row for +%s.", phone)

            # Clear search for next phone
            search.send_keys(Keys.CONTROL, 'a')
            search.send_keys(Keys.DELETE)
            self.driver.execute_script(
                "arguments[0].textContent=''; arguments[0].value='';", search
            )
            time.sleep(0.3)
            return True

        except Exception as e:
            log_exception(logger, f"_select_forward_contact_by_phone error for +{phone}", e)
            return False

    def _click_forward_send_button(self) -> bool:
        """
        Step 4d — Click the circular Send button inside the forward dialog.

        Returns True if the dialog closed (confirming the send worked),
        False if all strategies failed.
        """

        def _dialog_is_gone() -> bool:
            """Return True when the forward dialog is no longer in the DOM."""
            try:
                gone = self.driver.execute_script("""
                    var d = document.querySelector(
                        '[data-testid="forward-compose"],'
                        + '[data-testid="contact-picker"],'
                        + 'div[role="dialog"]'
                    );
                    return !d || d.offsetParent === null;
                """)
                return bool(gone)
            except Exception:
                return True  # session error = dialog gone

        # ── Strategy 1: JS with wds-ic-send-filled (PROVEN by DOM probe) ─────
        try:
            clicked = self.driver.execute_script("""
                var icon = document.querySelector('[data-testid="wds-ic-send-filled"]');
                if (icon) {
                    var btn = icon.closest('[role="button"]') || icon.parentElement;
                    if (btn) {
                        var r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            btn.click();
                            return 'wds-parent:' + Math.round(r.left) + ',' + Math.round(r.top);
                        }
                    }
                    icon.click();
                    return 'wds-icon-direct';
                }
                var sendBtns = Array.from(document.querySelectorAll(
                    '[role="button"][aria-label="Send"], button[aria-label="Send"]'
                ));
                for (var i = 0; i < sendBtns.length; i++) {
                    var r = sendBtns[i].getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        sendBtns[i].click();
                        return 'aria-send-' + i;
                    }
                }
                return null;
            """)
            if clicked:
                time.sleep(1.2)
                if _dialog_is_gone():
                    logger.debug("Forward send: JS strategy 1 confirmed (%s).", clicked)
                    return True
                logger.warning("JS strategy 1 clicked (%s) but dialog still open.", clicked)
        except Exception as e:
            logger.warning("JS send strategy 1 error: %s", e)

        # ── Strategy 2: XPath with Selectors.FORWARD_SEND_BTN ─────────────────
        try:
            send_btn = WebDriverWait(self.driver, 4).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.FORWARD_SEND_BTN))
                )
            )
            logger.debug(
                "Forward send: XPath found element: tag=%s testid=%s aria=%s",
                send_btn.tag_name,
                send_btn.get_attribute('data-testid') or '',
                send_btn.get_attribute('aria-label') or '',
            )
            send_btn.click()
            time.sleep(1.2)
            if _dialog_is_gone():
                logger.debug("Forward send: XPath click confirmed (dialog closed).")
                return True
            logger.warning("XPath send clicked but dialog still open.")
        except TimeoutException:
            logger.warning("XPath send button not found within 4s.")
        except Exception as e:
            logger.warning("XPath send click error: %s", e)

        # ── Strategy 3: Coordinate click at bottom-right corner of dialog ──────
        try:
            result = self.driver.execute_script("""
                var dialog = document.querySelector(
                    '[data-testid="forward-compose"],'
                    + '[data-testid="contact-picker"],'
                    + 'div[role="dialog"]'
                );
                if (!dialog) return null;
                var rect = dialog.getBoundingClientRect();
                var x = rect.right - 40;
                var y = rect.bottom - 40;
                var el = document.elementFromPoint(x, y);
                if (el) { el.click(); return 'coord:' + Math.round(x) + ',' + Math.round(y); }
                return null;
            """)
            if result:
                time.sleep(1.0)
                if _dialog_is_gone():
                    logger.debug("Forward send: coord-click confirmed (%s).", result)
                    return True
                logger.warning("Coord-click (%s) but dialog still open.", result)
        except Exception as e:
            logger.warning("JS coord-click error: %s", e)

        # ── Strategy 4: ActionChains near dialog bottom-right ─────────────────
        try:
            dialog_el = self.driver.find_element(
                By.XPATH,
                '//div[@role="dialog"] | //div[@data-testid="forward-compose"]'
                ' | //div[@data-testid="contact-picker"]'
            )
            size = dialog_el.size
            ActionChains(self.driver).move_to_element_with_offset(
                dialog_el,
                size['width'] // 2 - 20,
                size['height'] // 2 - 20,
            ).click().perform()
            time.sleep(1.0)
            if _dialog_is_gone():
                logger.debug("Forward send: ActionChains corner click confirmed.")
                return True
            logger.warning("ActionChains corner click but dialog still open.")
        except Exception as e:
            logger.warning("ActionChains send error: %s", e)

        # ── Strategy 5: Enter key as last resort ──────────────────────────────
        logger.error("All send button strategies failed — pressing Enter.")
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ENTER)
            time.sleep(1.0)
            if _dialog_is_gone():
                logger.debug("Forward send: Enter key confirmed.")
                return True
        except Exception:
            pass

        logger.error("Forward send button: dialog did NOT close — send likely failed.")
        return False

    # Backward-compat alias
    def _send_forward_selection(self):
        self._click_forward_send_button()

    # ── Private: helpers ──────────────────────────────────────────────────────

    def _safe_find(self, selector_list: List[str], timeout: float = 5):
        """
        Try each XPath in *selector_list* in order.
        Returns the first located element or None if all fail within *timeout*.

        The total budget is *timeout* seconds shared across all selectors.
        Each selector gets an equal slice of the remaining time.
        """
        if not selector_list:
            return None

        per_selector = max(timeout / len(selector_list), 0.5)
        for xpath in selector_list:
            try:
                return WebDriverWait(self.driver, per_selector).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            except TimeoutException:
                continue
            except Exception as e:
                logger.debug("_safe_find skipping xpath=%s error=%s", xpath, e)
                continue
        return None

    def _press_escape(self):
        """Send Escape to the page body to close any open menu or dialog."""
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass

    # ── Private: message input helpers ────────────────────────────────────────

    @staticmethod
    def _contains_link(message: str) -> bool:
        """Return True if the message contains at least one URL."""
        return bool(_URL_RE.search(message))

    def _clipboard_paste(self, element, text: str):
        """
        Copy *text* to the OS clipboard and paste it into *element* via Ctrl+V.
        Used for full-message fallback sends and for URL segments in mixed messages.
        """
        try:
            pyperclip.copy(text)
        except Exception as e:
            logger.warning("pyperclip.copy failed: %s — using send_keys", e)
            element.send_keys(text)
            return

        element.click()
        time.sleep(0.2)
        element.send_keys(Keys.CONTROL, 'v')
        time.sleep(random.uniform(0.3, 0.7))

    def _type_message_with_link_paste(self, element, message: str):
        """
        Send *message* to *element* using a hybrid strategy:
          - Plain text segments → typed character-by-character.
          - URL segments        → clipboard-pasted (preserves link exactly).
        """
        parts = _URL_RE.split(message)
        for part in parts:
            if not part:
                continue
            if _URL_RE.fullmatch(part):
                self._clipboard_paste(element, part)
            else:
                self._type_segment(element, part)

    def _type_segment(self, element, text: str):
        """Type a plain-text segment with human-like per-character delays."""
        lines = text.split("\n")
        try:
            actions = ActionChains(element.parent)
        except Exception:
            actions = None

        for i, line in enumerate(lines):
            for char in line:
                if random.random() < 0.02 and char.isalpha():
                    element.send_keys(random.choice("abcdefghijklmnopqrstuvwxyz"))
                    time.sleep(random.uniform(0.1, 0.3))
                    element.send_keys(Keys.BACKSPACE)
                    time.sleep(random.uniform(0.1, 0.3))

                element.send_keys(char)
                if random.random() < 0.1:
                    time.sleep(random.uniform(0.15, 0.4))
                else:
                    time.sleep(random.uniform(0.04, 0.18))

            if i < len(lines) - 1:
                element.send_keys(Keys.SHIFT, Keys.ENTER)
                time.sleep(random.uniform(0.4, 0.9))

        if actions:
            try:
                actions.move_by_offset(
                    random.randint(-15, 15), random.randint(-10, 10)
                ).perform()
                time.sleep(0.3)
            except Exception:
                pass

    # Legacy alias for send_file caption path
    def _type_message(self, element, message: str):
        self._type_message_with_link_paste(element, message)

    # ── Private: navigation helpers ───────────────────────────────────────────

    def _search_and_open_chat(self, phone: str, name: str) -> bool:
        """Search for a contact by phone number and open the chat."""
        # Try the New Chat button first (more reliable than the sidebar search)
        try:
            new_chat_btn = self.driver.find_element(
                By.XPATH, SelectorHelper.joined(Selectors.NEW_CHAT_BTN)
            )
            new_chat_btn.click()
            time.sleep(1.0)
        except Exception:
            pass

        try:
            # Wait for any visible editable / searchable element
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     '//*[@contenteditable="true"] | //input[@type="text"]'
                     ' | //input[@type="search"] | //input[not(@type)]')
                )
            )

            # Pick the right search box from all visible editables
            all_boxes = self.driver.find_elements(
                By.XPATH,
                '//*[@contenteditable="true"] | //input[@type="text"]'
                ' | //input[@type="search"] | //input[not(@type)]'
            )

            search_box = None
            for box in reversed(all_boxes):
                if not box.is_displayed():
                    continue
                tab = box.get_attribute("data-tab")
                if tab in ["1", "10", "6"]:  # skip chat/message/caption boxes
                    continue
                if box.get_attribute("type") == "file":
                    continue
                try:
                    box.click()
                    search_box = box
                    break
                except Exception:
                    continue

            if not search_box:
                raise Exception("No clickable search box found")

            search_box.send_keys(Keys.CONTROL, 'a')
            search_box.send_keys(Keys.BACKSPACE)
            time.sleep(0.5)

            for char in phone:
                search_box.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))

            time.sleep(random.uniform(1.5, 2.5))
            search_box.send_keys(Keys.ENTER)

            if self._wait_for_chat_box(timeout=10):
                return True

            # Try clicking the first search result
            try:
                first_contact = self.driver.find_element(
                    By.XPATH, SelectorHelper.joined(Selectors.SEARCH_RESULTS_CONTACT)
                )
                first_contact.click()
                if self._wait_for_chat_box(timeout=5):
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            logger.debug("_search_and_open_chat failed: %s", e)
            return False

    def _human_random_actions(self, intensity: str = "normal", skip_clip: bool = False):
        """
        Perform small randomised human-like actions. Non-critical; all errors ignored.

        Args:
            skip_clip: When True, skip the random attach-clip click. Pass True
                       whenever we are about to / have just used the attach flow
                       so we don't accidentally re-open the picker.
        """
        try:
            if random.random() < 0.6:
                self.driver.execute_script(
                    "window.scrollBy(0, arguments[0]);", random.randint(-300, 300)
                )
            if random.random() < 0.3:
                time.sleep(random.uniform(2, 6))
            if random.random() < 0.2:
                self.driver.execute_script(
                    "document.querySelector('div[data-testid=\"conversation-panel-messages\"]')"
                    "?.scrollBy(0, arguments[0]);",
                    random.randint(-400, 400),
                )
            if random.random() < 0.1:
                try:
                    emoji_btn = self.driver.find_element(
                        By.XPATH, SelectorHelper.joined(Selectors.EMOJI_BTN)
                    )
                    emoji_btn.click()
                    time.sleep(random.uniform(0.5, 1.5))
                    emoji_btn.click()
                except NoSuchElementException:
                    pass
            # NOTE: skip random clip-click when skip_clip=True (avoids interfering
            # with the attachment send flow or accidentally opening the picker).
            if not skip_clip and random.random() < 0.1:
                try:
                    clip = self.driver.find_element(
                        By.XPATH, SelectorHelper.joined(Selectors.ATTACH_CLIP)
                    )
                    clip.click()
                    time.sleep(random.uniform(0.5, 1.5))
                    clip.click()
                except NoSuchElementException:
                    pass
            for _ in range(random.randint(1, 3)):
                ActionChains(self.driver).move_by_offset(
                    random.randint(-120, 120), random.randint(-80, 80)
                ).perform()
                time.sleep(random.uniform(0.2, 0.8))
        except Exception:
            pass

    def _wait_for_chat_box(self, timeout: int = MESSAGE_SEND_TIMEOUT):
        """Wait for the message input box and return it (or None on timeout)."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable(
                    (By.XPATH, SelectorHelper.joined(Selectors.CHAT_BOX))
                )
            )
        except TimeoutException:
            return None
