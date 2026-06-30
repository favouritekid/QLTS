# app/utils/sms_token.py
"""
SMS short-link token (PR-3): base62×9 bearer code + HMAC hash (lookup) +
Fernet ciphertext (re-export). KHÔNG bao giờ lưu/log raw code — chỉ trả về
trong memory lúc build/export. Xem SMS_MARKETING_MODULE_DESIGN.md §6.

Key lifecycle: prod BẮT BUỘC cấu hình `SMS_TOKEN_ENCRYPTION_KEYS` (JSON
keyring) + `SMS_TOKEN_ACTIVE_KEY_VERSION`; thiếu → raise tại thời điểm build
(lazy, KHÔNG fail-fast startup để không gãy prod khi SMS chưa dùng). Dev/test
dẫn xuất 1 key ổn định từ hash secret → chạy được không cần env.
"""
import base64
import hashlib
import hmac
import json
import secrets
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

# Sentinel cố định cho {link} trong rendered_message_skeleton (KHÔNG raw code).
LINK_SENTINEL = "__SMS_LINK__"

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CODE_LENGTH = 9

# Default công khai — prod KHÔNG được dùng (token_hash sẽ đoán được).
_DEV_HASH_DEFAULT = "dev-sms-token-hash-secret-change-in-prod"
_DEV_IP_HASH_DEFAULT = "dev-sms-ip-hash-secret-change-in-prod"


def generate_short_code() -> str:
    """Sinh bearer code base62×9 (~54 bit) bằng secrets (CSPRNG)."""
    return "".join(secrets.choice(_BASE62) for _ in range(CODE_LENGTH))


def compute_token_hash(code: str) -> str:
    """HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET) → hex 64 ký tự [0-9a-f]
    (khớp CHECK `chk_sms_recipient_token_triplet`). Dùng để lookup /r/{code}."""
    secret = settings.SMS_TOKEN_HASH_SECRET.encode()
    return hmac.new(secret, code.encode(), hashlib.sha256).hexdigest()


def compute_ip_hash(ip: Optional[str]) -> Optional[str]:
    """HMAC-SHA256(ip, SMS_IP_HASH_SECRET) → hex 64 (click event PR-5). Secret
    TÁCH BIỆT token-hash (§2.2) → không suy ngược token↔IP. KHÔNG lưu IP thô.
    None nếu ip rỗng."""
    raw = (ip or "").strip()
    if not raw:
        return None
    secret = settings.SMS_IP_HASH_SECRET.encode()
    return hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()


def is_valid_code(code: str) -> bool:
    """Validate charset/length TRƯỚC khi chạm DB (§6.1) — base62 × 9 đúng
    `CODE_LENGTH`. Chặn path lạ/inject trước lookup."""
    return (
        isinstance(code, str)
        and len(code) == CODE_LENGTH
        and all(c in _BASE62 for c in code)
    )


def _load_keyring() -> Tuple[Dict[str, str], str]:
    """Trả (keyring {version: fernet_key}, active_version).

    Prod: bắt buộc cấu hình thật (raise nếu thiếu/sai — lazy). Dev/test:
    dẫn xuất 1 Fernet key ổn định từ hash secret nếu chưa cấu hình.
    """
    raw = (settings.SMS_TOKEN_ENCRYPTION_KEYS or "").strip()
    active = (settings.SMS_TOKEN_ACTIVE_KEY_VERSION or "").strip()
    if raw:
        try:
            keyring = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "SMS_TOKEN_ENCRYPTION_KEYS không phải JSON hợp lệ"
            ) from exc
        if not isinstance(keyring, dict) or not keyring:
            raise RuntimeError(
                "SMS_TOKEN_ENCRYPTION_KEYS phải là object {version: key}"
            )
        if not active:
            raise RuntimeError("SMS_TOKEN_ACTIVE_KEY_VERSION chưa được set")
        if active not in keyring:
            raise RuntimeError(
                f"SMS_TOKEN_ACTIVE_KEY_VERSION '{active}' không có trong keyring"
            )
        return keyring, active

    if settings.APP_ENV == "production":
        raise RuntimeError(
            "SMS token encryption chưa cấu hình (SMS_TOKEN_ENCRYPTION_KEYS + "
            "SMS_TOKEN_ACTIVE_KEY_VERSION) — bắt buộc trong production để build "
            "campaign có {link}."
        )
    # Dev/test: 1 Fernet key ổn định (32 byte → urlsafe-b64) từ hash secret.
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(
            ("sms-dev-fernet::" + settings.SMS_TOKEN_HASH_SECRET).encode()
        ).digest()
    ).decode()
    return {"dev": derived}, "dev"


def ensure_token_secrets_configured() -> None:
    """Lazy gate gọi lúc BUILD campaign có {link}. Prod BẮT BUỘC:
    `SMS_TOKEN_HASH_SECRET` thật (≠ default công khai, ≥32 ký tự) + Fernet
    keyring hợp lệ. KHÔNG fail-fast startup (tránh gãy prod chưa dùng SMS)."""
    if settings.APP_ENV == "production":
        secret = settings.SMS_TOKEN_HASH_SECRET or ""
        if secret == _DEV_HASH_DEFAULT or len(secret) < 32:
            raise RuntimeError(
                "SMS_TOKEN_HASH_SECRET chưa cấu hình mạnh (≥32 ký tự, KHÔNG "
                "dùng default công khai) — bắt buộc trong production để build "
                "campaign có {link}."
            )
        # IP-hash secret (PR-5 click) — link campaign SẼ bị click → fail-closed.
        ip_secret = settings.SMS_IP_HASH_SECRET or ""
        if ip_secret == _DEV_IP_HASH_DEFAULT or len(ip_secret) < 32:
            raise RuntimeError(
                "SMS_IP_HASH_SECRET chưa cấu hình mạnh (≥32 ký tự, KHÔNG dùng "
                "default công khai) — bắt buộc trong production (hash IP click)."
            )
        # Bearer link base: phải https + host thuộc allowlist (chống link trỏ
        # domain lạ xuất hiện trong tin/preview).
        parsed = urlparse((settings.SMS_PUBLIC_BASE_URL or "").strip())
        host = (parsed.hostname or "").lower()
        allowed = [
            d.strip().lower()
            for d in settings.SMS_ALLOWED_REDIRECT_DOMAINS.split(",")
            if d.strip()
        ]
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not any(host == d or host.endswith("." + d) for d in allowed)
        ):
            raise RuntimeError(
                "SMS_PUBLIC_BASE_URL phải https + host thuộc "
                "SMS_ALLOWED_REDIRECT_DOMAINS, KHÔNG userinfo/query/fragment "
                "(tránh URL link sai như https://host?x=1/r/code) trong "
                "production."
            )
    # _load_keyring raise nếu keyring thiếu/JSON sai (prod). Thêm: KHỞI TẠO
    # Fernet cho MỌI key → bắt key sai định dạng (32 url-safe base64) ngay
    # tại gate, thay vì văng giữa build lúc encrypt. #4 R3.
    keyring, _active = _load_keyring()
    for ver, key in keyring.items():
        # Version lưu vào cột token_key_version VARCHAR(32) — dài hơn → 500
        # StringDataRightTruncation lúc insert recipient. Chặn tại gate. #3 R5.
        if len(ver) > 32:
            raise RuntimeError(
                f"SMS_TOKEN version '{ver[:12]}…' quá dài (≤32 ký tự — khớp "
                "cột token_key_version VARCHAR(32))."
            )
        # key phải là CHUỖI (JSON có thể là số/obj → .encode() AttributeError).
        if not isinstance(key, str):
            raise RuntimeError(
                f"SMS_TOKEN_ENCRYPTION_KEYS['{ver}'] phải là chuỗi Fernet key."
            )
        try:
            Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"SMS_TOKEN_ENCRYPTION_KEYS['{ver}'] không phải Fernet key "
                "hợp lệ (32 url-safe base64 bytes)."
            ) from exc


def encrypt_code(code: str) -> Tuple[str, str]:
    """Trả (ciphertext, key_version). Fernet active key trong keyring."""
    keyring, active = _load_keyring()
    cipher = Fernet(keyring[active].encode())
    return cipher.encrypt(code.encode()).decode(), active


def decrypt_code(ciphertext: str, key_version: str) -> Optional[str]:
    """Giải mã code (re-export PR-4). None nếu version/key sai hoặc hỏng."""
    keyring, _ = _load_keyring()
    key = keyring.get(key_version)
    # key có thể không phải chuỗi (keyring JSON dạng số) → .encode() sẽ
    # AttributeError. Trả None theo contract thay vì 500 lúc export.
    if not key or not isinstance(key, str):
        return None
    try:
        return Fernet(key.encode()).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


def build_link(code: str) -> str:
    """URL public của bearer link: {SMS_PUBLIC_BASE_URL}/r/{code}."""
    base = settings.SMS_PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/r/{code}"


def link_placeholder_length() -> int:
    """Độ dài URL link (cố định vì code base62×9) — để preflight đo TIN CUỐI
    bằng cách thay sentinel bằng chuỗi cùng độ dài."""
    return len(build_link("X" * CODE_LENGTH))
