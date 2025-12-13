# app/utils/phone_helpers.py
"""
Vietnam Phone Number Validation & Normalization

Supports:
- Mobile: 03x, 05x, 07x, 08x, 09x (10 digits)
- Landline: 02x (10-11 digits)
- With country code: +84, 84

References:
- VNPT, Viettel, Mobiphone, Vinaphone numbering plans
"""

import re
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# Regex for normalized Vietnam phone (after removing +84/84 prefix)
# Format: 0 + (3|5|7|8|9|2) + 8-9 digits = 10-11 total
VIETNAM_PHONE_REGEX = re.compile(r"^0(3|5|7|8|9|2)\d{8,9}$")

# Characters to strip from phone input
PHONE_STRIP_CHARS = " \t\n\r.-()/"


def normalize_vietnam_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalize a phone number to standard Vietnam format (0xxxxxxxxx).
    
    Transformations:
    - Remove spaces, dashes, dots, parentheses
    - Convert +84 → 0
    - Convert 84xxxxxxxx → 0xxxxxxxx (if 11-12 digits starting with 84)
    
    Args:
        phone: Raw phone input
        
    Returns:
        Normalized phone or None if input is None/empty
        
    Examples:
        >>> normalize_vietnam_phone("+84 901 234 567")
        "0901234567"
        >>> normalize_vietnam_phone("84-32-1234-567")
        "0321234567"
        >>> normalize_vietnam_phone("0901234567")
        "0901234567"
        >>> normalize_vietnam_phone("  ")
        None
    """
    if phone is None:
        return None
    
    # Strip whitespace and common separators
    cleaned = phone.strip()
    for char in PHONE_STRIP_CHARS:
        cleaned = cleaned.replace(char, "")
    
    if not cleaned:
        return None
    
    # Handle +84 prefix
    if cleaned.startswith("+84"):
        cleaned = "0" + cleaned[3:]
    # Handle 84 prefix (11-12 digits starting with 84)
    elif cleaned.startswith("84") and len(cleaned) in [11, 12]:
        cleaned = "0" + cleaned[2:]
    
    return cleaned


def validate_vietnam_phone(phone: Optional[str], normalize: bool = True) -> bool:
    """
    Validate if a phone number is a valid Vietnam phone number.
    
    Args:
        phone: Phone number to validate
        normalize: If True, normalize before validation (default: True)
        
    Returns:
        True if valid Vietnam phone number, False otherwise
        
    Examples:
        >>> validate_vietnam_phone("0901234567")
        True
        >>> validate_vietnam_phone("+84 321 234 567")
        True
        >>> validate_vietnam_phone("0001234567")
        False  # Invalid prefix 00
        >>> validate_vietnam_phone("0123456789")
        False  # Invalid prefix 01
    """
    if phone is None:
        return False
    
    # Normalize if requested
    if normalize:
        phone = normalize_vietnam_phone(phone)
    
    if not phone:
        return False
    
    # Match against Vietnam phone regex
    return bool(VIETNAM_PHONE_REGEX.match(phone))


def normalize_and_validate_vietnam_phone(phone: Optional[str]) -> tuple[Optional[str], bool]:
    """
    Normalize and validate a phone number in one call.
    
    Args:
        phone: Raw phone input
        
    Returns:
        Tuple of (normalized_phone, is_valid)
        - normalized_phone: Normalized phone or None
        - is_valid: True if valid Vietnam phone
        
    Examples:
        >>> normalize_and_validate_vietnam_phone("+84 901 234 567")
        ("0901234567", True)
        >>> normalize_and_validate_vietnam_phone("invalid")
        ("invalid", False)
    """
    normalized = normalize_vietnam_phone(phone)
    if normalized is None:
        return None, False
    
    is_valid = bool(VIETNAM_PHONE_REGEX.match(normalized))
    return normalized, is_valid
