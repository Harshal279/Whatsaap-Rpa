"""
utils/excel_reader.py
---------------------
Reads and validates contact data from an .xlsx, .xls, or .csv file.
Returns a list of contact dictionaries or raises descriptive errors.
"""

import re
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd

from config import EXCEL_COL_NAME, EXCEL_COL_PHONE, EXCEL_COL_MESSAGE


class ExcelValidationError(Exception):
    """Raised when the Excel file has structural or data issues."""


def _normalize_phone(raw: Any) -> str:
    """
    Strip all non-digit characters from a phone number and
    return a clean string suitable for WhatsApp Web URL.
    """
    return re.sub(r"\D", "", str(raw))


def _is_valid_phone(phone: str) -> bool:
    """
    A phone number is considered valid when it contains
    between 7 and 15 digits (E.164 range).
    """
    return 7 <= len(phone) <= 15


def read_contacts(filepath: str | Path) -> List[Dict[str, str]]:
    """
    Read an Excel file and return a list of validated contact dicts.

    Expected columns (case-insensitive):
        Name, Phone, Message

    Each returned dict has keys: 'name', 'phone', 'message', 'raw_phone'

    Args:
        filepath: Path to the .xlsx file.

    Returns:
        List of contact dictionaries.

    Raises:
        ExcelValidationError: If columns are missing or no valid rows found.
        FileNotFoundError:    If the file does not exist.
        ValueError:           If the file extension is not .xlsx, .xls, or .csv.
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    suffix = filepath.suffix.lower()
    if suffix not in (".xlsx", ".xls", ".csv"):
        raise ValueError(
            f"Unsupported file type: '{filepath.suffix}'. Use .xlsx, .xls, or .csv"
        )

    # ── Load file ─────────────────────────────────────────────────────────────
    if suffix == ".csv":
        # Try common encodings so CSVs exported from Excel work out of the box
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                df = pd.read_csv(filepath, dtype=str, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ExcelValidationError("Could not decode the CSV file. Try saving it as UTF-8.")
    else:
        df = pd.read_excel(filepath, dtype=str)

    # Normalize column names (strip whitespace, title-case)
    df.columns = [col.strip().title() for col in df.columns]

    required = {EXCEL_COL_NAME, EXCEL_COL_PHONE, EXCEL_COL_MESSAGE}
    missing = required - set(df.columns)
    if missing:
        raise ExcelValidationError(
            f"Missing required columns: {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    # ── Process rows ─────────────────────────────────────────────────────────
    contacts: List[Dict[str, str]] = []
    skipped: List[int] = []

    for idx, row in df.iterrows():
        name = str(row.get(EXCEL_COL_NAME, "")).strip()
        raw_phone = str(row.get(EXCEL_COL_PHONE, "")).strip()
        message = str(row.get(EXCEL_COL_MESSAGE, "")).strip()
        
        # Occasional natural message variation for the same template
        if message and "{greeting}" in message.lower():
            greetings = ["Hi", "Hello", "Hey", "Greetings"]
            message = re.sub(r"{greeting}", lambda _: __import__('random').choice(greetings), message, flags=re.IGNORECASE)

        # Template support for personalisation
        if name and name.lower() != "nan":
            message = message.replace("{name}", name)
        else:
            message = message.replace("{name}", "there")

        phone = _normalize_phone(raw_phone)

        if not name or name.lower() == "nan":
            name = "Unknown"

        if not _is_valid_phone(phone):
            skipped.append(idx + 2)  # +2 for header row + 1-indexed
            continue

        if not message or message.lower() == "nan":
            message = f"Hello {name}!"

        contacts.append({
            "name": name,
            "phone": phone,
            "message": message,
            "raw_phone": raw_phone,
        })

    if not contacts:
        raise ExcelValidationError(
            "No valid contacts found in the Excel file. "
            f"Rows skipped (invalid phone): {skipped}"
        )

    return contacts


def detect_duplicates(contacts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Remove duplicate phone numbers, keeping the first occurrence.

    Returns:
        De-duplicated list of contacts, with a 'duplicate' flag on removed ones.
    """
    seen: set = set()
    unique: List[Dict[str, str]] = []

    for c in contacts:
        if c["phone"] in seen:
            continue
        seen.add(c["phone"])
        unique.append(c)

    return unique
