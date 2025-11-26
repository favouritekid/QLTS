# app/security/__init__.py
"""
Security utilities for password hashing and token management.

REFACTORED (PHASE 1 - Task 1.9):
- Token management functions moved to services/auth_service.py
- Password utilities remain here (utility functions, not business logic)
- Token functions re-exported for backward compatibility

Password Functions (remain here):
- verify_password() - Verify password against hash
- get_password_hash() - Hash password

Token Functions (re-exported from auth_service):
- create_access_token()
- create_refresh_token()
- create_password_reset_token()
- verify_password_reset_token()
- decode_token()
- decode_token_for_invalidation()
"""

from passlib.context import CryptContext

# ✅ PHASE 1 Task 1.9: Import token functions from auth_service
# These are re-exported for backward compatibility
from ..services.auth_service import (
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
    decode_token,
    decode_token_for_invalidation,
)

# flake8: noqa: F401 (imported but unused - they are re-exported)

# =============================================================================
# PASSWORD UTILITIES (remain in security.py)
# =============================================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=14)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password
        hashed_password: Bcrypt password hash

    Returns:
        True if password matches hash, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Bcrypt password hash
    """
    return pwd_context.hash(password)
