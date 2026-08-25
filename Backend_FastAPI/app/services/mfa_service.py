# app/services/mfa_service.py
"""
MFA (Multi-Factor Authentication) Service - TOTP-based.

Pure Python service (no FastAPI imports). Follows service isolation pattern:
- Input: Pydantic models / primitives
- Output: Tuple (result, post_commit_callback)
- Raises: DomainExceptions only

Security:
- TOTP secrets encrypted at rest with Fernet
- Backup codes: selector HMAC có khoá + bcrypt verifier (storage v2)
- Temporary setup secrets stored in Redis (TTL 10min) to avoid orphaned DB data
- All operations emit structured audit logs
"""

import asyncio
import base64
import hashlib
import hmac
import io
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pyotp
import qrcode
import structlog
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken
from passlib.context import CryptContext
from sqlalchemy.exc import InvalidRequestError as SQLAlchemyInvalidRequest
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import (
    safe_redis_consume_totp_counter,
    safe_redis_delete,
    safe_redis_get,
    safe_redis_set,
)
# Context mật khẩu dùng chung (rounds=15) — CHỈ còn dùng cho backup code
# LEGACY. Mã v2 dùng context riêng, xem ``_backup_context()``.
from ..security import pwd_context as _pwd_context
from ..utils.exceptions import BusinessRuleViolation, InvalidCredentials

log = structlog.get_logger(__name__)


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
    current_counter = totp.timecode(datetime.now(timezone.utc))

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
# BACKUP CODES — storage v2 (HMAC selector + bcrypt verifier)
# =============================================================================
#
# ⚠️ Vì sao đổi: bản trước lưu ``json.dumps(list[bcrypt_hash])`` và xác minh
# bằng cách quét TUYẾN TÍNH, bcrypt từng mục, với CHÍNH context mật khẩu
# (rounds=15). Đo trong container: một phép bcrypt-15 = 1,77s, nên một mã sai
# = 8 × 1,77 ≈ 14,1s CPU **và chặn event loop**. Tệ hơn: ``verify_mfa_code``
# thử TOTP trước rồi RƠI XUỐNG backup, nên cả một mã TOTP 6 số gõ nhầm cũng
# trả giá đầy đủ. Đó là khuếch đại CPU, không phải test chậm.
#
# Mô hình v2, mỗi mục là một dict trong CÙNG cột Text (không cần migration):
#
#     {"v": 2, "sel": "<hex>", "vfy": "<bcrypt hash>"}
#
#   * ``sel`` = HMAC-SHA256(pepper, code) — CÓ KHOÁ. Dùng để chọn ĐÚNG MỘT
#     candidate. Không có pepper thì người đọc được DB vẫn không precompute
#     được bảng tra cho không gian 40-bit của mã.
#   * ``vfy`` = bcrypt của chính mã. Selector CHỈ để chọn; bí mật vẫn do bcrypt
#     xác minh. Không dùng fast hash trần cho mã keyspace nhỏ.
#
# Chi phí sau khi đổi:
#   mã sai hình dạng      → 0 bcrypt
#   TOTP 6 số sai         → 0 bcrypt backup
#   selector không khớp   → 0 bcrypt
#   selector khớp         → ĐÚNG 1 bcrypt
#
# Top level vẫn là JSON **list** chứ không phải envelope ``{"v":2,"codes":[…]}``
# có chủ đích: hợp đồng hiện hữu mà ``TestBackupCodes`` khoá là
# ``len(json.loads(updated))`` giảm đúng 1. Version nằm ở TỪNG mục, nên một
# danh sách trộn legacy + v2 vẫn biểu diễn được — cần thiết vì mã legacy đang
# phát hành KHÔNG bị vô hiệu.

_BACKUP_CODE_BYTES = 5          # secrets.token_hex(5) → 10 ký tự hex
_BACKUP_CODE_LEN = 10
_BACKUP_CODE_ALPHABET = set("0123456789abcdef")
_TOTP_CODE_LEN = 6

CODE_SHAPE_TOTP = "totp"
CODE_SHAPE_BACKUP = "backup"
CODE_SHAPE_INVALID = "invalid"

# Hạn của khoá chống phát lại TOTP. 180s phủ trọn ba chu kỳ 30s của
# ``valid_window=1`` (bước -1, 0, +1) cộng dư ra cho lệch đồng hồ — sau ngần ấy
# thời gian thì mọi bước đã tiêu đều đã rơi khỏi cửa sổ chấp nhận, nên giữ dấu
# vết thêm nữa không đổi được quyết định nào.
_TOTP_REPLAY_TTL_SECONDS = 180


def classify_code_shape(code: str) -> str:
    """Phân tuyến theo HÌNH DẠNG, trước mọi chi phí CPU.

    Đây là hàng rào đầu tiên: 6 chữ số chỉ đi đường TOTP, 10 hex thường chỉ đi
    đường backup, còn lại từ chối ngay. Không có nhánh nào "thử cái này rồi rơi
    xuống cái kia" — chính cú rơi ấy là thứ biến một mã TOTP gõ nhầm thành 8
    phép bcrypt.
    """
    if not isinstance(code, str):
        return CODE_SHAPE_INVALID
    if len(code) == _TOTP_CODE_LEN and code.isdigit():
        return CODE_SHAPE_TOTP
    if len(code) == _BACKUP_CODE_LEN and all(c in _BACKUP_CODE_ALPHABET for c in code):
        return CODE_SHAPE_BACKUP
    return CODE_SHAPE_INVALID


def _get_backup_pepper() -> bytes:
    """Pepper cho selector. Thiếu hoặc rỗng ⇒ FAIL CLOSED.

    Cùng khuôn với ``_get_fernet``: bí mật bắt buộc, không default yếu. Cấu
    hình production còn chặn ở startup (``config.py``) để lỗi thiếu env không
    biến thành "không ai dùng được backup code" phát hiện lúc 2 giờ sáng.
    """
    pepper = getattr(settings, "MFA_BACKUP_CODE_PEPPER", "") or ""
    if not pepper:
        raise BusinessRuleViolation(
            detail=(
                "MFA backup code pepper not configured. "
                "Set MFA_BACKUP_CODE_PEPPER in environment."
            )
        )
    return pepper.encode() if isinstance(pepper, str) else pepper


def _selector(code: str) -> str:
    """HMAC-SHA256(pepper, code) → hex. Rẻ, có khoá, dùng để CHỌN candidate."""
    return hmac.new(_get_backup_pepper(), code.encode(), hashlib.sha256).hexdigest()


def _backup_context() -> CryptContext:
    """Context bcrypt RIÊNG cho backup code.

    KHÔNG dùng chung với mật khẩu: mã backup là 40-bit ngẫu nhiên đều do hệ
    sinh, không phải bí mật người chọn, nên không cần work factor của mật khẩu.
    Global password rounds=15 giữ NGUYÊN trong PR này.
    """
    global _backup_ctx_cache
    rounds = int(getattr(settings, "MFA_BACKUP_CODE_BCRYPT_ROUNDS", 12))
    if _backup_ctx_cache is None or _backup_ctx_cache[0] != rounds:
        _backup_ctx_cache = (
            rounds,
            CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=rounds),
        )
    return _backup_ctx_cache[1]


_backup_ctx_cache: Optional[Tuple[int, CryptContext]] = None


# --- Resource governor: bcrypt KHÔNG được chạy trên event loop ---------------
#
# bcrypt là CPU-bound và đồng bộ. Chạy thẳng trong coroutine thì nó chặn event
# loop: mọi request khác của cùng worker đứng im suốt thời gian đó. Ném vào
# default executor cũng sai — hàng đợi mặc định rộng (min(32, cpu+4)), nên tải
# đồng thời biến thành bấy nhiêu suất CPU.
#
# Ở đây: một pool CÓ TRẦN, cộng một semaphore để phần vượt trần XẾP HÀNG thay
# vì nhân bản.
_bcrypt_executor: Optional[ThreadPoolExecutor] = None
_bcrypt_gate: Optional[asyncio.Semaphore] = None
_bcrypt_gate_loop = None


def _max_bcrypt_workers() -> int:
    return max(1, int(getattr(settings, "MFA_BCRYPT_MAX_WORKERS", 2)))


def _get_bcrypt_executor() -> ThreadPoolExecutor:
    global _bcrypt_executor
    if _bcrypt_executor is None:
        _bcrypt_executor = ThreadPoolExecutor(
            max_workers=_max_bcrypt_workers(),
            thread_name_prefix="mfa-bcrypt",
        )
    return _bcrypt_executor


def _get_bcrypt_gate() -> asyncio.Semaphore:
    """Semaphore gắn với event loop hiện tại.

    Test suite dựng loop mới cho mỗi ca, và một ``asyncio.Semaphore`` tạo ở
    loop khác sẽ hỏng khi await. Nên gắn theo loop thay vì cache toàn cục mù.
    """
    global _bcrypt_gate, _bcrypt_gate_loop
    loop = asyncio.get_running_loop()
    if _bcrypt_gate is None or _bcrypt_gate_loop is not loop:
        _bcrypt_gate = asyncio.Semaphore(_max_bcrypt_workers())
        _bcrypt_gate_loop = loop
    return _bcrypt_gate


async def _run_bcrypt(fn, *args):
    """Chạy một phép bcrypt NGOÀI event loop, dưới trần tài nguyên."""
    async with _get_bcrypt_gate():
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_get_bcrypt_executor(), fn, *args)


# --- Sinh mã -----------------------------------------------------------------

def _build_v2_entry(code: str) -> dict:
    return {
        "v": 2,
        "sel": _selector(code),
        "vfy": _backup_context().hash(code),
    }


def v2_writer_enabled() -> bool:
    """Pha B đã bật chưa?

    Đọc ``settings`` ở mỗi lần gọi để test monkeypatch được — ĐỪNG đọc thành
    "đổi cờ lúc chạy". ``settings`` là singleton dựng MỘT LẦN lúc import; sửa
    ``.env.production`` KHÔNG chạm được tiến trình đang chạy. Bật pha B là một
    thao tác deploy: đổi env rồi **dựng lại** các service đọc Settings
    (backend + celery-worker + celery-beat) — ``restart`` không nạp lại
    ``env_file``. Xem Documents/PRODUCTION_DEPLOY_GUIDE.md §"Bật pha B".
    """
    return bool(getattr(settings, "MFA_BACKUP_CODE_V2_WRITER_ENABLED", False))


def generate_backup_codes(count: int = 8) -> Tuple[List[str], List]:
    """Sinh backup code + mục lưu trữ, theo PHA TRIỂN KHAI đang bật.

    Giữ nguyên chữ ký đồng bộ vì ``TestBackupCodes`` gọi trực tiếp. Đường
    service dùng ``agenerate_backup_codes`` để không chặn event loop.

    Hai định dạng ghi:

      * Pha A (mặc định, cờ TẮT) → ``list[str]`` bcrypt — ĐÚNG định dạng ảnh
        cũ đọc được. Rollback không làm chết mã vừa phát. Vẫn rẻ hơn bản cũ
        tám lần vì băm bằng ``MFA_BACKUP_CODE_BCRYPT_ROUNDS`` (12) thay vì
        rounds mật khẩu (15); chuỗi bcrypt tự mang tham số chi phí nên ảnh cũ
        xác minh bình thường.
      * Pha B (cờ BẬT) → ``list[dict]`` v2 có selector, cắt hẳn quét O(n).

    Đọc thì luôn hiểu cả hai — xem ``verify_backup_code``.

    Returns:
        (plaintext_codes, entries): plaintext hiện MỘT LẦN cho người dùng;
        ``entries`` ``json.dumps`` được ở cả hai pha.
    """
    plaintext_codes = [
        secrets.token_hex(_BACKUP_CODE_BYTES) for _ in range(count)
    ]  # 10 ký tự hex, 40-bit entropy — GIỮ NGUYÊN định dạng người dùng thấy
    if v2_writer_enabled():
        entries = [_build_v2_entry(code) for code in plaintext_codes]
    else:
        ctx = _backup_context()
        entries = [ctx.hash(code) for code in plaintext_codes]
    return plaintext_codes, entries


async def agenerate_backup_codes(count: int = 8) -> Tuple[List[str], List]:
    """Bản async: 8 phép bcrypt chạy ngoài event loop.

    Bản trước gọi thẳng ``_pwd_context.hash`` 8 lần trong coroutine, tức
    enable/regenerate chặn event loop ~14s TRƯỚC cả bước xác minh.
    """
    return await _run_bcrypt(generate_backup_codes, count)


# --- Xác minh ----------------------------------------------------------------

def _load_entries(hashed_codes_json: str) -> List:
    if not hashed_codes_json:
        return []
    try:
        loaded = json.loads(hashed_codes_json)
    except (ValueError, TypeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _is_v2(entry) -> bool:
    return isinstance(entry, dict) and entry.get("v") == 2


def _match_v2_index(entries: List, code: str) -> Optional[int]:
    """Chỉ số của mục v2 có selector khớp — hoặc None. KHÔNG chạy bcrypt.

    So sánh bằng ``compare_digest`` để không rò rỉ vị trí khớp qua thời gian.
    """
    # Kho KHÔNG có mục v2 nào (pha A, hoặc dữ liệu cũ) thì selector vô nghĩa —
    # và quan trọng hơn: không được đòi pepper ở một triển khai chưa dùng v2.
    # Thiếu pepper mà kho CÓ v2 thì vẫn fail closed ngay dòng dưới.
    if not any(_is_v2(e) for e in entries):
        return None

    want = _selector(code)
    for i, entry in enumerate(entries):
        if _is_v2(entry) and hmac.compare_digest(str(entry.get("sel", "")), want):
            return i
    return None


def verify_backup_code(input_code: str, hashed_codes_json: str) -> Tuple[bool, str]:
    """Xác minh backup code. Đồng bộ — giữ hợp đồng cho unit test hiện hữu.

    Chi phí bcrypt:
      * sai hình dạng            → 0
      * v2, selector không khớp  → 0
      * v2, selector khớp        → đúng 1
      * legacy (list[str])       → quét, nhưng CHỈ khi hình dạng đúng 10-hex

    Returns:
        (matched, updated_json): khớp thì mục đã dùng bị gỡ khỏi danh sách.
    """
    entries = _load_entries(hashed_codes_json)
    if not entries:
        return False, hashed_codes_json

    # Hàng rào hình dạng: mã không thể là backup code thì không tốn CPU nào.
    if classify_code_shape(input_code) != CODE_SHAPE_BACKUP:
        return False, hashed_codes_json

    idx = _match_v2_index(entries, input_code)
    if idx is not None:
        # ĐÚNG MỘT phép bcrypt. Selector chỉ chọn; bí mật do bcrypt xác minh.
        if _backup_context().verify(input_code, entries[idx]["vfy"]):
            remaining = entries[:idx] + entries[idx + 1:]
            return True, json.dumps(remaining)
        # Selector khớp mà bcrypt không khớp: dữ liệu hỏng hoặc pepper đổi.
        # KHÔNG rơi xuống legacy-scan — nếu không thì mọi mã sai lại tốn O(n).
        return False, hashed_codes_json

    # --- Legacy: list[str] bcrypt của bản cũ ---------------------------------
    # Mã đang phát hành KHÔNG bị vô hiệu. Quét tuyến tính là cái giá của định
    # dạng cũ; nó bị chặn bởi cùng reservation/rate-limit và chạy ngoài event
    # loop qua ``averify_backup_code``.
    legacy_idx = None
    for i, entry in enumerate(entries):
        if isinstance(entry, str) and _pwd_context.verify(input_code, entry):
            legacy_idx = i
            break
    if legacy_idx is not None:
        remaining = entries[:legacy_idx] + entries[legacy_idx + 1:]
        return True, json.dumps(remaining)

    return False, hashed_codes_json


async def averify_backup_code(
    input_code: str, hashed_codes_json: str
) -> Tuple[bool, str]:
    """Bản async: mọi bcrypt chạy ngoài event loop, dưới trần tài nguyên.

    Nhánh 0-bcrypt (sai hình dạng / selector không khớp) vẫn đi qua executor
    nhưng không tốn CPU đáng kể; giữ một đường duy nhất để hành vi hai bản
    không phân kỳ.
    """
    return await _run_bcrypt(verify_backup_code, input_code, hashed_codes_json)


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

    # 4. Generate backup codes — NGOÀI event loop (8 phép bcrypt).
    plaintext_codes, entries = await agenerate_backup_codes()
    user.backup_codes_hashed = json.dumps(entries)

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
    """Xác minh mã MFA. Phân tuyến theo HÌNH DẠNG trước mọi chi phí CPU.

    ⚠️ Bản trước thử TOTP rồi **rơi xuống** backup code. Hệ quả đo được: một mã
    TOTP 6 số gõ nhầm vẫn quét tuyến tính 8 bcrypt-15 ≈ 14,1s CPU, chặn event
    loop. Nay ba đường tách hẳn:

        6 chữ số   → CHỈ TOTP.   Sai ⇒ trả False, KHÔNG chạm backup bcrypt.
        10 hex     → CHỈ backup. Selector chọn ĐÚNG MỘT candidate.
        còn lại    → từ chối ngay, 0 bcrypt.

    Backup code được tiêu thụ dưới ``SELECT … FOR UPDATE`` để hai request đồng
    thời dùng cùng một mã chỉ có ĐÚNG MỘT thành công.
    """
    if not user.totp_secret_encrypted:
        log.warning("mfa_verify_no_secret", user_id=user.id, action="mfa.verify_failed")
        return False

    shape = classify_code_shape(code)

    if shape == CODE_SHAPE_INVALID:
        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
            reason="bad_shape", code_len=len(code) if isinstance(code, str) else -1,
        )
        return False

    if shape == CODE_SHAPE_TOTP:
        secret = decrypt_secret(user.totp_secret_encrypted)
        is_valid, matched_counter = verify_totp_with_counter(secret, code)

        if is_valid and matched_counter is not None:
            # Chống phát lại (RFC 6238 §5.2) — TIÊU THỤ NGUYÊN TỬ.
            #
            # ⚠️ Bản trước: GET counter ở đây rồi mới SET sau khi so sánh. Hai
            # request đồng thời cùng dừng ở ``await`` của GET, cùng đọc trạng
            # thái cũ, cùng kết luận hợp lệ ⇒ MỘT mã TOTP đổi được HAI lần xác
            # minh (đo được ``[True, True]`` trên Redis thật). Và khi Redis
            # lỗi, ``safe_redis_get`` trả ``None`` ⇒ vế ``if last and …`` là
            # falsy ⇒ CHẤP NHẬN. Một lượt Redis chết làm bốc hơi im lặng cả
            # lớp bảo vệ.
            #
            # Nay: so-sánh-rồi-ghi nằm trọn trong một script server-side, và
            # mọi ca "không chứng minh được" đều TỪ CHỐI.
            replay_key = f"totp_used:{user.id}"
            tieu_thu = await safe_redis_consume_totp_counter(
                replay_key, matched_counter, _TOTP_REPLAY_TTL_SECONDS
            )

            if tieu_thu is None:
                # FAIL CLOSED. Không chứng minh được rằng bước thời gian này
                # chưa bị tiêu thì không được coi nó là chưa tiêu.
                log.error(
                    "totp_replay_guard_unavailable", user_id=user.id,
                    action="mfa.replay_guard_unavailable",
                )
                return False

            if not tieu_thu.accepted:
                log.warning(
                    "totp_replay_rejected", user_id=user.id,
                    action="mfa.replay_rejected", matched_counter=matched_counter,
                )
                # KHÔNG rơi xuống backup: một mã TOTP không bao giờ là backup code.
                return False

            log.info(
                "mfa_verified", user_id=user.id, method="totp",
                action="mfa.verify_success",
            )
            return True

        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
            reason="totp_mismatch",
        )
        return False

    # --- shape == CODE_SHAPE_BACKUP -----------------------------------------
    if not user.backup_codes_hashed:
        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
            reason="no_backup_codes",
        )
        return False

    # Khoá hàng TRƯỚC khi đọc danh sách: hai request đồng thời cùng một mã sẽ
    # nối đuôi nhau, request thứ hai đọc danh sách ĐÃ bị gỡ mục và trượt.
    # Không khoá thì cả hai đọc cùng snapshot và lost-update làm "sống lại" mã.
    locked_user = await _lock_user_row(db, user)
    stored = locked_user.backup_codes_hashed if locked_user is not None else None
    if not stored:
        return False

    matched, updated_json = await averify_backup_code(code, stored)
    if not matched:
        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
            reason="backup_mismatch",
        )
        return False

    locked_user.backup_codes_hashed = updated_json
    db.add(locked_user)
    await db.flush()          # Router commit — service chỉ flush.

    try:
        remaining = len(json.loads(updated_json)) if updated_json else 0
    except (ValueError, TypeError):
        remaining = 0
    log.info(
        "backup_code_used", user_id=user.id, remaining_codes=remaining,
        action="mfa.backup_used",
    )
    return True


async def _lock_user_row(db: AsyncSession, user):
    """``SELECT … FOR UPDATE`` trên đúng hàng user, ĐỌC LẠI từ đĩa.

    Khoá giữ tới lúc router commit, nên vùng đọc-sửa-ghi của backup code là
    tuần tự thật sự chứ không phải "hy vọng không trùng".

    ⚠️ Khoá thôi CHƯA ĐỦ, và đây là chỗ đã đo được sai. Một
    ``select(...).with_for_update()`` trả về đối tượng đã nằm sẵn trong
    identity map của session thì SQLAlchemy **giữ nguyên giá trị thuộc tính
    cũ** — hàng bị khoá đúng, nhưng ``backup_codes_hashed`` đọc ra vẫn là
    ảnh chụp TRƯỚC khi phiên kia commit. Đo thật: hai phiên dùng cùng một
    backup code đều trả ``True``, mã dùng-một-lần dùng được hai lần.

    ``Session.refresh(..., with_for_update=True)`` phát đúng câu
    ``SELECT … FOR UPDATE`` ấy **và** ghi đè thuộc tính bằng dữ liệu vừa đọc,
    nên phiên thứ hai thấy danh sách đã bị gỡ mục.
    """
    try:
        await db.refresh(user, with_for_update=True)
    except SQLAlchemyInvalidRequest:
        # Hàng biến mất giữa chừng (xoá đồng thời): coi như không có gì để tiêu.
        return None
    return user


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

    plaintext_codes, entries = await agenerate_backup_codes()
    user.backup_codes_hashed = json.dumps(entries)
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
    import jwt

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
    return jwt.encode(
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
    import jwt
    from jwt.exceptions import PyJWTError as JWTError, ExpiredSignatureError

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except ExpiredSignatureError:
        raise InvalidCredentials(detail="MFA verification session expired. Please login again.")
    except JWTError:
        raise InvalidCredentials(detail="Invalid MFA token.")

    if payload.get("type") != "mfa":
        raise InvalidCredentials(detail="Invalid token type.")

    return payload
