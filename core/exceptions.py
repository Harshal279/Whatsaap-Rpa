"""
core/exceptions.py
------------------
Typed exception hierarchy for WhatsApp RPA automation.

Raising specific exceptions instead of returning False from critical paths
lets the caller differentiate failures and apply the right recovery strategy
without swallowing stack traces.
"""


class WhatsAppRPAError(Exception):
    """Base class for all WhatsApp RPA errors."""


class BrowserDeadError(WhatsAppRPAError):
    """Raised when the Selenium WebDriver session is no longer alive."""


class ChatNotFoundError(WhatsAppRPAError):
    """Raised when a chat cannot be opened for a given phone number."""

    def __init__(self, phone: str):
        self.phone = phone
        super().__init__(f"Could not open chat for +{phone}")


class ForwardFlowError(WhatsAppRPAError):
    """Raised when any step of the Forward dialog flow fails unrecoverably."""

    def __init__(self, step: str, detail: str = ""):
        self.step = step
        self.detail = detail
        msg = f"Forward flow failed at step '{step}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class BlockedError(WhatsAppRPAError):
    """
    Raised (or returned as a signal) when WhatsApp detects suspicious activity
    and shows a block/rate-limit banner.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"WhatsApp blocked: {reason}")
