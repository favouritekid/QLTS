# app/services/auth_service.py
"""
PHASE 1 - Task 1.9: Token Management Service

Extracted token creation/validation business logic from security.py utility module.
This service provides protocol-independent token management functions.

Protocol Independence:
- No HTTP/FastAPI dependencies
- Uses standard Python types
- Can be called from CLI, Celery, tests, etc.

Functions:
- create_access_token() - Generate JWT access tokens
- create_refresh_token() - Generate JWT refresh tokens
- create_password_reset_token() - Generate password reset tokens
- decode_token() - Decode and validate tokens
- decode_token_for_invalidation() - Decode tokens for blacklisting
- verify_password_reset_token() - Verify password reset tokens
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple

from jose import JWTError, jwt

from ..config import settings
from ..utils.exceptions import InvalidToken


# =============================================================================
# ACCESS & REFRESH TOKEN MANAGEMENT
# =============================================================================

def create_access_token(
    data: dict,
    refresh_jti: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token with refresh token linkage.

    Business Rules:
    - Access token contains user claims (sub, role, etc.)
    - Linked to refresh token via r_jti (refresh JTI)
    - Short-lived (default: ACCESS_TOKEN_EXPIRE_MINUTES from settings)
    - Each token has unique JTI for revocation tracking

    Args:
        data: User claims to encode (e.g., {"sub": "user:123", "role": "admin"})
        refresh_jti: JTI of the associated refresh token (for token family tracking)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT access token string

    Example:
        >>> token = create_access_token(
        ...     data={"sub": "user:123", "role": "admin"},
        ...     refresh_jti="refresh-jti-abc123"
        ... )
        >>> # Token contains: {sub, role, exp, jti, type, r_jti}
    """
    to_encode = data.copy()

    # Calculate expiration
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # Add token metadata
    to_encode.update({
        "exp": expire,
        "jti": secrets.token_urlsafe(16),  # 128-bit cryptographically random token ID
        "type": "access",
        "r_jti": refresh_jti,  # Link to refresh token (for token family)
    })

    # Encode JWT
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT refresh token.

    Business Rules:
    - Refresh token used to obtain new access tokens
    - Long-lived (default: REFRESH_TOKEN_EXPIRE_DAYS from settings)
    - Each token has unique JTI for revocation tracking
    - Does not contain sensitive claims (only sub)

    Args:
        data: User claims to encode (typically just {"sub": "user:123"})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT refresh token string

    Example:
        >>> token = create_refresh_token(data={"sub": "user:123"})
        >>> # Token contains: {sub, exp, jti, type}
    """
    to_encode = data.copy()

    # Calculate expiration
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    # Add token metadata
    to_encode.update({
        "exp": expire,
        "jti": secrets.token_urlsafe(16),  # 128-bit cryptographically random token ID
        "type": "refresh",
    })

    # Encode JWT
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


# =============================================================================
# PASSWORD RESET TOKEN MANAGEMENT
# =============================================================================

def create_password_reset_token(email: str) -> str:
    """
    Create JWT token for password reset flow.

    Business Rules:
    - Short-lived (30 minutes)
    - Contains email and password_reset scope
    - Single-use (should be invalidated after use)

    Args:
        email: User's email address

    Returns:
        Encoded JWT password reset token

    Example:
        >>> token = create_password_reset_token("user@example.com")
        >>> # Send token via email to user
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)

    to_encode = {
        "exp": expire,
        "sub": email,
        "scope": "password_reset"
    }

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> Optional[str]:
    """
    Verify and decode password reset token.

    Business Rules:
    - Token must not be expired
    - Token must have password_reset scope
    - Returns email if valid, None if invalid

    Args:
        token: JWT password reset token string

    Returns:
        User email if token is valid, None otherwise

    Example:
        >>> email = verify_password_reset_token(token)
        >>> if email:
        ...     # Allow user to reset password
        >>> else:
        ...     # Token invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        # Verify scope
        if payload.get("scope") != "password_reset":
            return None

        email: str = payload.get("sub")
        return email

    except JWTError:
        return None


# =============================================================================
# TOKEN DECODING & VALIDATION
# =============================================================================

def decode_token(token: str) -> Dict:
    """
    Decode and validate JWT token.

    Used for authentication - validates signature and expiration.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload (dict)

    Raises:
        InvalidToken: If token is invalid, expired, or malformed

    Example:
        >>> payload = decode_token(access_token)
        >>> user_id = payload["sub"]
        >>> user_role = payload.get("role")
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        raise InvalidToken(detail=f"Invalid token: {e}")


def decode_token_for_invalidation(token: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Decode token for blacklisting/invalidation purposes.

    Unlike decode_token(), this does NOT verify expiration,
    allowing us to blacklist even expired tokens.

    Business Rules:
    - Extracts JTI (for blacklist key)
    - Calculates remaining TTL (for Redis expiration)
    - Works with both expired and valid tokens

    Args:
        token: JWT token string

    Returns:
        Tuple of (jti, remaining_ttl_seconds)
        - jti: Token ID for blacklist
        - remaining_ttl: Seconds until token expires (for Redis TTL)
        Returns (None, None) if token is malformed

    Example:
        >>> jti, ttl = decode_token_for_invalidation(token)
        >>> if jti:
        ...     # Add to blacklist: redis.setex(f"blacklist:{jti}", ttl, "1")
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False}  # Don't verify expiration
        )

        jti = payload.get("jti")
        exp = payload.get("exp")

        # Calculate remaining TTL
        remaining_ttl = None
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            remaining_ttl = max(0, int(exp - now))

        return jti, remaining_ttl

    except JWTError:
        return None, None
