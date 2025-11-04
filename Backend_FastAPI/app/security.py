# app/security.py
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_password_reset_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=30
    )
    to_encode = {"exp": expire, "sub": email, "scope": "password_reset"}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("scope") != "password_reset":
            return None
        email: str = payload.get("sub")
        return email
    except JWTError:
        return None


# 2. Các hàm xử lý JWT

# ✅ BƯỚC 1: SỬA HÀM NÀY
def create_access_token(
    data: dict, refresh_jti: str, expires_delta: timedelta | None = None
) -> str:
    """Tạo Access Token, GẮN KÈM Refresh JTI (r_jti)"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid.uuid4()),  # JTI của riêng Access Token
            "type": "access",
            "r_jti": refresh_jti,  # ✅ JTI của Refresh Token (để liên kết)
        }
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        }
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token_for_invalidation(token: str) -> tuple[str | None, int | None]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        exp = payload.get("exp")

        remaining_ttl = None
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            remaining_ttl = max(0, int(exp - now))

        return jti, remaining_ttl
    except JWTError:
        return None, None

# ✅ HÀM MỚI: Dùng để decode Access Token trong deps.py
def decode_token(token: str) -> dict:
    """Giải mã token và trả về payload."""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        raise InvalidToken(detail=f"Invalid token: {e}")