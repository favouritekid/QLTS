# app/config.py
import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import ConfigDict, Field  # Thêm Field

# XÓA: from dotenv import load_dotenv, find_dotenv
from pydantic_settings import BaseSettings

# --- Lấy APP_ENV sớm để xác định file .env ---
APP_ENV_FOR_CONFIG = os.getenv("APP_ENV", "development")
print(
    f"INFO [config.py]: Determining env file based on APP_ENV_FOR_CONFIG = {APP_ENV_FOR_CONFIG}"
)  # Log debug

_env_file = ".env.test" if APP_ENV_FOR_CONFIG == "test" else ".env"
# Xác định đường dẫn tuyệt đối đến file .env trong thư mục gốc dự án
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file_path = os.path.join(_project_root, _env_file)
print(
    f"INFO [config.py]: Pydantic-settings will attempt to load env_file: '{_env_file_path}'"
)
_env_file_exists = os.path.exists(_env_file_path)
print(f"INFO [config.py]: Does the determined env_file exist? {_env_file_exists}")

_AVATAR_UPLOAD_FOLDER = os.path.join(
    os.path.dirname(__file__), "static", "uploads", "avatars"
)
os.makedirs(_AVATAR_UPLOAD_FOLDER, exist_ok=True)

# # --- TÍNH TOÁN CÁC GIÁ TRỊ TRƯỚC (Giữ nguyên) ---
# _max_avatar_size_mb_env = os.getenv("MAX_AVATAR_SIZE_MB", "2")
# try:
#     _MAX_AVATAR_SIZE_MB = int(_max_avatar_size_mb_env)
# except ValueError:
#     _MAX_AVATAR_SIZE_MB = 2
# _MAX_AVATAR_CONTENT_LENGTH = _MAX_AVATAR_SIZE_MB * 1024 * 1024
# _AVATAR_UPLOAD_FOLDER = os.path.join(
#     os.path.dirname(__file__), "static", "uploads", "avatars"
# )
# os.makedirs(_AVATAR_UPLOAD_FOLDER, exist_ok=True)
# # --- KẾT THÚC TÍNH TOÁN TRƯỚC ---


# Default placeholder hướng dẫn từ chối (SMS/điện thoại) — prod PHẢI đặt
# kênh từ chối THẬT; build refuse nếu còn placeholder này trong production.
SMS_OPTOUT_INSTRUCTION_DEFAULT = (
    "Tu choi QC: soan TC gui 1900xxxx hoac goi 1900xxxx."
)


class Settings(BaseSettings):
    # Application Settings
    # Pydantic tự đọc APP_ENV từ môi trường
    APP_ENV: str = Field(default="development", validation_alias="APP_ENV")
    LOG_LEVEL: str = Field(default="DEBUG", validation_alias="LOG_LEVEL")
    # Các biến bắt buộc (không có default), phải có trong file .env hoặc môi trường
    SECRET_KEY: str
    DATABASE_URL: str
    JWT_SECRET_KEY: str

    # JWT Settings với default
    # ✅ SECURITY: Only allow safe JWT algorithms (reject "none" algorithm)
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512", "RS256", "RS384", "RS512"] = Field(
        default="HS256", validation_alias="JWT_ALGORITHM"
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=15, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: float = Field(
        default=30.0, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )  # Dùng float

    # Các URL với default
    FRONTEND_URL: str = Field(
        default="http://localhost:5173", validation_alias="FRONTEND_URL"
    )
    # PR1 Commit 5: canonical public base URL of THIS backend. Used to build
    # the MoMo IPN (server callback) URL instead of deriving it from the
    # client-supplied return_url. Prod fail-fast: https + non-localhost.
    PUBLIC_BACKEND_URL: str = Field(
        default="http://localhost:8000", validation_alias="PUBLIC_BACKEND_URL"
    )
    CORS_ORIGINS: str = Field(
        default="http://localhost:5173", validation_alias="CORS_ORIGINS"
    )  # Mặc định lấy từ FRONTEND_URL không hoạt động tốt với pydantic-settings, nên đặt giá trị mặc định rõ ràng

    # Mail Settings - Bắt buộc
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str
    # Mail Settings với default
    MAIL_PORT: int = Field(default=587, validation_alias="MAIL_PORT")
    MAIL_STARTTLS: bool = Field(default=True, validation_alias="MAIL_STARTTLS")
    MAIL_SSL_TLS: bool = Field(default=False, validation_alias="MAIL_SSL_TLS")

    # Redis Settings với default
    REDIS_URL: str = Field(
        default="redis://localhost:6379/1", validation_alias="REDIS_URL"
    )

    # Celery Settings với default
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/2", validation_alias="CELERY_BROKER_URL"
    )
    CELERY_RESULT_BACKEND_URL: str = Field(
        default="redis://localhost:6379/3", validation_alias="CELERY_RESULT_BACKEND_URL"
    )

    # Timezone Settings - có thể thay đổi tùy theo vị trí VPS
    # Ví dụ: "Asia/Ho_Chi_Minh", "Asia/Singapore", "Asia/Tokyo", "UTC"
    TIMEZONE: str = Field(
        default="Asia/Ho_Chi_Minh", validation_alias="TIMEZONE"
    )

    # -- File Uploads --
    # Pydantic-settings reads MAX_AVATAR_SIZE_MB from env first
    MAX_AVATAR_SIZE_MB: int = Field(default=2, validation_alias="MAX_AVATAR_SIZE_MB")
    # MAX_AVATAR_CONTENT_LENGTH sẽ được tính toán lại trong __init__
    MAX_AVATAR_CONTENT_LENGTH: int = 2 * 1024 * 1024  # Khởi tạo với giá trị mặc định

    ALLOWED_AVATAR_EXTENSIONS: List[str] = ["png", "jpg", "jpeg"]
    ALLOWED_AVATAR_MIME_TYPES: List[str] = ["image/png", "image/jpeg"]
    AVATAR_UPLOAD_FOLDER: str = _AVATAR_UPLOAD_FOLDER

    # Wave 5 (2026-04-22): the 5 deprecated `DEFAULT_*_LEAD_STATUS*`
    # constants that lived here are gone. Production has used
    # `StatusHelper` (DB-driven lookups) + `AssignmentStatus` enum for
    # a while; the constants were kept as literal seed/assertion
    # strings for tests only. Tests now read them from
    # `tests/_lead_status_test_ids.py` instead.
    DEFAULT_ADMISSIONS_UNIT_ID: int = 1  # Fallback unit when no distribution config found

    # -- Security: Account Lockout --
    # These settings control brute-force protection for login attempts
    ACCOUNT_LOCKOUT_MAX_ATTEMPTS: int = Field(
        default=5, validation_alias="ACCOUNT_LOCKOUT_MAX_ATTEMPTS"
    )  # Lock after N failed attempts
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = Field(
        default=15, validation_alias="ACCOUNT_LOCKOUT_DURATION_MINUTES"
    )  # Lock duration in minutes
    ACCOUNT_LOCKOUT_WINDOW_MINUTES: int = Field(
        default=30, validation_alias="ACCOUNT_LOCKOUT_WINDOW_MINUTES"
    )  # Reset counter after N minutes of no attempts

    # -- Security: CSRF Protection --
    # Double-submit cookie pattern for state-changing requests
    CSRF_PROTECTION_ENABLED: bool = Field(
        default=True, validation_alias="CSRF_PROTECTION_ENABLED"
    )  # Enable CSRF middleware (disabled in test by default)
    CSRF_PROTECTION_IN_TEST: bool = Field(
        default=False, validation_alias="CSRF_PROTECTION_IN_TEST"
    )  # Force enable CSRF in test mode
    CSRF_ORIGIN_CHECK_ENABLED: bool = Field(
        default=False, validation_alias="CSRF_ORIGIN_CHECK_ENABLED"
    )  # Additional Origin/Referer validation (optional layer)

    # -- Security: Anomaly Detection --
    # These settings control suspicious activity detection on login
    ANOMALY_MAX_FAILED_LOGINS_PER_HOUR: int = Field(
        default=5, validation_alias="ANOMALY_MAX_FAILED_LOGINS_PER_HOUR"
    )
    ANOMALY_MAX_SESSIONS_PER_USER: int = Field(
        default=10, validation_alias="ANOMALY_MAX_SESSIONS_PER_USER"
    )  # Max concurrent sessions (enforced, oldest evicted)
    IDLE_SESSION_TIMEOUT_DAYS: int = Field(
        default=7, validation_alias="IDLE_SESSION_TIMEOUT_DAYS"
    )  # Revoke sessions idle longer than this

    # -- Security: Refresh Token Abuse Prevention (M4) --
    REFRESH_MAX_FAILURES: int = Field(
        default=5, validation_alias="REFRESH_MAX_FAILURES"
    )  # Max failed refresh attempts before lockout
    REFRESH_FAILURE_WINDOW_MINUTES: int = Field(
        default=5, validation_alias="REFRESH_FAILURE_WINDOW_MINUTES"
    )  # Window for counting failed refresh attempts
    ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS: int = Field(
        default=2, validation_alias="ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS"
    )  # Hours between logins from different countries to flag
    ANOMALY_UNUSUAL_LOGIN_START_HOUR: int = Field(
        default=2, validation_alias="ANOMALY_UNUSUAL_LOGIN_START_HOUR"
    )  # Start of unusual login hours (local time)
    ANOMALY_UNUSUAL_LOGIN_END_HOUR: int = Field(
        default=6, validation_alias="ANOMALY_UNUSUAL_LOGIN_END_HOUR"
    )  # End of unusual login hours (local time)
    # Risk-gate for suspicious-login EMAIL/zalo dispatch. risk_score weights
    # (login_history_service.RISK_WEIGHTS): new_ip 30 / new_device 40 /
    # new_location 50 / impossible_travel 80 (−20% if trusted device). A
    # bare new_ip (30, or 24 trusted) falls BELOW 40 → in-app banner only,
    # no email; new_device (40) and above keep all channels. Tunable without
    # code change.
    SUSPICIOUS_LOGIN_EMAIL_RISK_THRESHOLD: int = Field(
        default=40, validation_alias="SUSPICIOUS_LOGIN_EMAIL_RISK_THRESHOLD"
    )

    # -- Security: Socket Rate Limiting --
    SOCKET_MAX_CONN_PER_MINUTE: int = Field(
        default=60, validation_alias="SOCKET_MAX_CONN_PER_MINUTE"
    )  # Max WebSocket connections per minute per IP

    # -- Security: HIBP Breached Password Check --
    # Checks passwords against Have I Been Pwned database (OWASP ASVS §2.1.7)
    # Disabled in test mode to avoid external API calls and test password rejections
    HIBP_CHECK_ENABLED: bool = Field(
        default=True, validation_alias="HIBP_CHECK_ENABLED"
    )

    # -- Security: Device Fingerprint --
    # Server-side salt to prevent fingerprint spoofing
    # IMPORTANT: This should be a random string, set in .env
    # Example: openssl rand -base64 32
    DEVICE_FINGERPRINT_SALT: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        validation_alias="DEVICE_FINGERPRINT_SALT"
    )

    # -- Security: MFA (Multi-Factor Authentication) --
    # Fernet key for encrypting TOTP secrets at rest
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    MFA_ENCRYPTION_KEY: str = Field(
        default="", validation_alias="MFA_ENCRYPTION_KEY"
    )
    MFA_TOKEN_EXPIRE_MINUTES: int = Field(
        default=5, validation_alias="MFA_TOKEN_EXPIRE_MINUTES"
    )  # Short-lived MFA challenge token
    MFA_MAX_ATTEMPTS: int = Field(
        default=5, validation_alias="MFA_MAX_ATTEMPTS"
    )  # Max OTP attempts per 5-minute window
    MFA_ATTEMPT_WINDOW_MINUTES: int = Field(
        default=5, validation_alias="MFA_ATTEMPT_WINDOW_MINUTES"
    )  # Window for MFA attempt tracking
    MFA_ENFORCE_ROLES: List[str] = Field(
        default=["admin", "manager"], validation_alias="MFA_ENFORCE_ROLES"
    )  # Roles that MUST enable MFA (OWASP ASVS 5.0)

    # -- SMS Marketing: token + build (PR-3) --
    # Short-link token: HMAC hash secret (lookup) + Fernet keyring (re-export).
    # Prod cần giá trị thật. CỐ Ý KHÔNG fail-fast startup (để không gãy backend
    # prod khi SMS chưa cấu hình) — thiếu/invalid sẽ lỗi tại thời điểm BUILD
    # campaign có {link} (lazy, app/utils/sms_token.py). Dev/test: helper dẫn
    # xuất key từ default → chạy được không cần env.
    SMS_TOKEN_HASH_SECRET: str = Field(
        default="dev-sms-token-hash-secret-change-in-prod",
        validation_alias="SMS_TOKEN_HASH_SECRET",
    )
    # JSON string {version: fernet_key}, vd {"v1":"<Fernet.generate_key()>"}.
    SMS_TOKEN_ENCRYPTION_KEYS: str = Field(
        default="", validation_alias="SMS_TOKEN_ENCRYPTION_KEYS",
    )
    SMS_TOKEN_ACTIVE_KEY_VERSION: str = Field(
        default="", validation_alias="SMS_TOKEN_ACTIVE_KEY_VERSION",
    )
    SMS_IP_HASH_SECRET: str = Field(
        default="dev-sms-ip-hash-secret-change-in-prod",
        validation_alias="SMS_IP_HASH_SECRET",
    )  # click ip_hash (PR-5) — thêm sẵn cho keyring nhất quán
    SMS_PUBLIC_BASE_URL: str = Field(
        default="https://qlts.tnpc.edu.vn",
        validation_alias="SMS_PUBLIC_BASE_URL",
    )  # link {SMS_PUBLIC_BASE_URL}/r/{code}
    SMS_ALLOWED_REDIRECT_DOMAINS: str = Field(
        default="qlts.tnpc.edu.vn,tnpc.edu.vn",
        validation_alias="SMS_ALLOWED_REDIRECT_DOMAINS",
    )  # CSV host cho landing_type=external (§6.2)
    SMS_FREQUENCY_CAP_DAYS: int = Field(
        default=0, ge=0, le=3650, validation_alias="SMS_FREQUENCY_CAP_DAYS",
    )  # 0 = tắt; ge=0 chống âm; le=3650 trần (khớp campaign cap, chống 1e9)
    # [QC] LUÔN được chèn ở build (advertising NĐ91 Đ15) — không có toggle.
    SMS_OPTOUT_INSTRUCTION: str = Field(
        default=SMS_OPTOUT_INSTRUCTION_DEFAULT,
        validation_alias="SMS_OPTOUT_INSTRUCTION",
    )  # hướng dẫn từ chối SMS/điện thoại — org BẮT BUỘC đặt nội dung thật
    # -- Export file Excel per nhà mạng (PR-4) --
    SMS_EXPORT_STORAGE_DIR: str = Field(
        default="/app/private_exports/sms",
        validation_alias="SMS_EXPORT_STORAGE_DIR",
    )  # NGOÀI webroot (§11.7) — file chứa phone + raw short code; chỉ tải qua
    # endpoint admin có auth, KHÔNG khai báo nginx location public
    SMS_EXPORT_RETENTION_DAYS: int = Field(
        default=14, ge=1, le=365,
        validation_alias="SMS_EXPORT_RETENTION_DAYS",
    )  # re-download tới expires_at; cleanup job xoá file + set purged_at
    # -- Giấy báo nhập học PDF (official issuance artifact) --
    ENROLLMENT_LETTER_STORAGE_DIR: str = Field(
        default="/app/private_exports/letters",
        validation_alias="ENROLLMENT_LETTER_STORAGE_DIR",
    )  # NGOÀI webroot — PDF chứa PII (tên/địa chỉ/ngành/tiền); chỉ tải qua
    # endpoint có auth + IDOR, KHÔNG khai báo nginx location public
    ENROLLMENT_LETTER_RETENTION_DAYS: int = Field(
        default=90, ge=1, le=3650,
        validation_alias="ENROLLMENT_LETTER_RETENTION_DAYS",
    )  # re-download tới expires_at; sau đó cleanup xoá FILE và SCRUB phần PII
    # trong data_snapshot (tên/ngày sinh/địa chỉ/điện thoại). Row Ở LẠI vĩnh
    # viễn làm dấu vết phát hành (ai phát, lúc nào, cho hồ sơ nào, sha256 của
    # bản đã phát) + phần phi-PII đã in (ngành, học phí, năm học, mức đợt 1,
    # tài khoản, người ký). ⚠️ SAU retention KHÔNG re-render lại được nguyên
    # văn — đó là đánh đổi CÓ CHỦ Ý giữa data-minimization và tái lập. Cần lưu
    # lâu hơn thì nâng số ngày này, đừng bỏ bước scrub.
    # -- Landing page công khai /lp/{code} (PR-5) --
    SMS_LANDING_SCHOOL_NAME: str = Field(
        default="Cao đẳng Bách khoa Tây Nguyên",
        validation_alias="SMS_LANDING_SCHOOL_NAME",
    )  # tên trường hiển thị header landing (nhận diện, chống nghi lừa đảo).
    # Default = tên thật (hệ thống phục vụ 1 trường); env vẫn override được.
    SMS_LANDING_CONSENT_NOTICE: str = Field(
        default=(
            "Bạn nhận tin này vì đã đăng ký/quan tâm tuyển sinh. "
            "Không muốn nhận nữa? Bấm \"Hủy nhận tin\"."
        ),
        validation_alias="SMS_LANDING_CONSENT_NOTICE",
    )  # câu thông báo cơ sở xử lý dữ liệu trên landing (§19.2)
    # -- Phase 2 (§16) deep engagement / đo quan tâm ngành --
    SMS_SESSION_TOKEN_HASH_SECRET: str = Field(
        default="dev-sms-session-token-hash-secret-change-in-prod",
        validation_alias="SMS_SESSION_TOKEN_HASH_SECRET",
    )  # HMAC session token landing (bearer) — secret riêng, prod đặt thật ≥32
    SMS_INTEREST_DWELL_CAP: int = Field(
        default=180, ge=1, le=86400,
        validation_alias="SMS_INTEREST_DWELL_CAP",
    )  # trần dwell/lượt (giây) cho dwell_factor=min(s/CAP,1) — chống gian lận
    SMS_INTEREST_HALF_LIFE: int = Field(
        default=14, ge=1, le=3650,
        validation_alias="SMS_INTEREST_HALF_LIFE",
    )  # bán rã (ngày) cho recency_weight=exp(-Δdays/HALF_LIFE)
    SMS_INTEREST_K: float = Field(
        default=3.0, gt=0,
        validation_alias="SMS_INTEREST_K",
    )  # hệ số normalize(x)=x/(x+K); cosmetic (không đổi thứ hạng)
    SMS_INTEREST_EVENT_RETENTION_DAYS: int = Field(
        default=365, ge=30, le=3650,
        validation_alias="SMS_INTEREST_EVENT_RETENTION_DAYS",
    )  # §16.9 retention: dọn event tracking chi tiết (sms_landing_session +
    # sms_program_view cascade) cũ hơn ngần này; GIỮ aggregate
    # sms_contact_program_interest (recency_weight khiến view quá cũ ≈0)

    # -- Docker self-hosted deployment --
    # When True, skip TLS enforcement for DB/Redis connections.
    # Use ONLY when PostgreSQL and Redis run on the same Docker network (no external exposure).
    ALLOW_DOCKER_INTERNAL_NETWORK: bool = Field(
        default=False, validation_alias="ALLOW_DOCKER_INTERNAL_NETWORK"
    )

    def _validate_production_secrets(self):
        """Fail-fast validation for production environment secrets."""
        if self.APP_ENV != "production":
            return

        weak_secrets = [
            "a-very-hard-to-guess-string-for-fastapi",
            "another-super-secret-key-for-fastapi",
            "your-secret-key-here-change-in-production",
            "your-jwt-secret-key-here-change-in-production",
        ]

        if self.SECRET_KEY in weak_secrets or len(self.SECRET_KEY) < 32:
            raise RuntimeError(
                "CRITICAL: SECRET_KEY is weak or default. "
                "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if self.JWT_SECRET_KEY in weak_secrets or len(self.JWT_SECRET_KEY) < 32:
            raise RuntimeError(
                "CRITICAL: JWT_SECRET_KEY is weak or default. "
                "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if self.DEVICE_FINGERPRINT_SALT == "CHANGE_ME_IN_PRODUCTION":
            raise RuntimeError(
                "CRITICAL: DEVICE_FINGERPRINT_SALT is still the default value. "
                "Generate with: openssl rand -base64 32"
            )
        # PR1 Commit 6: MFA TOTP secrets are encrypted at rest with this key
        # via Fernet (mfa_service._get_fernet -> Fernet(key)). A missing OR
        # malformed key passes a naive "is set" check but crashes MFA at
        # runtime ("Fernet key must be 32 url-safe base64-encoded bytes"), so
        # validate the actual Fernet format here.
        if not self.MFA_ENCRYPTION_KEY:
            raise RuntimeError(
                "CRITICAL: MFA_ENCRYPTION_KEY must be set in production."
            )
        try:
            from cryptography.fernet import Fernet

            Fernet(self.MFA_ENCRYPTION_KEY.encode())
        except Exception as exc:
            raise RuntimeError(
                "CRITICAL: MFA_ENCRYPTION_KEY is not a valid Fernet key "
                "(32 url-safe base64 bytes). Generate with: "
                "Fernet.generate_key().decode()"
            ) from exc
        if self.LOG_LEVEL == "DEBUG":
            raise RuntimeError(
                "CRITICAL: LOG_LEVEL=DEBUG is not allowed in production. Use INFO or higher."
            )

        # PR1 Commit 5: payment-facing URLs must be HTTPS + non-localhost in
        # production. FRONTEND_URL is echoed back to the user by the payment
        # gateway (open-redirect surface) and PUBLIC_BACKEND_URL is the MoMo
        # IPN host — localhost/HTTP would break callbacks or leak plaintext.
        for _name, _url in (
            ("FRONTEND_URL", self.FRONTEND_URL),
            ("PUBLIC_BACKEND_URL", self.PUBLIC_BACKEND_URL),
        ):
            _u = _url.lower()
            if not _u.startswith("https://"):
                raise RuntimeError(
                    f"CRITICAL: {_name} must use https:// in production."
                )
            if "localhost" in _u or "127.0.0.1" in _u:
                raise RuntimeError(
                    f"CRITICAL: {_name} points to localhost in production."
                )

        # ✅ C1: Reject localhost/default DB URLs in production
        db_url_lower = self.DATABASE_URL.lower()
        if "localhost" in db_url_lower or "127.0.0.1" in db_url_lower:
            raise RuntimeError(
                "CRITICAL: DATABASE_URL points to localhost in production. "
                "Use a remote database with proper credentials."
            )

        # ✅ M2: Enforce TLS for DB/Redis connections in production
        # Skip when using Docker internal network (services on same bridge, no external exposure)
        if not self.ALLOW_DOCKER_INTERNAL_NETWORK:
            if "asyncpg://" in db_url_lower and "sslmode=" not in db_url_lower:
                raise RuntimeError(
                    "CRITICAL: DATABASE_URL does not specify sslmode in production. "
                    "Add ?sslmode=require for encrypted connections. "
                    "Example: postgresql+asyncpg://user:pass@host/db?sslmode=require\n"
                    "If using Docker internal network, set ALLOW_DOCKER_INTERNAL_NETWORK=true"
                )

            redis_urls = [self.REDIS_URL, self.CELERY_BROKER_URL, self.CELERY_RESULT_BACKEND_URL]
            for url in redis_urls:
                if url.startswith("redis://") and not url.startswith("rediss://"):
                    raise RuntimeError(
                        f"CRITICAL: Redis URL uses unencrypted redis:// protocol in production: {url[:30]}... "
                        "Use rediss:// for TLS-encrypted connections.\n"
                        "If using Docker internal network, set ALLOW_DOCKER_INTERNAL_NETWORK=true"
                    )

    # -- Lead Scoring Defaults (Không từ env) --
    LEAD_SCORING_ENGAGEMENT_POINTS: Dict[str, Any] = {
        "consultation_count_multiplier": 5,
        "outcome": {"successful": 10, "follow-up": 5, "failed": -5},
        "method": {"meeting": 15, "call": 5, "email": 2},
        "duration_bonus_per_10_min": 2,
        "inactivity_penalty_per_day": -1,
        "max_score": 100,
    }
    LEAD_SCORING_FIT_POINTS: Dict[str, Any] = {
        "source": {"event": 20, "referral": 15, "website": 5},
        "gpa_thresholds": {8.0: 20, 7.0: 10, 6.0: 5},
        "education_level": {"Tốt nghiệp THPT": 15, "Đã có bằng Đại học": 5},
        "location": {"Hà Nội": 10, "TP.HCM": 10},
        "max_score": 100,
    }
    LEAD_SCORING_URGENCY_POINTS: Dict[str, Any] = {
        "stage_order_multiplier": 15,
        "fast_conversion_bonus": 20,
        "slow_conversion_penalty": -10,
        "max_score": 100,
    }
    LEAD_SCORING_WEIGHTS: Dict[str, float] = {
        "engagement": 0.3,
        "fit": 0.4,
        "urgency": 0.2,
        "officer_rating_multiplier": 20,
        "officer_rating_weight": 0.1,
    }

    # -- Sentry Error Tracking (H12+M10) --
    # Set SENTRY_DSN in .env to enable. Leave empty to disable.
    SENTRY_DSN: str = Field(default="", validation_alias="SENTRY_DSN")
    SENTRY_TRACES_SAMPLE_RATE: float = Field(
        default=0.1, validation_alias="SENTRY_TRACES_SAMPLE_RATE"
    )  # 10% of transactions sampled by default

    # -- Log File Rotation (L2) --
    # Set LOG_FILE to enable file logging with rotation.
    LOG_FILE: str = Field(default="", validation_alias="LOG_FILE")
    LOG_FILE_MAX_BYTES: int = Field(
        default=10_485_760, validation_alias="LOG_FILE_MAX_BYTES"
    )  # 10 MB
    LOG_FILE_BACKUP_COUNT: int = Field(
        default=5, validation_alias="LOG_FILE_BACKUP_COUNT"
    )  # Keep 5 rotated files

    # -- Config Cache --
    CONFIG_CACHE_TTL_SECONDS: int = Field(
        default=3600, validation_alias="CONFIG_CACHE_TTL_SECONDS"
    )

    # -- GeoIP Development Mode --
    DEV_GEOIP_TEST_IP: str | None = Field(
        default=None, validation_alias="DEV_GEOIP_TEST_IP"
    )

    # -- Casbin Auto-Sync Templates --
    # If True, automatically sync casbin policies from templates on startup
    # Only applies in development mode; production always requires manual sync for safety
    AUTO_SYNC_TEMPLATES: bool = Field(
        default=False, validation_alias="AUTO_SYNC_TEMPLATES"
    )

    # -- Admission Cold Cutover Freeze (T0-2) --
    # When True, the AdmissionFreezeMiddleware rejects POST/PUT/PATCH/DELETE on
    # `/api/admissions`, `/api/admission-config`, and `/api/public/admissions`
    # with 503 — read endpoints (GET/HEAD/OPTIONS) stay open. Pydantic loads
    # this once at module import; flipping the env requires
    # `docker compose restart backend`. Pair with Nginx admission block (T0-3)
    # for defense-in-depth. See `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` §6.1.
    ADMISSION_FROZEN: bool = Field(
        default=False, validation_alias="ADMISSION_FROZEN"
    )

    # -- Admission Confirmation Settings --
    # Magic link token expiration and CCCD verification
    ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, validation_alias="ADMISSION_CONFIRM_TOKEN_EXPIRE_DAYS"
    )  # Token expires after N days
    ADMISSION_CONFIRM_MAX_ATTEMPTS: int = Field(
        default=5, validation_alias="ADMISSION_CONFIRM_MAX_ATTEMPTS"
    )  # Lock token after N failed CCCD attempts
    ADMISSION_CONFIRM_CCCD_DIGITS: int = Field(
        default=4, validation_alias="ADMISSION_CONFIRM_CCCD_DIGITS"
    )  # Last N digits to verify

    # -- Finance Module Feature Flags (Phase 0+1) --
    # Controls gradual rollout of Finance Module functionality
    FINANCE_MODULE_ENABLED: bool = Field(
        default=False, validation_alias="FINANCE_MODULE_ENABLED"
    )  # Master switch for finance module
    USE_NEW_FEE_TABLE: bool = Field(
        default=False, validation_alias="USE_NEW_FEE_TABLE"
    )  # Read fees from new table vs JSONB fallback
    FINANCE_PAYMENT_GATEWAY_ENABLED: bool = Field(
        default=False, validation_alias="FINANCE_PAYMENT_GATEWAY_ENABLED"
    )  # Enable online payment gateways (VNPay, etc.)
    FINANCE_MAKER_CHECKER_ENABLED: bool = Field(
        default=True, validation_alias="FINANCE_MAKER_CHECKER_ENABLED"
    )  # Require two-person verification for manual payments

    # ---------------------------------------------------------------------
    # Socket.IO — PII leak mitigation (PR #2 admission audit)
    # ---------------------------------------------------------------------
    # When True, `_emit_domain_event` honors the `rooms=` kwarg and fails
    # closed for sensitive events that reach the emitter without explicit
    # targeting. When False (legacy), rooms are ignored and every event
    # broadcasts globally — the pre-fix behavior kept only as a rollback
    # escape hatch. Default True per PR #2 acceptance: the fix must be
    # active in production after deploy, not deferred behind a manual flip.
    SOCKET_SCOPED_EMIT: bool = Field(
        default=True, validation_alias="SOCKET_SCOPED_EMIT"
    )

    ENABLE_FEE_VERIFICATION: bool = Field(
        default=False, validation_alias="ENABLE_FEE_VERIFICATION"
    )  # Block enrollment if tuition fee not paid/waived (Phase 6)
    MAJOR_CHANGE_REPRICE_ENABLED: bool = Field(
        default=False, validation_alias="MAJOR_CHANGE_REPRICE_ENABLED"
    )  # Feature "đổi ngành có khấu trừ phiếu thu + kế toán xác nhận". OFF =
    # no-op tuyệt đối: mọi nhánh (set/clear major_change_requested, nới finance
    # lock, bypass round-open, reprice hook, gate 6 điểm) gate cờ này. Bật ở PR-2
    # sau khi FE sẵn sàng. Migration cột/casbin/trigger là thuần cộng thêm nên
    # deploy cờ OFF không đổi hành vi.
    ADMISSION_FEE_GATE_MODE: Literal["legacy", "semester_hk1"] = Field(
        default="legacy", validation_alias="ADMISSION_FEE_GATE_MODE"
    )  # ADR-002: 'legacy' = paid/waived; 'semester_hk1' = HK1 financial clearance (partial passes)
    OVERDUE_NOTIFY_SINCE: Optional[str] = Field(
        default=None, validation_alias="OVERDUE_NOTIFY_SINCE"
    )  # PR 8: ISO date (YYYY-MM-DD). Only dispatch PAYMENT_OVERDUE for invoices
    # with due_date >= this value. None = notify all overdue. Set explicitly
    # in env at rollout to prevent first-run notification burst.
    ADMISSION_SURVEY_ENABLED: bool = Field(
        default=False, validation_alias="ADMISSION_SURVEY_ENABLED"
    )  # Phase E master switch. Beat schedule is always registered (so a stale
    # worker can't silently drop it — see commit 011340b4), but the task
    # early-returns until this is flipped to true. Keeps rollout two-step:
    # 1) deploy with ENABLED=false, 2) set BASELINE_DATE, 3) flip ENABLED=true.
    ADMISSION_SURVEY_BASELINE_DATE: Optional[str] = Field(
        default=None, validation_alias="ADMISSION_SURVEY_BASELINE_DATE"
    )  # Phase E: ISO date (YYYY-MM-DD). Only dispatch APPLICATION_SURVEY_DUE for
    # profiles with approved_at >= this value. None = send to every profile whose
    # approved_at is ≥30d old and not yet surveyed (strongly discouraged on
    # first-run — would flood every past approval on day one). Set to deploy
    # date at rollout; leave fixed afterwards so the scheduler has a stable
    # scan window.
    ADMISSION_SURVEY_BATCH_SIZE: int = Field(
        default=100, validation_alias="ADMISSION_SURVEY_BATCH_SIZE"
    )  # Max profiles per scheduler tick. Keeps Zalo API load bounded and
    # recovers gracefully from single-profile failures (savepoint per row).
    ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT: bool = Field(
        default=False, validation_alias="ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT"
    )  # Phase P2-2: Use fairness-weighted scoring instead of pure round-robin
    ENABLE_MEMBER_WEIGHTED_ASSIGNMENT: bool = Field(
        default=False, validation_alias="ENABLE_MEMBER_WEIGHTED_ASSIGNMENT"
    )  # Member-weighted assignment: eff_util = workload/(capacity*assignment_weight).
    # Officers with a higher assignment_weight are treated as "emptier" and receive
    # proportionally more leads. INDEPENDENT of ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT
    # (either, both, or neither may be on). Default False ⇒ no behavior change until
    # flipped. The safety gate (real_util >= SAFETY_THRESHOLD) is never bent by weight.
    ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED: bool = Field(
        default=False,
        validation_alias="ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED",
    )  # Khi ON: khóa SẮP XẾP auto-assign (real_util/eff_util) tính trên
    # dist_load = workload − (lead officer TỰ TUYỂN, xem _self_sourced_subquery),
    # KHÔNG trên tổng workload. Mục tiêu: lead tự tuyển không làm giảm suất nhận
    # lead-chia. Cổng an toàn `overloaded`, gate `workload < capacity`, và
    # is_officer_at_threshold (referral fast-path) VẪN dùng TỔNG workload —
    # self-tuyển không phá trần quá tải thật. Default False ⇒ 0 đổi hành vi + 0
    # query phụ cho tới khi bật.
    ENABLE_FINANCE_WORKLOAD_DISCOUNT: bool = Field(
        default=False,
        validation_alias="ENABLE_FINANCE_WORKLOAD_DISCOUNT",
    )  # Khi ON: lead ở giai đoạn HỌC PHÍ non-final (sts14 Chưa hoàn tất học phí +
    # sts10 Đã hoàn tất học phí — xem TUITION_HOLD_STATUS_IDS) VÀ ĐÃ CÓ TIỀN HỌC
    # PHÍ HK1 VÀO (sts10 = settled, hoặc sts14 có fee tuition HK1 paid_amount>0 =
    # đã thu một phần — HK2+ KHÔNG tính, xem _tuition_payment_confirmed_subquery)
    # được GIẢM TRỪ khỏi
    # cơ sở sắp xếp (eff_util/dist_load), khỏi cổng `overloaded`, VÀ khỏi
    # is_officer_at_threshold (referral fast-path) — vì đây là khách đã chuyển đổi
    # đang chờ xác nhận nhập học, không còn là tải tư vấn. Gate cứng
    # `workload < capacity` VẪN theo TỔNG workload (không ôm quá capacity học sinh
    # thật). Loại trừ sts18 (TUITION_REFUNDED, is_final) VÀ ca "đã tính phí nhưng
    # chưa thu đồng nào" (officer còn phải theo đuổi ⇒ vẫn là tải thật). Default
    # False ⇒ 0 đổi hành vi + 0 aggregate/audit-shape phụ cho tới khi bật.

    # -- Lead Lifecycle SLA: auto-close stale rejected consultations --
    # A lead in sts04 (CONSULT_REJECTED, is_final=false for re-engagement) that
    # has had no consultation activity for this many days is auto-transitioned to
    # sts20 (CONSULT_GIVEUP, terminal) by the daily SLA beat. This frees officer
    # workload (sts04 still counts as non-final load) so balanced auto-assign can
    # resume. Tunable without code change. NOTE: 15d is more aggressive than 30d
    # (on prod data ~100 leads vs ~42) — pair with the reopen workflow before
    # flipping SLA_AUTO_GIVEUP_ENABLED so closed leads can come back.
    SLA_CONSULT_GIVEUP_DAYS: int = Field(
        default=15, validation_alias="SLA_CONSULT_GIVEUP_DAYS"
    )
    # Master switch for the daily auto-close beat (2-step rollout). Default False
    # so deploying the feature seeds sts20 + transitions (manual close by
    # manager/admin works immediately) WITHOUT auto-closing any lead. The beat
    # schedule is always registered (a stale worker can't silently drop it), but
    # the task early-returns until this is flipped true — pair with the one-shot
    # scripts/backfill_sts20_giveup.py so closing existing/stale leads is a
    # deliberate, observable step once the reopen workflow is ready.
    SLA_AUTO_GIVEUP_ENABLED: bool = Field(
        default=False, validation_alias="SLA_AUTO_GIVEUP_ENABLED"
    )

    # -- VNPay Payment Gateway Settings --
    # Get credentials from VNPay merchant portal
    # Sandbox docs: https://sandbox.vnpayment.vn/apis/
    VNPAY_TMN_CODE: str = Field(
        default="", validation_alias="VNPAY_TMN_CODE"
    )  # Merchant terminal code
    VNPAY_HASH_SECRET: str = Field(
        default="", validation_alias="VNPAY_HASH_SECRET"
    )  # Secret key for HMAC-SHA512
    VNPAY_PAYMENT_URL: str = Field(
        default="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        validation_alias="VNPAY_PAYMENT_URL"
    )  # Sandbox or production URL
    VNPAY_API_URL: str = Field(
        default="https://sandbox.vnpayment.vn/merchant_webapi/api/transaction",
        validation_alias="VNPAY_API_URL"
    )  # Query API URL

    # -- Notification Anti-spam (Phase C2) --
    NOTIFICATION_COOLDOWN_SECONDS: int = Field(
        default=300, validation_alias="NOTIFICATION_COOLDOWN_SECONDS"
    )  # Min interval (seconds) between same event+user+channel (default 5 min)
    NOTIFICATION_RATE_LIMIT_PER_HOUR: int = Field(
        default=50, validation_alias="NOTIFICATION_RATE_LIMIT_PER_HOUR"
    )  # Max notifications per user per hour

    # -- Notification Alerting (Phase D3) --
    ALERT_FAILURE_RATE_THRESHOLD: float = Field(
        default=0.20, validation_alias="ALERT_FAILURE_RATE_THRESHOLD"
    )  # Alert when failure rate exceeds 20%
    ALERT_BACKLOG_THRESHOLD: int = Field(
        default=500, validation_alias="ALERT_BACKLOG_THRESHOLD"
    )  # Alert when queued backlog exceeds count
    ALERT_WEBHOOK_LAG_MINUTES: int = Field(
        default=60, validation_alias="ALERT_WEBHOOK_LAG_MINUTES"
    )  # Alert when sent deliveries without webhook > this many minutes

    # -- Notification Circuit Breaker (Phase D2) --
    CIRCUIT_BREAKER_FAIL_MAX: int = Field(
        default=10, validation_alias="CIRCUIT_BREAKER_FAIL_MAX"
    )  # Failures before tripping breaker for a channel
    CIRCUIT_BREAKER_TIMEOUT: int = Field(
        default=300, validation_alias="CIRCUIT_BREAKER_TIMEOUT"
    )  # Seconds before breaker transitions from open → half-open

    # -- Notification Quota (Phase D1) --
    ZALO_DAILY_QUOTA_LIMIT: int = Field(
        default=500, validation_alias="ZALO_DAILY_QUOTA_LIMIT"
    )  # Zalo ZNS daily send limit per OA
    QUOTA_WARN_THRESHOLD_PCT: int = Field(
        default=80, validation_alias="QUOTA_WARN_THRESHOLD_PCT"
    )  # Alert when quota usage exceeds this %
    QUOTA_BLOCK_THRESHOLD_PCT: int = Field(
        default=100, validation_alias="QUOTA_BLOCK_THRESHOLD_PCT"
    )  # Block sends when quota usage exceeds this %

    # -- Zalo ZNS Integration (Phase C1) --
    # Get credentials from Zalo Business portal (business.zalo.me)
    ZALO_ENABLED: bool = Field(
        default=False, validation_alias="ZALO_ENABLED"
    )  # Master switch — must be True to register Zalo channel
    ZALO_APP_ID: str = Field(
        default="", validation_alias="ZALO_APP_ID"
    )  # Zalo app ID from developer portal
    ZALO_APP_SECRET: str = Field(
        default="", validation_alias="ZALO_APP_SECRET"
    )  # Secret key for HMAC webhook verification + OAuth
    ZALO_OA_ID: str = Field(
        default="", validation_alias="ZALO_OA_ID"
    )  # Official Account ID
    ZALO_REFRESH_TOKEN: str = Field(
        default="", validation_alias="ZALO_REFRESH_TOKEN"
    )  # Initial seed refresh token (used only on first bootstrap)
    ZALO_WEBHOOK_SECRET: str = Field(
        default="", validation_alias="ZALO_WEBHOOK_SECRET"
    )  # Secret for verifying webhook HMAC signatures

    # -- Zalo Bot Platform (Internal Staff Notifications) --
    # Separate from ZNS (ZALO_*). Zalo Bot Platform = free 3000 msg/month
    # for staff-facing push (no template approval required). Channel
    # registration / preference column added in later steps.
    ZALO_BOT_ENABLED: bool = Field(
        default=False, validation_alias="ZALO_BOT_ENABLED"
    )  # Master switch — must be True before registering zalo_bot channel
    ZALO_BOT_TOKEN: str = Field(
        default="", validation_alias="ZALO_BOT_TOKEN"
    )  # Bot token from bot.zaloplatforms.com — DO NOT log
    ZALO_BOT_WEBHOOK_SECRET: str = Field(
        default="", validation_alias="ZALO_BOT_WEBHOOK_SECRET"
    )  # X-Bot-Api-Secret-Token header value — DO NOT log
    ZALO_BOT_MONTHLY_QUOTA: int = Field(
        default=2800, validation_alias="ZALO_BOT_MONTHLY_QUOTA"
    )  # Zalo Bot free tier = 3000 msg/month; 2800 leaves ~7% safety margin.
    # MONTHLY (not daily): Zalo Bot Platform has NO hard daily cap (verified
    # bot.zapps.me docs), so a per-day limit wasted the monthly budget on
    # bursty admission-season traffic. (Old ZALO_BOT_DAILY_QUOTA removed —
    # extra="ignore" tolerates any stale env var.)

    # -- MoMo Payment Gateway Settings --
    # Get credentials from MoMo merchant portal
    # Docs: https://developers.momo.vn/v3/docs/payment/api/collection-link/
    MOMO_PARTNER_CODE: str = Field(
        default="", validation_alias="MOMO_PARTNER_CODE"
    )  # Partner code from MoMo
    MOMO_ACCESS_KEY: str = Field(
        default="", validation_alias="MOMO_ACCESS_KEY"
    )  # API access key
    MOMO_SECRET_KEY: str = Field(
        default="", validation_alias="MOMO_SECRET_KEY"
    )  # Secret for HMAC-SHA256
    MOMO_ENDPOINT: str = Field(
        default="https://test-payment.momo.vn/v2/gateway/api/create",
        validation_alias="MOMO_ENDPOINT"
    )  # Sandbox or production endpoint

    # -- School contact info (shared across email + Zalo channels) --
    SCHOOL_ADDRESS: str = Field(
        default="02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk",
        validation_alias="SCHOOL_ADDRESS",
    )
    SCHOOL_BANK_NAME: str = Field(default="", validation_alias="SCHOOL_BANK_NAME")
    SCHOOL_BANK_ACCOUNT: str = Field(default="", validation_alias="SCHOOL_BANK_ACCOUNT")
    SCHOOL_BANK_HOLDER: str = Field(default="", validation_alias="SCHOOL_BANK_HOLDER")

    # -- THCS diploma policy (Thông tư 10/2026/TT-BGDĐT) --
    # Từ 15/04/2026 bỏ cấp Bằng tốt nghiệp THCS, thay bằng xác nhận hoàn thành
    # chương trình trong học bạ. Học sinh hoàn thành lớp 9 (year_to) TỪ năm này
    # trở đi rơi vào diện mới → nếu hồ sơ vẫn ghi 'graduated_thcs' (có bằng) thì
    # bật cảnh báo MỀM rà soát nhãn. Chỉ lưu NĂM nên đây là heuristic rà soát,
    # KHÔNG khẳng định tuyệt đối. Nguồn 2026 DUY NHẤT ở đây (live caller truyền
    # tường minh; pure helper nhận None = no-op).
    THCS_DIPLOMA_REVIEW_FROM_GRADE9_YEAR: int = Field(
        default=2026, validation_alias="THCS_DIPLOMA_REVIEW_FROM_GRADE9_YEAR"
    )

    # === Pydantic Settings Configuration ===
    model_config = ConfigDict(
        # Đường dẫn tới file .env cần tải (chỉ tải nếu tồn tại)
        env_file=_env_file_path if _env_file_exists else None,
        env_file_encoding="utf-8",
        case_sensitive=True,  # Biến môi trường phân biệt hoa thường
        extra="ignore",  # Bỏ qua các biến môi trường thừa không định nghĩa trong Settings
    )

    # --- Tính toán lại giá trị dựa trên biến đã load ---
    def __init__(self, **values: Any):
        super().__init__(**values)
        # Tính toán lại MAX_AVATAR_CONTENT_LENGTH sau khi MAX_AVATAR_SIZE_MB đã được load
        self.MAX_AVATAR_CONTENT_LENGTH = self.MAX_AVATAR_SIZE_MB * 1024 * 1024

        # ✅ M5: Auto-generate secure dev secrets when using insecure defaults
        self._generate_dev_secrets()

    def _generate_dev_secrets(self):
        """Auto-generate random secrets in test mode; warn in dev if using insecure defaults."""
        if self.APP_ENV == "production":
            return

        # In test mode: auto-generate ephemeral secrets (OK for CI/test isolation)
        if self.APP_ENV == "test":
            import secrets as _secrets
            if self.DEVICE_FINGERPRINT_SALT == "CHANGE_ME_IN_PRODUCTION":
                self.DEVICE_FINGERPRINT_SALT = _secrets.token_urlsafe(32)
            if not self.MFA_ENCRYPTION_KEY:
                from cryptography.fernet import Fernet
                self.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
            return

        # In development: require persistent values in .env for stable behavior
        if self.DEVICE_FINGERPRINT_SALT == "CHANGE_ME_IN_PRODUCTION":
            print(
                "WARNING [config.py]: ⚠️ DEVICE_FINGERPRINT_SALT not set in .env. "
                "Device fingerprinting will be inconsistent. "
                "Add DEVICE_FINGERPRINT_SALT to your .env file."
            )

        if not self.MFA_ENCRYPTION_KEY:
            print(
                "WARNING [config.py]: ⚠️ MFA_ENCRYPTION_KEY not set in .env. "
                "MFA will not work. Add MFA_ENCRYPTION_KEY to your .env file."
            )


# --- Khởi tạo Settings ---
try:
    settings = Settings()
    # ✅ SECURITY: Fail-fast validation for production secrets
    settings._validate_production_secrets()

    print(
        f"INFO [config.py]: Settings loaded successfully. APP_ENV={settings.APP_ENV}, DB_URL={settings.DATABASE_URL[:30]}..."
    )  # Log một phần DB_URL

    # Debug log for GeoIP development mode
    if settings.DEV_GEOIP_TEST_IP:
        print(
            f"INFO [config.py]: 🌍 GeoIP DEV MODE ENABLED - Test IP: {settings.DEV_GEOIP_TEST_IP}"
        )
    else:
        print(
            f"INFO [config.py]: GeoIP DEV MODE DISABLED - Set DEV_GEOIP_TEST_IP in .env to test GeoIP on localhost"
        )
except Exception as e:
    print(
        f"CRITICAL [config.py]: Failed to initialize Settings. Ensure all required variables are in '{_env_file}' or system environment. Error: {e}"
    )
    raise e
