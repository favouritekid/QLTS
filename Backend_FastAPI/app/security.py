# app/security.py
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional  # Giữ lại Optional

# Bỏ import Depends, HTTPException, status, OAuth2PasswordBearer, AsyncSession
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

# Bỏ import database, models, services

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_password_reset_token(email: str) -> str:
    """Tạo một token đặc biệt để reset mật khẩu, có thời hạn ngắn."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=30
    )  # Token chỉ hiệu lực 30 phút
    to_encode = {"exp": expire, "sub": email, "scope": "password_reset"}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> Optional[str]:
    """Giải mã và xác thực token reset mật khẩu."""
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
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    # Thêm jti và type
    to_encode.update(
        {"exp": expire, "jti": str(uuid.uuid4()), "type": "access"}  # Thêm type
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

    # Thêm jti và type
    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid.uuid4()),  # Refresh token cũng cần JTI
            "type": "refresh",  # Thêm type
        }
    )
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


# Hàm helper để lấy JTI và thời gian hết hạn từ token
def decode_token_for_invalidation(token: str) -> tuple[str | None, int | None]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_exp": False
            },  # Bỏ qua kiểm tra hết hạn khi decode để lấy jti
        )
        jti = payload.get("jti")
        exp = payload.get("exp")

        # Tính thời gian còn lại (TTL) cho Redis blacklist
        remaining_ttl = None
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            remaining_ttl = max(0, int(exp - now))  # TTL không âm

        return jti, remaining_ttl
    except JWTError:
        return None, None
