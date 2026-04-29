# app/utils/masking.py
"""
Data Masking Utilities.

Provides functions to mask sensitive data for display purposes.
Follows security best practices for PII (Personally Identifiable Information).
"""

from typing import Optional


def mask_citizen_id(citizen_id: Optional[str], visible_digits: int = 4) -> Optional[str]:
    """
    Mask a citizen ID (CCCD/CMND) for display.

    Shows only the last N digits, masks the rest with asterisks.

    Args:
        citizen_id: Full citizen ID (12 digits for CCCD)
        visible_digits: Number of digits to show at the end (default: 4)

    Returns:
        Masked citizen ID or None if input is None/empty

    Examples:
        >>> mask_citizen_id("034567891234")
        "********1234"

        >>> mask_citizen_id("034567891234", visible_digits=6)
        "******891234"

        >>> mask_citizen_id(None)
        None
    """
    if not citizen_id:
        return None

    if len(citizen_id) <= visible_digits:
        return citizen_id  # Too short to mask meaningfully

    masked_length = len(citizen_id) - visible_digits
    return "*" * masked_length + citizen_id[-visible_digits:]


def mask_phone(phone: Optional[str], visible_digits: int = 4) -> Optional[str]:
    """
    Mask a phone number for display.

    Shows only the last N digits, masks the rest with asterisks.

    Args:
        phone: Full phone number
        visible_digits: Number of digits to show at the end (default: 4)

    Returns:
        Masked phone number or None if input is None/empty

    Examples:
        >>> mask_phone("0901234567")
        "******4567"

        >>> mask_phone("0901234567", visible_digits=3)
        "*******567"
    """
    if not phone:
        return None

    # Remove any non-digit characters for consistent masking
    digits_only = ''.join(c for c in phone if c.isdigit())

    if len(digits_only) <= visible_digits:
        return phone  # Too short to mask

    masked_length = len(digits_only) - visible_digits
    return "*" * masked_length + digits_only[-visible_digits:]


def mask_chat_id(chat_id: Optional[str]) -> str:
    """Mask a Zalo Bot chat_id for log/audit/dispatch payloads.

    Returns ``"XXXX***YY"`` — first 4 + last 2 chars with ``***`` between.
    Format is stable across the codebase (webhook logs, audit rows, and
    notification dedup keys all rely on it) so do not change the
    separator without coordinating an audit-row + dedup-key migration.

    Why first-4 + last-2 (not first-8): Zalo chat_ids are ~20 hex chars,
    and exposing 8/20 (40%) is enough to correlate IDs across logs if an
    attacker gets a partial leak. 6/20 (30%) keeps logs greppable for
    operators while reducing pivot value for an attacker.
    """
    if not chat_id:
        return ""
    if len(chat_id) <= 6:
        return chat_id[:2] + "***"
    return chat_id[:4] + "***" + chat_id[-2:]


def mask_email(email: Optional[str]) -> Optional[str]:
    """
    Mask an email address for display.

    Shows first 2 characters of local part + masked + domain.

    Args:
        email: Full email address

    Returns:
        Masked email or None if input is None/empty

    Examples:
        >>> mask_email("nguyenvana@example.com")
        "ng*****@example.com"

        >>> mask_email("ab@test.com")
        "ab@test.com"  # Too short to mask
    """
    if not email or "@" not in email:
        return email

    local_part, domain = email.rsplit("@", 1)

    if len(local_part) <= 2:
        return email  # Too short to mask

    visible_start = 2
    masked_local = local_part[:visible_start] + "*" * (len(local_part) - visible_start)

    return f"{masked_local}@{domain}"
