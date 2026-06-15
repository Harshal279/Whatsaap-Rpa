"""
utils/logger.py
---------------
Centralized logging setup used across the entire application.
Creates both file-based and in-memory handlers so the UI console
can stream log records in real time.
"""

import logging
import logging.handlers
from pathlib import Path
from config import LOG_FORMAT, LOG_DATE_FORMAT, LOG_FILE


class UILogHandler(logging.Handler):
    """
    Custom logging handler that forwards records to a callback
    so the UI console widget can display them in real time.
    """

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._callback(msg, record.levelname)
        except Exception:
            self.handleError(record)


def get_logger(name: str, ui_callback=None) -> logging.Logger:
    """
    Return a fully configured logger instance.

    Args:
        name:        Module name (e.g. __name__).
        ui_callback: Optional callable(message: str, level: str) for UI streaming.

    Returns:
        logging.Logger
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times if logger already exists
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # ── Rotating file handler (max 5 MB, 3 backups) ──────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # ── Console (stdout) handler ─────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ── UI streaming handler ─────────────────────────────────────────────────
    if ui_callback:
        ui_handler = UILogHandler(ui_callback)
        ui_handler.setLevel(logging.DEBUG)
        ui_handler.setFormatter(formatter)
        logger.addHandler(ui_handler)

    return logger


def log_exception(logger_instance: logging.Logger, msg: str, exc: Exception) -> None:
    """
    Log *exc* with a full traceback at ERROR level.

    Prefer this over ``logger.error("...: %s", e)`` in critical paths so that
    stack traces are never silently discarded.

    Usage::

        try:
            ...
        except Exception as e:
            log_exception(logger, "Forward flow failed", e)
    """
    logger_instance.error("%s: %s", msg, exc, exc_info=True)
