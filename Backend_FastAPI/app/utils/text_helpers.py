"""Text normalization helpers for channel-specific constraints.

Zalo ``BANK_TRANSFER_NOTE`` params reject any character outside
``^[a-zA-Z0-9 ]+$``  — Vietnamese diacritics, dashes, and punctuation all
trigger ``-1124 invalid format``. This mirrors real Vietnamese banks'
Nội-dung-chuyển-khoản field, which strips accents + special chars server-side.
"""
import re
import unicodedata
from typing import Optional


def strip_diacritics(raw: Optional[str]) -> str:
    """Bỏ dấu tiếng Việt, GIỮ nguyên mọi ký tự khác (khoảng trắng, dấu câu).

    Dùng chung cho mọi chỗ cần so khớp không-dấu (slug nhóm/campaign, nhận
    diện header import…) — đừng chép lại vòng NFD ở service mới.
    """
    if not raw:
        return ""
    # NFD decomposition splits accented chars into base + combining mark;
    # dropping Mn (Mark, nonspacing) removes the accent while keeping the letter.
    normalized = unicodedata.normalize("NFD", raw)
    ascii_str = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    # Replace đ/Đ separately — NFD doesn't decompose them (Latin Extended).
    return ascii_str.replace("đ", "d").replace("Đ", "D")


def to_bank_transfer_note(raw: Optional[str], max_len: int = 90) -> str:
    """Strip Vietnamese diacritics and non-alphanumeric characters.

    Keeps ASCII letters, digits, and single-spaces (collapses runs). Truncates
    to ``max_len`` (Zalo BANK_TRANSFER_NOTE cap = 90).  Returns empty string
    for falsy input.
    """
    if not raw:
        return ""
    ascii_str = strip_diacritics(raw)
    # Collapse any non-[a-zA-Z0-9] run into a single space, then trim.
    ascii_str = re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_str)
    ascii_str = re.sub(r"\s+", " ", ascii_str).strip()
    return ascii_str[:max_len]


# Escape character used by ``escape_like_pattern``. Repositories MUST pass
# the same character to ``.ilike(..., escape=LIKE_ESCAPE_CHAR)`` so the
# escaped wildcards are honoured by PostgreSQL.
LIKE_ESCAPE_CHAR = "\\"


def escape_like_pattern(value: str) -> str:
    """Escape ``%`` and ``_`` so user input is treated as a literal in LIKE.

    Without this, a search for ``"a%"`` collapses any LIKE filter into
    "match-everything-after-a", letting an attacker either expand a result
    set past the intended scope or trigger a worst-case backtracking
    pattern (DoS). Always pair the returned value with
    ``.ilike(f"%{escape_like_pattern(v)}%", escape=LIKE_ESCAPE_CHAR)``.

    The backslash itself is escaped first so the user-controlled string
    cannot smuggle a stray ``\\%`` past the second pass.
    """
    return (
        value.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR + LIKE_ESCAPE_CHAR)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )
