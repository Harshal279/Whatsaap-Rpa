"""
core/selectors.py
-----------------
Centralized XPath / CSS selector repository for WhatsApp Web automation.

DESIGN
------
Every selector group is a plain list[str].  The first element is the most
current / most-specific selector (proven against the latest WhatsApp Web DOM).
Subsequent elements are ordered fallbacks tried in sequence.

When WhatsApp updates its DOM, only this file needs editing — no hunting
through whatsapp_bot.py for scattered magic strings.

USAGE IN whatsapp_bot.py
------------------------
    from core.selectors import Selectors, SelectorHelper

    # Build a joined XPath for WebDriverWait (any-of semantics):
    xpath = SelectorHelper.joined(Selectors.CHAT_BOX)

    # Iterate for manual fallback chains:
    for xpath in Selectors.SEARCH_BOX:
        el = driver.find_elements(By.XPATH, xpath)
        if el:
            ...
"""

from typing import List


class Selectors:
    """
    Static collection of XPath selector lists.

    Convention
    ----------
    Each attribute is a list[str] ordered best-first → fallback-last.
    All XPaths use absolute paths (start with //) so they can be used
    both with WebDriverWait and driver.find_elements directly.
    """

    # ── Login / Session ────────────────────────────────────────────────────────

    QR_CODE: List[str] = [
        '//canvas[@aria-label="Scan me!"]',
        '//div[@data-testid="qr-code"]',
        '//div[@data-ref]',
    ]

    LOGGED_IN: List[str] = [
        '//div[@data-testid="chat-list"]',
        '//div[@aria-label="Chat list"]',
        '//div[@id="pane-side"]',
    ]

    # ── Navigation / Search ────────────────────────────────────────────────────

    NEW_CHAT_BTN: List[str] = [
        '//div[@title="New chat"]',
        '//span[@data-testid="chat"]',
        '//button[@aria-label="New chat"]',
        '//div[@data-testid="new-chat-btn"]',
    ]

    SEARCH_BOX: List[str] = [
        '//div[@contenteditable="true"][@data-tab="3"]',
        '//div[@aria-label="Search input textbox"]',
        '//div[@title="Search input textbox"]',
        '//div[@data-testid="chat-list-search"]',
        '//div[@aria-label="Search name or number"]',
        '//div[@title="Search name or number"]',
        '//div[@id="side"]//div[@contenteditable="true"]',
    ]

    # ── Chat input box ─────────────────────────────────────────────────────────

    CHAT_BOX: List[str] = [
        '//div[@contenteditable="true"][@data-tab="10"]',
        '//div[@contenteditable="true"][@data-tab="1"]',
        '//footer//div[@contenteditable="true"]',
    ]

    # ── Attachments ────────────────────────────────────────────────────────────

    ATTACH_CLIP: List[str] = [
        '//div[@data-testid="clip"]',
        '//span[@data-testid="clip"]',
        '//button[@aria-label="Attach"]',
        '//div[@title="Attach"]',
    ]

    ATTACH_FILE_INPUT: List[str] = [
        # Document / any-file picker (most reliable for non-image files)
        '//input[@accept="*"]',
        '//input[@accept="*/*"]',
        # Image / video picker
        '//input[@accept="image/*,video/mp4,video/3gpp,video/quicktime"]',
        # Generic fallbacks
        '//input[@type="file"]',
        '//span[@data-testid="attach-document"]//input[@type="file"]',
        '//li[@data-testid="mi-attach-document"]//input[@type="file"]',
    ]

    SEND_MEDIA_BTN: List[str] = [
        '//div[@data-testid="send"]',
        '//span[@data-testid="send"]',
        '//button[@data-testid="send"]',
    ]

    MEDIA_CAPTION_BOX: List[str] = [
        '//div[@contenteditable="true"][@data-tab="6"]',
        '//div[@data-testid="media-caption-input-container"]//div[@contenteditable]',
    ]

    # ── Forward flow — Step 1: message bubble ──────────────────────────────────
    # LAST_SENT_MESSAGE — ordered best-first:
    #   1. message-out div that contains a delivery tick (double or single)
    #   2. message-out div by class alone
    #   3. last child of the message container
    #   4. any div with a data-id (final fallback)

    LAST_SENT_MESSAGE: List[str] = [
        '//div[contains(@class,"message-out") and .//*[@data-testid="msg-dblchk"]]',
        '//div[contains(@class,"message-out") and .//*[@data-testid="msg-check"]]',
        '//div[contains(@class,"message-out") and .//*[@data-testid="msg-time"]]',
        '//div[contains(@class,"message-out")]',
        '//*[@data-testid="msg-container"]//div[@data-id][last()]',
        '//div[@data-id and .//span[@data-testid="msg-dblchk"]]',
        '//div[@data-id]',
    ]

    # Keep legacy alias for any references
    LAST_OUT_MSG = LAST_SENT_MESSAGE

    # ── Forward flow — Step 1: chevron dropdown ────────────────────────────────

    MSG_DROPDOWN_CHEVRON: List[str] = [
        './/div[@data-testid="down-context"]',
        './/span[@data-testid="down-context"]',
        './/button[@data-testid="down-context"]',
        './/div[@data-testid="msg-action-down"]',
    ]

    # Same selectors but scoped to document root (for global fallback search)
    MSG_DROPDOWN_CHEVRON_GLOBAL: List[str] = [
        '//*[@data-testid="down-context"]',
        '//*[@data-testid="msg-action-down"]',
    ]

    # ── Forward flow — Step 2: "Forward" in context menu ──────────────────────

    CONTEXT_FORWARD: List[str] = [
        '//*[@data-testid="mi-msg-forward"]',
        '//li[normalize-space(.)="Forward"]',
        '//div[normalize-space(.)="Forward" and @role="button"]',
        '//div[@aria-label="Forward message"]',
        '//div[@aria-label="Forward"]',
        '//ul//li[contains(.,"Forward")]',
    ]

    # ── Forward flow — Step 3: "»" forward button in selection-mode bar ───────

    SELECTION_FORWARD_BTN: List[str] = [
        '//span[@data-testid="forward"]',
        '//div[@data-testid="forward"]',
        '//button[@data-testid="forward"]',
        '//span[@data-icon="forward"]',
        '//div[@aria-label="Forward"][@role="button"]',
        '//button[@aria-label="Forward"]',
    ]

    # ── Forward flow — Step 4: "Forward message to" dialog container ──────────

    FORWARD_DIALOG: List[str] = [
        '//div[@data-testid="forward-compose"]',
        '//div[@data-testid="contact-picker"]',
        '//div[@role="dialog"][.//input[@placeholder="Search name or number"]]',
        '//div[.//span[normalize-space(text())="Forward message to"]]',
    ]

    # ── Forward flow — Step 4: search box inside the dialog ───────────────────

    FORWARD_DIALOG_SEARCH: List[str] = [
        '//input[@placeholder="Search name or number"]',
        '//input[@placeholder="Search name or number "]',
        '//div[@data-testid="contact-picker"]//input[@type="text"]',
        '//div[@data-testid="forward-compose"]//input[@type="text"]',
        '//div[@aria-label="Forward message to"]//input',
        '//div[@role="dialog"]//input[@type="text"]',
        '//div[@role="dialog"]//input[@type="search"]',
        '//div[@role="dialog"]//div[@contenteditable="true"]',
    ]

    # ── Forward flow — Step 4: contact rows in the dialog ─────────────────────

    FORWARD_RESULT_ROW: List[str] = [
        '//div[@role="dialog"]//div[@role="listitem"]',
        '//div[@role="dialog"]//div[@data-testid="cell-frame-container"]',
        '//div[@data-testid="contact-picker"]//div[@role="listitem"]',
        '//div[@role="dialog"]//div[@role="option"]',
    ]

    # ── Forward flow — Step 4d: Send button ───────────────────────────────────
    #
    # DOM-probe confirmed:
    #   [DIV] aria='Send' role='button' pos=(804,551) size=46x46
    #   [SPAN] testid='wds-ic-send-filled' pos=(812,559) size=30x30  (icon)
    #
    # NOTE: The button is NOT scoped inside div[role="dialog"] — use global paths.

    FORWARD_SEND_BTN: List[str] = [
        # 2026 WhatsApp: icon span -> ancestor button or role=button div
        '//*[@data-testid="wds-ic-send-filled"]/ancestor::button',
        '//*[@data-testid="wds-ic-send-filled"]/ancestor::div[@role="button"]',
        '//div[@role="button"][.//*[@data-testid="wds-ic-send-filled"]]',
        '//button[@aria-label="Send"][@data-testid]',
        # Direct aria-label (unscoped — button is outside dialog DOM)
        '//div[@aria-label="Send"][@role="button"]',
        '//button[@aria-label="Send"]',
        # Legacy / older WA Web versions
        '//*[@data-testid="wds-ic-send-filled"]/parent::*',
        '//div[@data-testid="forward-compose-btn"]',
        '//span[@data-testid="compose-btn-send"]',
        '//*[@data-testid="wds-ic-send-filled"]',
    ]

    # ── Block / Error detection (NEW) ─────────────────────────────────────────

    MSG_NOT_SENT_BANNER: List[str] = [
        '//*[contains(text(),"Message not sent")]',
        '//*[contains(@aria-label,"Message not sent")]',
        '//div[@data-testid="msg-not-sent"]',
        '//*[contains(text(),"Couldn\'t send")]',
    ]

    TRYING_TO_CONNECT: List[str] = [
        '//*[contains(text(),"Trying to connect")]',
        '//*[contains(text(),"Connecting")]',
        '//div[@data-testid="status-banner"]',
    ]

    RATE_LIMIT_BANNER: List[str] = [
        '//*[contains(text(),"Too many messages")]',
        '//*[contains(text(),"temporarily blocked")]',
        '//*[contains(text(),"You\'ve been temporarily")]',
    ]

    # ── Miscellaneous ─────────────────────────────────────────────────────────

    EMOJI_BTN: List[str] = [
        '//div[@data-testid="smiley-or-emoji-button"]',
        '//span[@data-testid="smiley"]',
    ]

    SEARCH_RESULTS_CONTACT: List[str] = [
        '//div[@aria-label="Search results"]//div[@role="listitem"]',
        '//div[contains(@class,"matched-text")]/ancestor::div[@role="button"]',
        '//div[@data-testid="cell-frame-container"]',
    ]


class SelectorHelper:
    """Utility methods for working with selector lists."""

    @staticmethod
    def joined(*selector_lists: List[str]) -> str:
        """
        Join one or more selector lists into a single XPath string
        using the '|' union operator.

        Example::

            xpath = SelectorHelper.joined(Selectors.CHAT_BOX)
            # or combine multiple:
            xpath = SelectorHelper.joined(Selectors.SEARCH_BOX, Selectors.CHAT_BOX)
        """
        all_xpaths: List[str] = []
        for lst in selector_lists:
            all_xpaths.extend(lst)
        return " | ".join(all_xpaths)

    @staticmethod
    def joined_relative(*selector_lists: List[str]) -> str:
        """
        Same as joined() but converts leading '//' to './/' for relative context.
        Use when searching within a parent element.
        """
        all_xpaths: List[str] = []
        for lst in selector_lists:
            for xpath in lst:
                if xpath.startswith("//"):
                    xpath = "." + xpath
                all_xpaths.append(xpath)
        return " | ".join(all_xpaths)
