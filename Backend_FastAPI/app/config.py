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

    # -- File Uploads --
    # Pydantic-settings reads MAX_AVATAR_SIZE_MB from env first
    MAX_AVATAR_SIZE_MB: int = Field(default=2, validation_alias="MAX_AVATAR_SIZE_MB")
    # MAX_AVATAR_CONTENT_LENGTH sẽ được tính toán lại trong __init__
    MAX_AVATAR_CONTENT_LENGTH: int = 2 * 1024 * 1024  # Khởi tạo với giá trị mặc định

    ALLOWED_AVATAR_EXTENSIONS: List[str] = ["png", "jpg", "jpeg"]
    ALLOWED_AVATAR_MIME_TYPES: List[str] = ["image/png", "image/jpeg"]
    AVATAR_UPLOAD_FOLDER: str = _AVATAR_UPLOAD_FOLDER

    # -- Lead Assignment Defaults (Không từ env) --
    ACTIVE_LEAD_STATUSES_FOR_WORKLOAD: List[str] = ["assigned", "in_progress"]
    DEFAULT_INITIAL_LEAD_STATUS_ID: str = "TTHV000"
    DEFAULT_LOST_LEAD_STATUS_ID: str = "TTHV004"
    DEFAULT_UNASSIGNED_LEAD_STATUS: str = "unassigned_pending"
    DEFAULT_ASSIGNED_LEAD_STATUS: str = "assigned"
    DEFAULT_REASSIGN_LEAD_STATUS: str = "reassigned_pending"

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
except Exception as e:
    print(
        f"CRITICAL [config.py]: Failed to initialize Settings. Ensure all required variables are in '{_env_file}' or system environment. Error: {e}"
    )
    raise e
