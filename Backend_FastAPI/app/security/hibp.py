# app/security/hibp.py
"""
Have I Been Pwned (HIBP) breached password check using k-Anonymity API.

OWASP ASVS 5.0 §2.1.7 recommends checking passwords against known breaches.
Uses the k-Anonymity model: only the first 5 chars of the SHA-1 hash are sent
to the API, so the full password hash is never exposed.

References:
- https://haveibeenpwned.com/API/v3#SearchingPwnedPasswordsByRange
- OWASP ASVS 5.0 §2.1.7
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

HIBP_API_URL = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT = 3.0  # seconds - fail open on timeout
HIBP_BREACH_THRESHOLD = 0  # Any occurrence means breached


async def check_password_breached(password: str) -> tuple[bool, int]:
    """
    Check if a password appears in known data breaches via HIBP k-Anonymity API.

    How it works:
    1. SHA-1 hash the password
    2. Send first 5 hex chars (prefix) to HIBP API
    3. API returns all suffixes matching that prefix
    4. Check if our full hash suffix appears in the response

    Args:
        password: Plain text password to check

    Returns:
        Tuple of (is_breached, breach_count)
        - is_breached: True if password found in breaches
        - breach_count: Number of times seen in breaches (0 if not found)

    Note:
        Fails open (returns False, 0) on network errors to avoid
        blocking registration when HIBP is unreachable.
        Disabled in test mode via HIBP_CHECK_ENABLED setting.
    """
    from ..config import settings

    if not settings.HIBP_CHECK_ENABLED:
        return False, 0
    # SHA-1 hash the password
    sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1_hash[:5]
    suffix = sha1_hash[5:]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{HIBP_API_URL}{prefix}",
                headers={"User-Agent": "QLTS-PasswordCheck/1.0"},
                timeout=HIBP_TIMEOUT,
            )
            response.raise_for_status()

        # Parse response: each line is "SUFFIX:COUNT"
        for line in response.text.splitlines():
            parts = line.split(":")
            if len(parts) == 2 and parts[0] == suffix:
                count = int(parts[1])
                if count > HIBP_BREACH_THRESHOLD:
                    logger.warning(
                        "Password found in HIBP database (%d occurrences)", count
                    )
                    return True, count

        return False, 0

    except httpx.TimeoutException:
        logger.warning("HIBP API timeout after %.1fs - failing open", HIBP_TIMEOUT)
        return False, 0
    except httpx.HTTPError as e:
        logger.warning("HIBP API error: %s - failing open", str(e))
        return False, 0
    except Exception as e:
        logger.warning("Unexpected error checking HIBP: %s - failing open", str(e))
        return False, 0
