"""Text normalization helpers for channel-specific constraints.

Zalo ``BANK_TRANSFER_NOTE`` params reject any character outside
``^[a-zA-Z0-9 ]+$``  — Vietnamese diacritics, dashes, and punctuation all
trigger ``-1124 invalid format``. This mirrors real Vietnamese banks'
Nội-dung-chuyển-khoản field, which strips accents + special chars server-side.
"""
import re
import unicodedata
from typing import Optional


def to_bank_transfer_note(raw: Optional[str], max_len: int = 90) -> str:
    """Strip Vietnamese diacritics and non-alphanumeric characters.

    Keeps ASCII letters, digits, and single-spaces (collapses runs). Truncates
    to ``max_len`` (Zalo BANK_TRANSFER_NOTE cap = 90).  Returns empty string
    for falsy input.
    """
    if not raw:
        return ""
    # NFD decomposition splits accented chars into base + combining mark;
    # dropping Mn (Mark, nonspacing) removes the accent while keeping the letter.
    normalized = unicodedata.normalize("NFD", raw)
    ascii_str = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    # Replace đ/Đ separately — NFD doesn't decompose them (Latin Extended).
    ascii_str = ascii_str.replace("đ", "d").replace("Đ", "D")
    # Collapse any non-[a-zA-Z0-9] run into a single space, then trim.
    ascii_str = re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_str)
    ascii_str = re.sub(r"\s+", " ", ascii_str).strip()
    return ascii_str[:max_len]
