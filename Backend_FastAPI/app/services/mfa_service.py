# app/services/mfa_service.py
"""
MFA (Multi-Factor Authentication) Service - TOTP-based.

Pure Python service (no FastAPI imports). Follows service isolation pattern:
- Input: Pydantic models / primitives
- Output: Tuple (result, post_commit_callback)
- Raises: DomainExceptions only

Security:
- TOTP secrets encrypted at rest with Fernet
- Backup codes stored as bcrypt hashes (NOT reversible)
- Temporary setup secrets stored in Redis (TTL 10min) to avoid orphaned DB data
- All operations emit structured audit logs
"""

import base64
import io
import json
import secrets
import time
from typing import List, Optional, Tuple

import pyotp
import qrcode
import structlog
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import BusinessRuleViolation, InvalidCredentials

log = structlog.get_logger(__name__)

# Reuse bcrypt context from security module for backup codes
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# =============================================================================
# TOTP HELPERS
# =============================================================================

def generate_totp_secret() -> str:
    """Generate a new base32-encoded TOTP secret."""
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, username: str, issuer: str = "QLTS") -> str:
    """Generate otpauth:// URI for QR code scanning."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_code_base64(uri: str) -> str:
    """Generate QR code as base64 data URI from provisioning URI."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code with +-1 time window (no replay protection)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def verify_totp_with_counter(secret: str, code: str) -> Tuple[bool, Optional[int]]:
    """
    Verify TOTP code and return the matched time counter.

    Returns:
        (is_valid, matched_counter): counter is the TOTP time step that matched.
        Used for replay protection (RFC 6238 Section 5.2).
    """
    totp = pyotp.TOTP(secret)
    current_counter = totp.timecode(time.time())

    for offset in [-1, 0, 1]:  # valid_window=1
        counter = current_counter + offset
        if totp.generate_otp(counter) == code:
            return True, counter

    return False, None


# =============================================================================
# ENCRYPTION (TOTP secret only)
# =============================================================================

def _get_fernet() -> Fernet:
    """Get Fernet instance for TOTP secret encryption."""
    key = settings.MFA_ENCRYPTION_KEY
    if not key:
        raise BusinessRuleViolation(
            detail="MFA encryption key not configured. Set MFA_ENCRYPTION_KEY in environment."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt TOTP secret using Fernet symmetric encryption."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt TOTP secret using Fernet symmetric encryption."""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except FernetInvalidToken:
        raise BusinessRuleViolation(detail="Failed to decrypt MFA secret. Key may have changed.")


# =============================================================================
# BACKUP CODES (bcrypt hashed - NOT reversible)
# =============================================================================

def generate_backup_codes(count: int = 8) -> Tuple[List[str], List[str]]:
    """
    Generate backup codes and their bcrypt hashes.

    Returns:
        (plaintext_codes, bcrypt_hashes): Plaintext shown once to user, hashes stored in DB.
    """
    plaintext_codes = [secrets.token_hex(4) for _ in range(count)]  # 8 hex chars each
    bcrypt_hashes = [_pwd_context.hash(code) for code in plaintext_codes]
    return plaintext_codes, bcrypt_hashes


def verify_backup_code(
    input_code: str, hashed_codes_json: str
) -> Tuple[bool, str]:
    """
    Verify input against bcrypt backup code hashes.

    Returns:
        (matched, updated_hashes_json): If matched, the used hash is removed.
    """
    if not hashed_codes_json:
        return False, hashed_codes_json

    hashes = json.loads(hashed_codes_json)
    for i, h in enumerate(hashes):
        if _pwd_context.verify(input_code, h):
            # Consume the used backup code
            remaining = hashes[:i] + hashes[i + 1:]
            return True, json.dumps(remaining)

    return False, hashed_codes_json


# =============================================================================
# BUSINESS LOGIC (service pattern)
# =============================================================================

async def setup_mfa(
    user_id: int, username: str
) -> Tuple[dict, Optional[callable]]:
    """
    Initiate MFA setup: generate TOTP secret + QR code.
    Secret is stored temporarily in Redis (TTL 10min), NOT in DB.

    Returns:
        (setup_data, None): QR code + secret for display.
    """
    secret = generate_totp_secret()
    uri = get_provisioning_uri(secret, username)
    qr_code = generate_qr_code_base64(uri)

    # Store in Redis temporarily (avoids orphaned secrets in DB)
    redis_key = f"mfa_setup:{user_id}"
    ttl = settings.MFA_ATTEMPT_WINDOW_MINUTES * 2 * 60  # 10 min default
    await safe_redis_set(redis_key, secret, ex=ttl)

    log.info("mfa_setup_initiated", user_id=user_id, action="mfa.setup")

    return {
        "secret": secret,
        "qr_code": qr_code,
        "provisioning_uri": uri,
    }, None


async def enable_mfa(
    db: AsyncSession,
    user,  # models.User
    code: str,
    current_session_id: Optional[int] = None,
) -> Tuple[List[str], Optional[callable]]:
    """
    Enable MFA after verifying TOTP code.

    Steps:
    1. Read temp secret from Redis
    2. Verify TOTP code
    3. Encrypt secret → write to DB
    4. Generate backup codes → store bcrypt hashes
    5. Revoke all other sessions
    6. Return plaintext backup codes (shown once)
    """
    from . import session_service

    # 1. Read temp secret from Redis
    redis_key = f"mfa_setup:{user.id}"
    secret = await safe_redis_get(redis_key)
    if not secret:
        raise BusinessRuleViolation(
            detail="MFA setup session expired. Please start setup again."
        )

    # 2. Verify TOTP code
    if not verify_totp(secret, code):
        log.warning("mfa_enable_failed", user_id=user.id, action="mfa.enable_failed",
                     reason="invalid_totp_code")
        raise InvalidCredentials(detail="Invalid verification code. Please try again.")

    # 3. Encrypt and store secret
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.mfa_enabled = True

    # 4. Generate backup codes
    plaintext_codes, bcrypt_hashes = generate_backup_codes()
    user.backup_codes_hashed = json.dumps(bcrypt_hashes)

    db.add(user)
    await db.flush()

    # 5. Delete Redis temp key
    await safe_redis_delete(redis_key)

    # 6. Revoke all other sessions (security: kick potential attackers)
    revoked_count = 0
    session_callback = None
    if current_session_id:
        revoked_count, session_callback = await session_service.revoke_all_other_sessions(
            db=db,
            user_id=user.id,
            except_session_id=current_session_id,
        )

    log.info(
        "mfa_enabled", user_id=user.id, action="mfa.enable",
        sessions_revoked=revoked_count,
    )

    async def post_commit():
        if session_callback:
            await session_callback()

    return plaintext_codes, post_commit


async def disable_mfa(
    db: AsyncSession,
    user,  # models.User
    password: str,
) -> Tuple[bool, Optional[callable]]:
    """
    Disable MFA after password verification.
    Clears TOTP secret and backup codes from DB.
    """
    from ..security import verify_password

    if not verify_password(password, user.password_hash):
        log.warning("mfa_disable_failed", user_id=user.id, action="mfa.disable_failed",
                     reason="invalid_password")
        raise InvalidCredentials(detail="Invalid password.")

    user.mfa_enabled = False
    user.totp_secret_encrypted = None
    user.backup_codes_hashed = None
    db.add(user)
    await db.flush()

    log.info("mfa_disabled", user_id=user.id, action="mfa.disable")

    return True, None


async def verify_mfa_code(
    db: AsyncSession,
    user,  # models.User
    code: str,
) -> bool:
    """
    Verify MFA code (TOTP or backup code).
    If backup code is used, it is consumed (removed from hash list).
    """
    if not user.totp_secret_encrypted:
        log.warning("mfa_verify_no_secret", user_id=user.id, action="mfa.verify_failed")
        return False

    secret = decrypt_secret(user.totp_secret_encrypted)

    # Try TOTP first (6-digit codes)
    if len(code) == 6 and code.isdigit():
        is_valid, matched_counter = verify_totp_with_counter(secret, code)

        if is_valid and matched_counter is not None:
            # Replay protection (RFC 6238 §5.2): reject if this time step already used
            replay_key = f"totp_used:{user.id}"
            last_counter_str = await safe_redis_get(replay_key)

            if last_counter_str and int(last_counter_str) >= matched_counter:
                log.warning(
                    "totp_replay_rejected", user_id=user.id,
                    action="mfa.replay_rejected", matched_counter=matched_counter,
                )
                # Fall through to backup codes / fail (do NOT return True)
            else:
                # Accept and record this counter (TTL 180s covers 3 valid_window cycles)
                await safe_redis_set(replay_key, str(matched_counter), ex=180)
                log.info("mfa_verified", user_id=user.id, method="totp", action="mfa.verify_success")
                return True

    # Try backup codes (8 hex char codes)
    if user.backup_codes_hashed:
        matched, updated_json = verify_backup_code(code, user.backup_codes_hashed)
        if matched:
            user.backup_codes_hashed = updated_json
            db.add(user)
            await db.flush()

            remaining = len(json.loads(updated_json)) if updated_json else 0
            log.info(
                "backup_code_used", user_id=user.id, remaining_codes=remaining,
                action="mfa.backup_used",
            )
            return True

    log.warning(
        "mfa_failed", user_id=user.id, action="mfa.verify_failed",
        code_len=len(code), code_is_digit=code.isdigit(),
    )
    return False


async def regenerate_backup_codes(
    db: AsyncSession,
    user,  # models.User
    password: str,
) -> Tuple[List[str], Optional[callable]]:
    """
    Generate new backup codes (invalidates all old ones).
    Requires password verification.
    """
    from ..security import verify_password

    if not verify_password(password, user.password_hash):
        raise InvalidCredentials(detail="Invalid password.")

    if not user.mfa_enabled:
        raise BusinessRuleViolation(detail="MFA is not enabled.")

    plaintext_codes, bcrypt_hashes = generate_backup_codes()
    user.backup_codes_hashed = json.dumps(bcrypt_hashes)
    db.add(user)
    await db.flush()

    log.info("backup_codes_regenerated", user_id=user.id, action="mfa.backup_regen")

    return plaintext_codes, None


def create_mfa_token(username: str, user_id: int) -> str:
    """
    Create a short-lived JWT token for MFA challenge.
    Type="mfa" to distinguish from access/refresh tokens.
    """
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.MFA_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": username,
        "user_id": user_id,
        "type": "mfa",
        "exp": expire,
        "jti": secrets.token_urlsafe(16),
    }
    return jose_jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_mfa_token(token: str) -> dict:
    """
    Decode and validate MFA token. Rejects non-mfa tokens.

    Returns:
        Decoded payload dict with sub, user_id, type.

    Raises:
        InvalidCredentials if token is invalid, expired, or wrong type.
    """
    from jose import jwt as jose_jwt, JWTError, ExpiredSignatureError

    try:
        payload = jose_jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except ExpiredSignatureError:
        raise InvalidCredentials(detail="MFA verification session expired. Please login again.")
    except JWTError:
        raise InvalidCredentials(detail="Invalid MFA token.")

    if payload.get("type") != "mfa":
        raise InvalidCredentials(detail="Invalid token type.")

    return payload
