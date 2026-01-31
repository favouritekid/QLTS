# app/config.py
import os
from typing import Any, Dict, List

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
    JWT_ALGORITHM: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
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

    # -- Lead Assignment Defaults (Không từ env) --
    # ⚠️ DEPRECATED: These status constants are deprecated.
    # Production code now uses StatusHelper (database-driven) + AssignmentStatus enum.
    # These remain for test compatibility only and will be removed in future.
    # @see app/services/status_helper.py for the new approach.
    DEFAULT_INITIAL_LEAD_STATUS_ID: str = "TTHV000"  # DEPRECATED: Use StatusHelper.get_initial_status()
    DEFAULT_LOST_LEAD_STATUS_ID: str = "TTHV004"  # DEPRECATED: Use StatusHelper.get_rejected_status()
    DEFAULT_UNASSIGNED_LEAD_STATUS: str = "unassigned_pending"  # DEPRECATED: Use AssignmentStatus.FAILED
    DEFAULT_ASSIGNED_LEAD_STATUS: str = "assigned"  # DEPRECATED: Use AssignmentStatus.ASSIGNED
    DEFAULT_REASSIGN_LEAD_STATUS: str = "reassigned_pending"  # DEPRECATED: Use AssignmentStatus.REASSIGN_PENDING
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
    )  # Max concurrent sessions before warning
    ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS: int = Field(
        default=2, validation_alias="ANOMALY_SUSPICIOUS_COUNTRY_CHANGE_HOURS"
    )  # Hours between logins from different countries to flag
    ANOMALY_UNUSUAL_LOGIN_START_HOUR: int = Field(
        default=2, validation_alias="ANOMALY_UNUSUAL_LOGIN_START_HOUR"
    )  # Start of unusual login hours (local time)
    ANOMALY_UNUSUAL_LOGIN_END_HOUR: int = Field(
        default=6, validation_alias="ANOMALY_UNUSUAL_LOGIN_END_HOUR"
    )  # End of unusual login hours (local time)

    # -- Security: Socket Rate Limiting --
    SOCKET_MAX_CONN_PER_MINUTE: int = Field(
        default=60, validation_alias="SOCKET_MAX_CONN_PER_MINUTE"
    )  # Max WebSocket connections per minute per IP

    # -- Security: Device Fingerprint --
    # Server-side salt to prevent fingerprint spoofing
    # IMPORTANT: This should be a random string, set in .env
    # Example: openssl rand -base64 32
    DEVICE_FINGERPRINT_SALT: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        validation_alias="DEVICE_FINGERPRINT_SALT"
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
    ENABLE_FEE_VERIFICATION: bool = Field(
        default=False, validation_alias="ENABLE_FEE_VERIFICATION"
    )  # Block enrollment if tuition fee not paid/waived (Phase 6)

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


# --- Khởi tạo Settings ---
try:
    settings = Settings()
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
