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
# ⚠ Dùng [0-9] (KHÔNG \d): \d của Python khớp cả Unicode digit (full-width
# ０-９, Arabic ٠-٩) → 2 chuỗi cùng "số" nhưng khác byte sẽ lọt UNIQUE,
# phá dedupe global + sinh số export không hợp lệ.
VIETNAM_PHONE_REGEX = re.compile(r"^0(3|5|7|8|9|2)[0-9]{8,9}$")

# Mobile-ONLY: 0 + (3|5|7|8|9) + 8 digits = đúng 10 chữ số (ASCII).
# Loại đầu số 02x (landline) mà VIETNAM_PHONE_REGEX vẫn chấp nhận.
VIETNAM_MOBILE_REGEX = re.compile(r"^0[35789][0-9]{8}$")

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


def to_zalo_phone(phone: Optional[str]) -> Optional[str]:
    """
    Convert a Vietnam phone number to Zalo format (84xxx).

    Zalo API requires phone numbers in international format without '+':
    - 0901234567 → 84901234567
    - +84901234567 → 84901234567
    - 84901234567 → 84901234567

    Args:
        phone: Raw phone input

    Returns:
        Phone in 84xxx format, or None if invalid

    Examples:
        >>> to_zalo_phone("0901234567")
        "84901234567"
        >>> to_zalo_phone("+84 321 234 567")
        "84321234567"
        >>> to_zalo_phone("invalid")
        None
    """
    normalized = normalize_vietnam_phone(phone)
    if not normalized:
        return None

    if not validate_vietnam_phone(normalized, normalize=False):
        return None

    # 0xxxxxxxxx → 84xxxxxxxxx
    if normalized.startswith("0"):
        return "84" + normalized[1:]

    return None


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


def is_vietnam_mobile(phone_normalized: Optional[str]) -> bool:
    """
    True nếu là số DI ĐỘNG Việt Nam (0[35789]xxxxxxxx — đúng 10 chữ số).

    Khác ``validate_vietnam_phone`` (chấp nhận cả landline 02x). SMS
    Marketing chỉ gửi tới di động nên import phải lọc mobile-only.

    Args:
        phone_normalized: Số đã normalize (0xxxxxxxxx); KHÔNG tự normalize.

    Returns:
        True nếu khớp đầu số di động VN.
    """
    if not phone_normalized:
        return False
    return bool(VIETNAM_MOBILE_REGEX.match(phone_normalized))


def normalize_vn_mobile(phone: Optional[str]) -> Optional[tuple[str, str]]:
    """(normalized, international=84xxx) nếu là DI ĐỘNG VN hợp lệ; None nếu không.

    Gộp normalize + ép mobile-only + dựng dạng quốc tế — dùng chung cho tạo
    contact (``SmsContactService``) và consult-link (khoá thống nhất theo phone).
    KHÔNG raise (giữ util thuần); caller tự raise domain exception với thông điệp
    phù hợp ngữ cảnh.
    """
    normalized = normalize_vietnam_phone(phone)
    if not normalized or not is_vietnam_mobile(normalized):
        return None
    return normalized, to_zalo_phone(normalized)
