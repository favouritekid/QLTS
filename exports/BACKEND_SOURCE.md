# Backend Source Code

**Generated:** 2025-11-04 21:06:05  
**Project:** QLTS (Quản Lý Tài Sản)  
**Description:** Complete source code export of the FastAPI backend application

---

## 📁 Directory Structure

```
Backend_FastAPI/app/
└── __pycache__/
└── core/
    ├── __pycache__/
    ├── deps.py
└── models/
    ├── __pycache__/
    ├── __init__.py
    ├── base.py
    ├── config.py
    ├── lead.py
    ├── lead_history.py
    ├── organization.py
    ├── pipeline.py
    ├── user.py
    ├── user_session.py
└── routers/
    ├── __pycache__/
    ├── __init__.py
    ├── admin.py
    ├── auth.py
    ├── leads.py
    ├── organization.py
    ├── pipeline.py
    ├── profile.py
    ├── sessions.py
    ├── users.py
└── schemas/
    ├── __pycache__/
    ├── __init__.py
    ├── config.py
    ├── lead.py
    ├── organization.py
    ├── permissions.py
    ├── pipeline.py
    ├── user.py
    ├── user_session.py
└── services/
    ├── __pycache__/
    ├── __init__.py
    ├── anomaly_detection.py
    ├── assignment_service.py
    ├── config_service.py
    ├── insights_service.py
    ├── lead_service.py
    ├── organization_service.py
    ├── pipeline_service.py
    ├── session_service.py
    ├── user_service.py
└── static/
    ├── uploads/
    │   └── avatars/
    │       └── 0a621baa-4a5d-4367-ba30-3b4883d1a3c5.jpg
    │       └── 5a205d84-bfeb-431a-b373-ed68eca65687.jpg
└── utils/
    ├── __pycache__/
    ├── __init__.py
    ├── exceptions.py
    ├── file_helpers.py
└── __init__.py
└── celery_utils.py
└── config.py
└── database.py
└── email.py
└── main.py
└── ratelimit.py
└── security.py
```

---

## 📝 Source Files


## 📄 `__init__.py`

**Lines:** 1 | **Size:** 0 bytes

```python

```


## 📄 `celery_utils.py`

**Lines:** 269 | **Size:** 12311 bytes

```python
# app/celery_utils.py
import logging
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .services import assignment_service

# Lấy logger chuẩn của Python
log = logging.getLogger(__name__)

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND_URL,
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

# ==================================================================
# === KHÔNG CẦN ENGINE TOÀN CỤC NỮA ===
# ==================================================================

@worker_process_init.connect
def init_worker(**kwargs):
    """ Chỉ cấu hình logging cơ bản. """
    print("INFO [celery_utils.py/init_worker]: Initializing worker process...")
    logging.basicConfig(level=settings.LOG_LEVEL.upper(),
                        format='%(asctime)s [%(levelname)-5.5s] [%(name)s] %(message)s')
    log.info(f"Root logger level set to {settings.LOG_LEVEL.upper()}")
    print("INFO [celery_utils.py/init_worker]: Worker process initialized.")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """ Không cần làm gì ở đây nữa. """
    log.info("Shutting down worker process...")
    pass

# ==================================================================
# === Tasks ===
# ==================================================================

# Email task (Giữ nguyên là sync)
@celery_app.task(
    name="send_password_reset_email_task",
    autoretry_for=(Exception,), max_retries=3, default_retry_delay=60,
)
def send_password_reset_email_task(email_to: str, reset_url: str, username: str):
    """Sync Celery task để gửi email reset password."""
    task_log = logging.getLogger("send_password_reset_email_task")
    task_log.info(f"Task started for recipient: {email_to}")

    body = f"""
    <html><body><p>Xin chào {username},</p><p>Bạn đã yêu cầu...</p>
    <p><a href="{reset_url}">{reset_url}</a></p><p>Nếu bạn không yêu cầu...</p>
    </body></html>"""
    try:
        msg = MIMEMultipart("alternative"); msg["Subject"] = "[Celery] Yêu cầu Đặt lại Mật khẩu"
        msg["From"] = settings.MAIL_FROM; msg["To"] = email_to
        html_part = MIMEText(body, "html"); msg.attach(html_part)
        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS: server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
        task_log.info(f"Email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to}
    except Exception as e:
        task_log.error(f"Failed to send email to {email_to}", exc_info=True)
        raise e


# ✅ NEW: Login alert email task
@celery_app.task(
    name="send_login_alert_email_task",
    autoretry_for=(Exception,), max_retries=3, default_retry_delay=60,
)
def send_login_alert_email_task(
    email_to: str,
    username: str,
    ip_address: str,
    user_agent: str,
    device_type: str,
    browser: str,
    os: str,
    anomalies: dict = None  # ✅ NEW: Anomaly details
):
    """Sync Celery task to send login alert email for suspicious activity."""
    task_log = logging.getLogger("send_login_alert_email_task")
    task_log.info(f"Login alert task started for recipient: {email_to}")

    from datetime import datetime
    login_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build anomaly warnings
    anomaly_warnings = ""
    if anomalies:
        warnings = []
        if anomalies.get("new_ip"):
            warnings.append("⚠️ Địa chỉ IP mới chưa từng sử dụng")
        if anomalies.get("new_device"):
            warnings.append("⚠️ Thiết bị/trình duyệt mới")
        if anomalies.get("impossible_travel"):
            warnings.append("⚠️ Đăng nhập từ vị trí khác thường trong thời gian ngắn")
        if anomalies.get("excessive_sessions"):
            warnings.append("⚠️ Số lượng phiên đăng nhập đồng thời cao bất thường")
        if anomalies.get("unusual_time"):
            warnings.append("⚠️ Đăng nhập vào thời gian bất thường")

        if warnings:
            anomaly_warnings = f"""
            <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #856404;">🚨 Cảnh báo Bảo mật</h3>
                <ul style="margin-bottom: 0;">
                    {''.join(f'<li>{w}</li>' for w in warnings)}
                </ul>
            </div>
            """

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #d32f2f;">🔐 Cảnh báo Đăng nhập Đáng ngờ</h2>
            <p>Xin chào <strong>{username}</strong>,</p>
            <p>Chúng tôi phát hiện một hoạt động đăng nhập đáng ngờ vào tài khoản của bạn:</p>

            {anomaly_warnings}

            <h3>Chi tiết Đăng nhập:</h3>
            <table style="border-collapse: collapse; margin: 20px 0; width: 100%;">
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thời gian:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{login_time}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Địa chỉ IP:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{ip_address}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Thiết bị:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{device_type.capitalize()}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Trình duyệt:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{browser}</td>
                </tr>
                <tr style="background-color: #f5f5f5;">
                    <td style="padding: 10px; font-weight: bold; border: 1px solid #ddd;">Hệ điều hành:</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{os}</td>
                </tr>
            </table>

            <div style="background-color: #e8f5e9; border-left: 4px solid #4caf50; padding: 15px; margin: 20px 0;">
                <p style="margin: 0;"><strong>✅ Nếu đây là bạn:</strong> Không cần làm gì cả. Bạn có thể bỏ qua email này.</p>
            </div>

            <div style="background-color: #ffebee; border-left: 4px solid #f44336; padding: 15px; margin: 20px 0;">
                <p style="margin-top: 0;"><strong>❌ Nếu đây KHÔNG phải là bạn:</strong></p>
                <ol style="margin-bottom: 0;">
                    <li><strong>Đổi mật khẩu ngay lập tức</strong></li>
                    <li>Kiểm tra và revoke các phiên đăng nhập đáng ngờ trong cài đặt tài khoản</li>
                    <li>Bật xác thực hai yếu tố (2FA) nếu chưa có</li>
                    <li>Liên hệ với bộ phận hỗ trợ nếu bạn nghi ngờ tài khoản bị xâm nhập</li>
                </ol>
            </div>

            <p style="color: #666; font-size: 12px; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 15px;">
                Email này được gửi tự động từ hệ thống Lead Management System.<br>
                Vui lòng không trả lời email này.
            </p>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🚨 Cảnh báo Bảo mật: Phát hiện hoạt động đăng nhập đáng ngờ"
        msg["From"] = settings.MAIL_FROM
        msg["To"] = email_to
        html_part = MIMEText(body, "html")
        msg.attach(html_part)

        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT) as server:
            if settings.MAIL_STARTTLS:
                server.starttls()
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)

        task_log.info(f"Login alert email sent successfully to: {email_to}")
        return {"status": "success", "recipient": email_to, "ip_address": ip_address}
    except Exception as e:
        task_log.error(f"Failed to send login alert email to {email_to}", exc_info=True)
        raise e

# Auto-assignment task (QUAY LẠI HÀM SYNC `def`)
@celery_app.task(
    name="process_automatic_lead_assignment_task",
    bind=True, autoretry_for=(Exception,), max_retries=3, default_retry_delay=30,
)
def process_automatic_lead_assignment_task(self, lead_id: int): # <--- QUAY LẠI `def`
    """
    Sync Celery task. Tạo Engine/Session và gọi service async bên trong asyncio.run.
    """
    task_log = logging.getLogger("process_automatic_lead_assignment_task")
    task_log.info(f"Task received for lead_id: {lead_id}")

    # BỎ KIỂM TRA celery_async_session_maker (vì chúng ta tạo nó bên trong)

    async def _run_async_assignment_with_engine():
        # Lấy logger chuẩn bên trong hàm async
        async_task_log = logging.getLogger("assignment_task_async")
        
        # 1. TẠO ENGINE MỚI BÊN TRONG EVENT LOOP
        engine = create_async_engine(
            settings.DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=3600,
            pool_size=5, max_overflow=10, pool_timeout=30,
        )
        
        # 2. TẠO SESSIONMAKER MỚI
        ScopedSessionMaker = sessionmaker(
            bind=engine, class_=AsyncSession,
            expire_on_commit=False, autoflush=False,
        )

        try:
            async_task_log.info(f"Engine created. Creating session for lead_id: {lead_id}")
            async with ScopedSessionMaker() as session:
                async_task_log.debug(f"Session created, calling service for lead_id: {lead_id}")
                # Truyền logger vào service
                await assignment_service.automatically_assign_lead(lead_id, session, logger=async_task_log)
                async_task_log.debug(f"Service call finished, committing for lead_id: {lead_id}")
                
                # === BƯỚC QUAN TRỌNG ĐÃ SỬA TỪ LỖI TIMEOUT TRƯỚC ===
                await session.commit()
                # ===================================================
                
                async_task_log.debug(f"Transaction committed for lead_id: {lead_id}")
        
        finally:
            # 3. QUAN TRỌNG: HỦY ENGINE SAU KHI DÙNG
            async_task_log.debug(f"Disposing task-specific engine for lead_id: {lead_id}")
            await engine.dispose()
            async_task_log.debug(f"Engine disposed for lead_id: {lead_id}")

    try:
        # Chạy hàm async
        asyncio.run(_run_async_assignment_with_engine())
        result = {"status": "assigned", "lead_id": lead_id}
        task_log.info(f"Task success for lead_id: {lead_id}. Result: {result}")
        return result
    except Exception as e:
        task_log.error(f"Task failed for lead_id: {lead_id}", exc_info=True)
        raise e
```


## 📄 `config.py`

**Lines:** 147 | **Size:** 7101 bytes

```python
# app/config.py
import os
from typing import Any, Dict, List
# XÓA: from dotenv import load_dotenv, find_dotenv
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field # Thêm Field

# --- Lấy APP_ENV sớm để xác định file .env ---
APP_ENV_FOR_CONFIG = os.getenv("APP_ENV", "development")
print(f"INFO [config.py]: Determining env file based on APP_ENV_FOR_CONFIG = {APP_ENV_FOR_CONFIG}") # Log debug

_env_file = '.env.test' if APP_ENV_FOR_CONFIG == 'test' else '.env'
# Xác định đường dẫn tuyệt đối đến file .env trong thư mục gốc dự án
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file_path = os.path.join(_project_root, _env_file)
print(f"INFO [config.py]: Pydantic-settings will attempt to load env_file: '{_env_file_path}'")
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
    APP_ENV: str = Field(default="development", validation_alias='APP_ENV')
    LOG_LEVEL: str = Field(default="DEBUG", validation_alias='LOG_LEVEL')
    # Các biến bắt buộc (không có default), phải có trong file .env hoặc môi trường
    SECRET_KEY: str
    DATABASE_URL: str
    JWT_SECRET_KEY: str

    # JWT Settings với default
    JWT_ALGORITHM: str = Field(default="HS256", validation_alias='JWT_ALGORITHM')
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, validation_alias='ACCESS_TOKEN_EXPIRE_MINUTES')
    REFRESH_TOKEN_EXPIRE_DAYS: float = Field(default=30.0, validation_alias='REFRESH_TOKEN_EXPIRE_DAYS') # Dùng float

    # Các URL với default
    FRONTEND_URL: str = Field(default="http://localhost:5173", validation_alias='FRONTEND_URL')
    CORS_ORIGINS: str = Field(default="http://localhost:5173", validation_alias='CORS_ORIGINS') # Mặc định lấy từ FRONTEND_URL không hoạt động tốt với pydantic-settings, nên đặt giá trị mặc định rõ ràng

    # Mail Settings - Bắt buộc
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str
    # Mail Settings với default
    MAIL_PORT: int = Field(default=587, validation_alias='MAIL_PORT')
    MAIL_STARTTLS: bool = Field(default=True, validation_alias='MAIL_STARTTLS')
    MAIL_SSL_TLS: bool = Field(default=False, validation_alias='MAIL_SSL_TLS')

    # Redis Settings với default
    REDIS_URL: str = Field(default="redis://localhost:6379/1", validation_alias='REDIS_URL')

    # Celery Settings với default
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/2", validation_alias='CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND_URL: str = Field(default="redis://localhost:6379/3", validation_alias='CELERY_RESULT_BACKEND_URL')

    # -- File Uploads --
    # Pydantic-settings reads MAX_AVATAR_SIZE_MB from env first
    MAX_AVATAR_SIZE_MB: int = Field(default=2, validation_alias='MAX_AVATAR_SIZE_MB')
    # MAX_AVATAR_CONTENT_LENGTH sẽ được tính toán lại trong __init__
    MAX_AVATAR_CONTENT_LENGTH: int = 2 * 1024 * 1024 # Khởi tạo với giá trị mặc định

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
    CONFIG_CACHE_TTL_SECONDS: int = Field(default=3600, validation_alias='CONFIG_CACHE_TTL_SECONDS')

    # === Pydantic Settings Configuration ===
    model_config = ConfigDict(
        # Đường dẫn tới file .env cần tải (chỉ tải nếu tồn tại)
        env_file=_env_file_path if _env_file_exists else None,
        env_file_encoding='utf-8',
        case_sensitive=True, # Biến môi trường phân biệt hoa thường
        extra='ignore' # Bỏ qua các biến môi trường thừa không định nghĩa trong Settings
    )

    # --- Tính toán lại giá trị dựa trên biến đã load ---
    def __init__(self, **values: Any):
        super().__init__(**values)
        # Tính toán lại MAX_AVATAR_CONTENT_LENGTH sau khi MAX_AVATAR_SIZE_MB đã được load
        self.MAX_AVATAR_CONTENT_LENGTH = self.MAX_AVATAR_SIZE_MB * 1024 * 1024

# --- Khởi tạo Settings ---
try:
    settings = Settings()
    print(f"INFO [config.py]: Settings loaded successfully. APP_ENV={settings.APP_ENV}, DB_URL={settings.DATABASE_URL[:30]}...") # Log một phần DB_URL
except Exception as e:
    print(f"CRITICAL [config.py]: Failed to initialize Settings. Ensure all required variables are in '{_env_file}' or system environment. Error: {e}")
    raise e
```


## 📄 `core\deps.py`

**Lines:** 256 | **Size:** 10335 bytes

```python
# app/core/deps.py
import casbin

from typing import List
from fastapi import Path
import structlog
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt # <-- Sửa: import jwt trực tiếp
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, services, security # ✅ THÊM IMPORT security
from ..config import settings
from ..database import safe_redis_exists, safe_redis_get
from ..utils.exceptions import InvalidToken, PermissionDeniedError, ResourceNotFoundError

log = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(database.get_db)
) -> models.User:
    """
    ✅ FIXED: Dependency để lấy user hiện tại từ JWT token.
    Kiểm tra session (r_jti) và blacklist.
    """
    credentials_exception = InvalidToken(detail="Could not validate credentials")

    try:
        # ✅ BƯỚC 3: SỬA HÀM get_current_user

        # === STEP 1: DECODE TOKEN ===
        try:
            # Dùng hàm decode mới đã tạo trong security.py
            payload = security.decode_token(token)
        except InvalidToken as e:
            await log.warning("JWT decoding error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        access_jti: str | None = payload.get("jti")
        refresh_jti: str | None = payload.get("r_jti") # <-- Lấy JTI của Refresh Token
        token_type: str = payload.get("type", "access")

        if (
            username is None
            or access_jti is None
            or refresh_jti is None # <-- Kiểm tra cả refresh_jti
            or token_type != "access"
        ):
            await log.warning(
                "Token missing critical claims (sub, jti, r_jti, or wrong type)",
                payload=payload
            )
            raise credentials_exception

        # === STEP 2: CHECK ACCESS JTI BLACKLIST ===
        # (Kiểm tra xem chính Access Token này đã bị logout/xoay vòng chưa)
        try:
            is_jti_blacklisted = await safe_redis_exists(f"blacklist:{access_jti}")
            if is_jti_blacklisted:
                await log.info(
                    "Token validation failed: Access JTI found in blacklist", 
                    jti=access_jti
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error(
                "Redis Access JTI blacklist check failed", jti=access_jti, error=str(e)
            )
            # (Không cần fallback CSDL cho access JTI)

        # === STEP 3: GET USER & CHECK USER BLACKLIST ===
        user = await services.user_service.get_user_by_username(db, username=username)
        if user is None:
            await log.warning("Token validation failed: User not found", username=username)
            raise credentials_exception

        try:
            is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
            if is_user_blacklisted:
                await log.info(
                    "Token rejected: User found in global blacklist (password changed?)",
                    user_id=user.id,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error(
                "Redis user blacklist check failed", user_id=user.id, error=str(e)
            )
            # (Giữ nguyên logic fallback CSDL cho user blacklist)
            try:
                from sqlalchemy import select, and_
                from datetime import datetime, timezone
                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc)
                        )
                    )
                    .limit(1)
                )
                active_session = result.scalar_one_or_none()
                if active_session is None:
                    await log.warning(
                        "Database fallback: No active sessions found for user",
                        user_id=user.id
                    )
                    raise credentials_exception
                await log.info(
                    "Database fallback successful: User has active sessions",
                    user_id=user.id
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                await log.error(
                    "Database fallback failed during user blacklist check",
                    user_id=user.id,
                    error=str(db_error)
                )
                raise credentials_exception

        # === ✅ NEW STEP 4: CHECK SESSION VALIDITY ===
        # (Kiểm tra xem session (liên kết qua r_jti) có bị revoke không)
        try:
            stored_user_id = await safe_redis_get(f"session:{refresh_jti}")
            if not stored_user_id or int(stored_user_id) != user.id:
                await log.warning(
                    "Token validation failed: Session not found in Redis (revoked?)",
                    user_id=user.id,
                    refresh_jti=refresh_jti
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error(
                "Redis Session check failed", refresh_jti=refresh_jti, error=str(e)
            )
            # (Fallback CSDL cho session check)
            try:
                from sqlalchemy import select, and_
                from datetime import datetime, timezone
                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.refresh_jti == refresh_jti,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc)
                        )
                    )
                )
                session = result.scalar_one_or_none()
                if session is None:
                    await log.warning(
                        "Database fallback: Session not found or revoked",
                        jti=refresh_jti
                    )
                    raise credentials_exception
                await log.info(
                    "Database fallback successful: Session validated via database",
                    jti=refresh_jti
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                await log.error(
                    "Database fallback failed during Session check",
                    jti=refresh_jti,
                    error=str(db_error)
                )
                raise credentials_exception

        return user

    except (JWTError, InvalidToken):
        # Đã log lỗi bên trong security.decode_token hoặc ở trên
        raise credentials_exception
    except Exception as e:
        # Bắt các lỗi chung khác
        await log.error("Unhandled error in get_current_user", error=str(e), exc_info=True)
        raise credentials_exception


async def check_permission(
    request: Request,
    current_user: models.User = Depends(get_current_user)
):
    # (Giữ nguyên logic, thêm await cho log)
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    if not enforcer:
        await log.critical("Casbin enforcer not found in app state!")
        raise PermissionDeniedError("Permission system is misconfigured.")

    subject = f"user:{current_user.id}"
    object_path = request.url.path
    action = request.method

    if not enforcer.enforce(subject, object_path, action):
        await log.warning(
            "Permission Denied (Casbin)",
            subject=subject,
            object=object_path,
            action=action,
        )
        raise PermissionDeniedError(detail="You do not have permission for this action.")

    return current_user

def require_roles(required_roles: List[str]):
    # (Giữ nguyên logic)
    async def role_checker(
        current_user: models.User = Depends(get_current_user),
    ) -> models.User:
        if current_user.role not in required_roles:
            from ..utils.exceptions import PermissionDeniedError
            raise PermissionDeniedError(
                detail=f"User does not have the required roles: {required_roles}"
            )
        return current_user
    return role_checker

async def get_lead_for_user(
    lead_id: int = Path(..., description="ID của Lead"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.Lead:
    # (Giữ nguyên logic)
    from ..services import lead_service
    try:
        lead = await lead_service.get_lead_by_id(db, lead_id)
    except ResourceNotFoundError:
        raise
    if current_user.role in ["admin", "manager"]:
        return lead
    if current_user.role == "officer" and lead.assigned_officer_id == current_user.id:
        return lead
    raise PermissionDeniedError(detail="You do not have permission to access this lead.")

# (Giữ nguyên các dependency shortcuts)
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_roles(["admin"]))
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))
```


## 📄 `database.py`

**Lines:** 143 | **Size:** 4592 bytes

```python
# app/database.py
import redis.asyncio as redis
import structlog
from aiobreaker import CircuitBreaker
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from contextlib import asynccontextmanager

log = structlog.get_logger(__name__)

# === CẤU HÌNH ENGINE CSDL (Giữ nguyên) ===
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=20,
    max_overflow=40,
    # echo=(settings.APP_ENV == "development"), 
    echo=False, 
    connect_args={
        "server_settings": {
            "application_name": "qlts_backend_api",
        }
    },
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# === KHỞI TẠO REDIS CLIENT GỐC ===
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN VỚI AIOBREAKER (SỬA LẠI) 🔧 ===
# ===============================================================

# Khởi tạo breaker
# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN (ĐÃ SỬA safe_redis_pipeline) ===
# ===============================================================

redis_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

REDIS_BREAKER_EXCEPTIONS = (ConnectionError, TimeoutError)


async def safe_redis_ping():
    """Ping Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.ping)
    except REDIS_BREAKER_EXCEPTIONS:
        await log.error("Redis ping failed", exc_info=True)
        return False


async def safe_redis_get(key: str):
    """Lấy key từ Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.get, key)
    except REDIS_BREAKER_EXCEPTIONS:
        await log.error("Redis GET failed", key=key, exc_info=True)
        return None


async def safe_redis_exists(key: str) -> bool:
    """Kiểm tra key tồn tại (an toàn qua circuit breaker)."""
    try:
        result = await redis_breaker.call_async(redis_client.exists, key)
        return bool(result)
    except REDIS_BREAKER_EXCEPTIONS:
        await log.error("Redis EXISTS failed", key=key, exc_info=True)
        return False


async def safe_redis_set(key: str, value: str, ex: int):
    """Set key trong Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.set, key, value, ex=ex)
    except REDIS_BREAKER_EXCEPTIONS:
        await log.error("Redis SET failed", key=key, exc_info=True)
        raise


async def safe_redis_delete(key: str):
    """Xóa key khỏi Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.delete, key)
    except REDIS_BREAKER_EXCEPTIONS:
        await log.error("Redis DELETE failed", key=key, exc_info=True)
        return 0


# ✅ FIX: Tạo async context manager cho pipeline


@asynccontextmanager
async def safe_redis_pipeline(transaction: bool = True):
    """
    Async context manager cho Redis pipeline với circuit breaker protection.

    Usage:
        async with safe_redis_pipeline() as pipe:
            pipe.set("key1", "value1")
            pipe.set("key2", "value2")
            await pipe.execute()
    """
    pipe = None
    try:
        # Pipeline không cần qua breaker khi tạo (chỉ là object local)
        pipe = redis_client.pipeline(transaction=transaction)
        yield pipe

    except REDIS_BREAKER_EXCEPTIONS as e:
        await log.error("Redis PIPELINE operation failed", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()  # Cleanup pipeline
        raise
    except Exception as e:
        await log.error("Unexpected error in Redis pipeline", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()
        raise
    finally:
        # Cleanup (nếu cần)
        pass


# ===============================================================


async def get_db() -> AsyncSession:
    """Dependency function that yields a new SQLAlchemy AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session

```


## 📄 `email.py`

**Lines:** 56 | **Size:** 2066 bytes

```python
# app/email.py
import traceback  # <-- Dùng structlog thay logging

import structlog
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema

from .config import settings

log = structlog.get_logger(__name__)  # <-- Khởi tạo logger structlog

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)

fm = FastMail(conf)


async def send_password_reset_email(email_to: str, reset_url: str, username: str):
    """Gửi email chứa link reset mật khẩu."""
    body = f"""
    <p>Xin chào {username},</p>
    <p>Bạn đã yêu cầu đặt lại mật khẩu. Vui lòng nhấn vào liên kết dưới đây để tiếp tục:</p>
    <p><a href="{reset_url}">{reset_url}</a></p>
    <p>Nếu bạn không yêu cầu điều này, vui lòng bỏ qua email này.</p>
    """
    message = MessageSchema(
        subject="Yêu cầu Đặt lại Mật khẩu",
        recipients=[email_to],
        body=body,
        subtype="html",
    )

    try:
        await log.info("Attempting to send password reset email", recipient=email_to)
        await fm.send_message(message)
        await log.info("Password reset email task completed", recipient=email_to)
    except Exception as e:
        # === BỔ SUNG LOG CHI TIẾT HƠN ===
        # Ghi lại cả traceback để biết lỗi xảy ra ở đâu
        detailed_error = traceback.format_exc()
        await log.error(
            "Failed to send password reset email background task",
            recipient=email_to,
            error=str(e),
            traceback=detailed_error,
            exc_info=False,  # Không cần exc_info nữa vì đã có traceback
        )  # Log khi hoàn thành (không đảm bảo thành công 100%)

```


## 📄 `main.py`

**Lines:** 436 | **Size:** 19533 bytes

```python
# app/main.py
import logging
import sys
import uuid
import structlog
import ujson
import casbin
from .database import AsyncSessionLocal
from . import models  # Cần import models để dùng models.User

from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter, Base as CasbinBase
from .database import engine as async_db_engine
from fastapi import Depends, FastAPI, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager

from . import database
from .celery_utils import celery_app
from .config import settings
from .database import safe_redis_ping
from .database import redis_client as main_redis_client
from .ratelimit import limiter
from .routers import admin, auth, leads, organization, pipeline, profile, sessions, users
from .utils.exceptions import (
    AuthenticationError,
    BadRequest,
    BaseAppException,
    DuplicateResourceError,
    InvalidToken,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from pydantic import ValidationError
# === Cấu hình Structured Logging ===
# (Giữ nguyên cấu hình structlog của bạn, đảm bảo wrapper_class là AsyncBoundLogger)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Dùng ConsoleRenderer nếu là dev, JSONRenderer nếu là prod/tty
        structlog.dev.ConsoleRenderer()
        if settings.APP_ENV == "development"
        else structlog.processors.JSONRenderer(serializer=ujson.dumps),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.AsyncBoundLogger, # <-- Đây là lý do cần await
    cache_logger_on_first_use=True,
)

# Cấu hình handler cho logging
log_handler = logging.StreamHandler()
root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(log_handler)
root_logger.setLevel(settings.LOG_LEVEL.upper())

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

logging.getLogger("uvicorn.access").handlers.clear()
logging.getLogger("uvicorn.access").addHandler(log_handler)
logging.getLogger("uvicorn.error").handlers.clear()
logging.getLogger("uvicorn.error").addHandler(log_handler)

log = structlog.get_logger("app.main") # Logger giờ là async

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- LOGIC STARTUP ---
    await log.info("--- FastAPI application startup ---", environment=settings.APP_ENV)
    
    try:
        # 1. TẠO BẢNG CASBIN
        async with async_db_engine.begin() as conn:
            await conn.run_sync(CasbinBase.metadata.create_all)
        await log.info("Casbin 'casbin_rule' table checked/created.")

        # 2. KHỞI TẠO ADAPTER
        adapter = AsyncCasbinAdapter(async_db_engine)
        await log.info(f"Casbin Adapter successfully initialized: Type={type(adapter)}")

        # 3. KHỞI TẠO ENFORCER
        enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)

        # 4. TẢI POLICY
        await enforcer.load_policy()
        app.state.enforcer = enforcer
        await log.info("✅ Casbin AsyncEnforcer initialized and policies loaded.")

        # --- LOGIC GÁN VAI TRÒ ADMIN BAN ĐẦU ---
        # INITIAL_ADMIN_USER_ID = 115
        # ADMIN_ROLE_NAME = "role:admin"
        # ADMIN_SUBJECT = f"user:{INITIAL_ADMIN_USER_ID}"

        # has_admin_role = enforcer.has_grouping_policy(ADMIN_SUBJECT, ADMIN_ROLE_NAME)

        # if not has_admin_role:
        #     await log.info(f"Casbin grouping policy for initial admin ({ADMIN_SUBJECT}) not found. Attempting to add.")
        #     async with AsyncSessionLocal() as db:
        #         admin_user = await db.get(models.User, INITIAL_ADMIN_USER_ID)
        #         if admin_user and admin_user.role == 'admin':
        #             await log.info(f"Assigning initial admin role in Casbin to {ADMIN_SUBJECT}")
        #             added = await enforcer.add_grouping_policy(ADMIN_SUBJECT, ADMIN_ROLE_NAME)
        #             if added:
        #                 await log.info(f"Successfully added Casbin grouping policy: g, {ADMIN_SUBJECT}, {ADMIN_ROLE_NAME}")
        #             else:
        #                 await log.warning(f"Failed to add Casbin grouping policy (might already exist): g, {ADMIN_SUBJECT}, {ADMIN_ROLE_NAME}")
        #         elif not admin_user:
        #             await log.error(f"Initial admin user ID {INITIAL_ADMIN_USER_ID} not found in 'user' table. Cannot assign Casbin role.")
        #         else:
        #             await log.error(f"User {INITIAL_ADMIN_USER_ID} exists but does not have 'admin' role in 'user' table. Cannot assign Casbin role.")
        # else:
        #     await log.info(f"Casbin grouping policy for initial admin ({ADMIN_SUBJECT}) already exists.")
        # # --- KẾT THÚC LOGIC GÁN VAI TRÒ ADMIN BAN ĐẦU ---

        # 5. THÊM POLICY 'p' MẶC ĐỊNH (nếu chưa có)
        if not enforcer.get_policy():
            await log.info("No Casbin P policies found. Adding defaults...")
            await enforcer.add_policy("role:admin", "/*", ".*")
            await enforcer.add_policy("role:manager", "/api/admin/users", ".*")
            await enforcer.add_policy("role:manager", "/api/leads/*", ".*")
            await enforcer.add_policy("role:manager", "/api/leads", "GET")

            await enforcer.add_policy("role:officer", "/api/leads", "GET") # Policy mới từ Fix 1
            await enforcer.add_policy("role:officer", "/api/leads/{lead_id}", "GET")
            await enforcer.add_policy("role:officer", "/api/leads/{lead_id}/consultations", "POST")
            await enforcer.add_policy("role:officer", "/api/leads/{lead_id}/action", "POST")

            # === THÊM CÁC POLICY CHO PROFILE ===
            await enforcer.add_policy("role:user", "/api/profile", "GET")
            await enforcer.add_policy("role:user", "/api/profile", "PUT")
            await enforcer.add_policy("role:officer", "/api/profile", "GET") # Cho phép officer
            await enforcer.add_policy("role:officer", "/api/profile", "PUT")
            await enforcer.add_policy("role:manager", "/api/profile", "GET") # Cho phép manager
            await enforcer.add_policy("role:manager", "/api/profile", "PUT")
            # === KẾT THÚC THÊM POLICY ===

            await log.info("Default P policies added.")

    except Exception as e:
        await log.critical("❌ FAILED TO INITIALIZE OR CONFIGURE CASBIN ENFORCER!", error=str(e), exc_info=True)
    
    # ==========================================================
    # === ⭐️ DI CHUYỂN LOGIC RATE LIMITER VÀO ĐÂY ⭐️ ===
    # ==========================================================
    if settings.APP_ENV != "test":
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        await log.info("SlowAPI rate limiter INITIALIZED for non-test environment.")
    else:
        # Thêm 'await' vì chúng ta đang ở trong hàm async
        await log.info("APP_ENV is 'test', skipping SlowAPI rate limiter setup.")
    # ==========================================================



    # --- Kiểm tra Redis ---
    try:
        pong = await safe_redis_ping()
        await log.info("✅ Redis connection successful", response=pong)
    except Exception as e:
        await log.error(
            "❌ FAILED TO CONNECT TO REDIS on startup!", error=str(e), exc_info=True
        )
    
    # --- Ứng dụng chạy ---
    yield
    
    # --- LOGIC SHUTDOWN ---
    await log.info("--- FastAPI application shutdown ---")
    # Thêm phần đóng Redis client ở đây
    try:
        await main_redis_client.aclose() # Sử dụng client đã import
        await log.info("✅ Main Redis client connection closed.")
    except Exception as e:
        await log.error("Error closing main Redis client connection during shutdown.", error=str(e))

# === KHỞI TẠO APP ===
app = FastAPI(
    title="QLTS Project API with FastAPI",
    description="API for managing leads, users, and system configurations.",
    version="1.0.0",
    lifespan=lifespan 
)

# ===============================================================
# === EXCEPTION HANDLERS (Đã thêm 'await' cho log) =============
# ===============================================================

@app.exception_handler(InvalidToken)
async def invalid_token_handler(request: Request, exc: InvalidToken):
    await log.warning(
        "Invalid Token Error",
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.detail},
        headers={"WWW-Authenticate": "Bearer"},
    )

@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    await log.warning(
        "Authentication Error",
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": exc.detail},
        headers={"WWW-Authenticate": "Bearer"},
    )

@app.exception_handler(BadRequest)
async def bad_request_handler(request: Request, exc: BadRequest):
    await log.warning("Bad Request", detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.detail},
    )

@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    await log.warning("Permission Denied", detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": exc.detail},
    )

@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
    await log.warning("Resource Not Found", detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": exc.detail},
    )

@app.exception_handler(DuplicateResourceError)
async def duplicate_resource_handler(request: Request, exc: DuplicateResourceError):
    await log.warning("Duplicate Resource", detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_details = []
    for error in exc.errors():
        # Bỏ html.escape() như đã sửa
        field_parts = [str(loc_part) for loc_part in error.get("loc", [])]
        field = " -> ".join(field_parts) if field_parts else "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    await log.warning("Request Validation Error", errors=error_details, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException):
    await log.error(
        "Unhandled BaseAppException",
        type=type(exc).__name__,
        detail=exc.detail,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )

@app.exception_handler(ValidationError) # Thêm handler này
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    error_details = []
    for error in exc.errors():
        field = " -> ".join(map(str, error.get("loc", []))) or "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    await log.warning("Pydantic Validation Error inside endpoint", errors=error_details, path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    await log.exception("Unhandled Internal Server Error", path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred."},
    )

# ===============================================================
# === MIDDLEWARES =============================================
# ===============================================================

# Add Limiter state and exception handler
# app.state.limiter = limiter
# app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def request_id_tracking_middleware(request: Request, call_next):
    """Gán Request ID và bind vào structlog context."""
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.clear_contextvars() # Dọn dẹp context
    return response

# CORS Middleware
# ✅ SECURITY FIX: Expose Set-Cookie header for HttpOnly cookies
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")] if settings.CORS_ORIGINS else ["*"],
    allow_credentials=True,  # Required for cookies
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Set-Cookie"],  # Allow frontend to see Set-Cookie header
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Middleware để thêm các HTTP header bảo mật."""
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

# ===============================================================
# === ROUTERS ===================================================
# ===============================================================

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(sessions.router, prefix="/api", tags=["Sessions"])  # ✅ NEW: Session management
app.include_router(leads.router, prefix="/api/leads", tags=["Leads"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(organization.router, prefix="/api/organization", tags=["Organization"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


# ===============================================================
# === HEALTH CHECKS (Đã thêm 'async' và 'await') ================
# ===============================================================

@app.get("/health", tags=["Utilities"])
async def health_check(): # <-- SỬA: Chuyển thành async def
    """Kiểm tra API cơ bản."""
    await log.debug("Health check endpoint was reached.") # <-- SỬA: Thêm await
    return {"status": "ok", "message": "Server is healthy and running!"}


@app.get("/health/detailed", tags=["Utilities"])
async def detailed_health_check(db: AsyncSession = Depends(database.get_db)):
    """
    Kiểm tra sức khỏe chi tiết của API và các dịch vụ phụ thuộc.
    """
    checks = {
        "api": {"status": "ok", "message": "API is responsive"},
        "database": {"status": "unknown", "message": ""},
        "redis_cache": {"status": "unknown", "message": ""},
        "celery_broker": {"status": "unknown", "message": ""},
    }
    is_healthy = True

    # 1. Kiểm tra Database (PostgreSQL)
    try:
        await db.execute(text("SELECT 1"))
        checks["database"]["status"] = "ok"
        checks["database"]["message"] = "Database connection successful"
    except Exception as e:
        is_healthy = False
        checks["database"]["status"] = "error"
        checks["database"]["message"] = f"Database connection failed: {type(e).__name__}"
        await log.error("Health check failed (Database)", error=str(e)) # <-- SỬA: Thêm await

    # 2. Kiểm tra Redis
    try:
        await safe_redis_ping()
        checks["redis_cache"]["status"] = "ok"
        checks["redis_cache"]["message"] = "Redis connection successful"
    except Exception as e:
        is_healthy = False
        checks["redis_cache"]["status"] = "error"
        checks["redis_cache"]["message"] = f"Redis connection failed: {type(e).__name__}"
        await log.error("Health check failed (Redis Cache)", error=str(e)) # <-- SỬA: Thêm await

    # 3. Kiểm tra Celery (Broker/Worker)
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_workers = await run_in_threadpool(inspect.active) 

        if active_workers:
            checks["celery_broker"]["status"] = "ok"
            checks["celery_broker"]["message"] = f"Found {len(active_workers)} active worker(s)."
        else:
            is_healthy = False 
            checks["celery_broker"]["status"] = "error"
            checks["celery_broker"]["message"] = "No active Celery workers found."
    except Exception as e:
        is_healthy = False
        checks["celery_broker"]["status"] = "error"
        checks["celery_broker"]["message"] = f"Celery check failed (broker down?): {type(e).__name__}"
        await log.error("Health check failed (Celery)", error=str(e)) # <-- SỬA: Thêm await

    status_code = (
        status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=checks)
```


## 📄 `models\__init__.py`

**Lines:** 11 | **Size:** 456 bytes

```python
# flake8: noqa: F401
# app/models/__init__.py
from .base import Base
from .config import LeadScoringConfig, OfficerAssignmentConfig, SkillRequirementRule
from .lead import Application, AssignmentLog, Consultation, CRMInteraction, Lead
from .lead_history import LeadStatusHistory
from .organization import Major, OrganizationUnit
from .pipeline import ConsultationStatus, PipelineStage
from .user import User
from .user_session import UserSession

```


## 📄 `models\base.py`

**Lines:** 6 | **Size:** 160 bytes

```python
# app/models/base.py
from sqlalchemy.orm import declarative_base

# Tạo một lớp Base dùng chung cho tất cả các model
Base = declarative_base()

```


## 📄 `models\config.py`

**Lines:** 41 | **Size:** 1464 bytes

```python
# app/models/config.py
from sqlalchemy import JSON, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class OfficerAssignmentConfig(Base):
    __tablename__ = "officer_assignment_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="assignment_config")


class LeadScoringConfig(Base):
    __tablename__ = "lead_scoring_config"
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(
        Integer, ForeignKey("organization_unit.id"), nullable=False, unique=True
    )
    params = Column(JSON, nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    unit = relationship("OrganizationUnit", back_populates="scoring_config")


class SkillRequirementRule(Base):
    """Lưu trữ ma trận quy tắc để suy luận kỹ năng cần thiết cho Lead."""

    __tablename__ = "skill_requirement_rule"

    id = Column(Integer, primary_key=True, index=True)
    lead_attribute = Column(String(100), nullable=False)
    attribute_value = Column(String(255), nullable=False)
    required_skill = Column(String(100), nullable=False)

```


## 📄 `models\lead.py`

**Lines:** 163 | **Size:** 5779 bytes

```python
# app/models/lead.py
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class Lead(Base):
    """Model cho học viên tiềm năng (Lead)."""

    __tablename__ = "lead"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="new", index=True)
    lead_score = Column(Integer, default=0, nullable=False)
    education_level = Column(String(100), nullable=True)
    gpa = Column(Float, nullable=True)
    location = Column(String(255), nullable=True)
    officer_rating = Column(Integer, nullable=True)
    officer_summary = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    major_id = Column(Integer, ForeignKey("major.id"), nullable=True)
    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)
    assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True, index=True
    )
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )
    pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True, index=True
    )

    pipeline_stage = relationship("PipelineStage", back_populates="leads")

    assigned_officer = relationship(
        "User", back_populates="leads_assigned", foreign_keys=[assigned_officer_id]
    )
    consultations = relationship(
        "Consultation", back_populates="lead", cascade="all, delete-orphan"
    )
    application = relationship(
        "Application",
        back_populates="lead",
        uselist=False,
        cascade="all, delete-orphan",
    )
    interactions = relationship(
        "CRMInteraction", back_populates="lead", cascade="all, delete-orphan"
    )
    assignment_logs = relationship(
        "AssignmentLog", back_populates="lead", cascade="all, delete-orphan"
    )
    major = relationship("Major", back_populates="leads")
    unit = relationship("OrganizationUnit", back_populates="leads")
    consultation_status = relationship("ConsultationStatus", back_populates="leads")

    def __repr__(self):
        return f"<Lead {self.id}: {self.full_name}>"


class Consultation(Base):
    """Model cho các buổi tư vấn."""

    __tablename__ = "consultation"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    consultation_date = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    method = Column(String(50))
    notes = Column(Text)
    outcome = Column(String(50))
    duration_minutes = Column(Integer, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )

    consultation_status = relationship("ConsultationStatus")
    officer = relationship(
        "User", back_populates="consultations_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="consultations")


class Application(Base):
    """Model cho hồ sơ nhập học."""

    __tablename__ = "application"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, unique=True)
    documents = Column(JSON)
    status = Column(String(50), default="submitted")
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    officer = relationship(
        "User", back_populates="applications_handled", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="application")


class CRMInteraction(Base):
    """Model cho các tương tác CRM tự động."""

    __tablename__ = "crm_interaction"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False)
    type = Column(String(50))
    details = Column(JSON)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    lead = relationship("Lead", back_populates="interactions")


class AssignmentLog(Base):
    """Model để ghi lại lịch sử phân công lead."""

    __tablename__ = "assignment_log"

    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False)
    method = Column(String(50))
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason = Column(Text, nullable=True)
    officer_id = Column(Integer, ForeignKey("user.id"), nullable=False)

    officer = relationship(
        "User", back_populates="assignment_logs_involved", foreign_keys=[officer_id]
    )
    lead = relationship("Lead", back_populates="assignment_logs")

```


## 📄 `models\lead_history.py`

**Lines:** 75 | **Size:** 2920 bytes

```python
# app/models/lead_history.py
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from .base import Base

class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("lead.id"), nullable=False, index=True)
    
    # Ai thay đổi và lý do (Giữ nguyên)
    changed_by_user_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )  # Có thể là System (NULL) hoặc User ID
    reason = Column(Text, nullable=True)
    changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # === MỞ RỘNG TRƯỜNG LỊCH SỬ ===
    
    # 1. Trạng thái chính (lead.status)
    old_status = Column(String(50), nullable=True, index=True)
    new_status = Column(String(50), nullable=False, index=True)

    # 2. Trạng thái Pipeline (lead.consultation_status_id)
    old_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )
    new_consultation_status_id = Column(
        String(50), ForeignKey("consultation_status.id"), nullable=True
    )

    # 3. Giai đoạn Pipeline (lead.pipeline_stage_id)
    old_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )
    new_pipeline_stage_id = Column(
        String(50), ForeignKey("pipeline_stage.id"), nullable=True
    )
    
    # 4. Nhân viên phụ trách (lead.assigned_officer_id)
    old_assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    new_assigned_officer_id = Column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    # === KẾT THÚC MỞ RỘNG ===

    # Relationships
    lead = relationship(
        "Lead",
        foreign_keys=[lead_id] # Chỉ định rõ foreign_keys
    )
    changed_by_user = relationship(
        "User",
        foreign_keys=[changed_by_user_id] # Chỉ định rõ
    )
    
    old_officer = relationship("User", foreign_keys=[old_assigned_officer_id])
    new_officer = relationship("User", foreign_keys=[new_assigned_officer_id])
    old_consult_status = relationship("ConsultationStatus", foreign_keys=[old_consultation_status_id])
    new_consult_status = relationship("ConsultationStatus", foreign_keys=[new_consultation_status_id])
    old_pipeline_stage = relationship("PipelineStage", foreign_keys=[old_pipeline_stage_id])
    new_pipeline_stage = relationship("PipelineStage", foreign_keys=[new_pipeline_stage_id])


    def __repr__(self):
        return f"<LeadStatusHistory lead={self.lead_id} from={self.old_status} to={self.new_status}>"
```


## 📄 `models\organization.py`

**Lines:** 50 | **Size:** 1779 bytes

```python
# app/models/organization.py
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base


class OrganizationUnit(Base):
    __tablename__ = "organization_unit"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    parent = relationship(
        "OrganizationUnit", back_populates="children", remote_side=[id]
    )
    children = relationship("OrganizationUnit", back_populates="parent")
    # === KẾT THÚC SỬA LỖI ===

    users = relationship("User", back_populates="unit")
    majors = relationship("Major", back_populates="unit")
    leads = relationship("Lead", back_populates="unit")

    # Thêm relationship cho config
    assignment_config = relationship(
        "OfficerAssignmentConfig", back_populates="unit", uselist=False
    )
    scoring_config = relationship(
        "LeadScoringConfig", back_populates="unit", uselist=False
    )


class Major(Base):
    """Model cho các ngành học."""

    __tablename__ = "major"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=False)

    unit = relationship("OrganizationUnit", back_populates="majors")
    leads = relationship("Lead", back_populates="major")

```


## 📄 `models\pipeline.py`

**Lines:** 31 | **Size:** 1117 bytes

```python
# app/models/pipeline.py
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class PipelineStage(Base):
    __tablename__ = "pipeline_stage"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    order = Column(Integer, nullable=False, unique=True)

    leads = relationship("Lead", back_populates="pipeline_stage")

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    statuses = relationship("ConsultationStatus", back_populates="stage")


class ConsultationStatus(Base):
    __tablename__ = "consultation_status"
    id = Column(String(50), primary_key=True)
    name = Column(String(255), nullable=False)
    color_code = Column(String(7), nullable=False)
    stage_id = Column(String(50), ForeignKey("pipeline_stage.id"), nullable=False)

    # === SỬA LỖI: Chuyển 'backref' sang 'back_populates' ===
    stage = relationship("PipelineStage", back_populates="statuses")

    leads = relationship("Lead", back_populates="consultation_status")

```


## 📄 `models\user.py`

**Lines:** 64 | **Size:** 2574 bytes

```python
# app/models/user.py
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base


class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, unique=True, nullable=False)
    email = Column(String(120), index=True, unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(120), nullable=True)
    avatar_url = Column(String(256), nullable=True)
    phone_number = Column(String(20), nullable=True)
    address = Column(String(256), nullable=True)
    company = Column(String(120), nullable=True)
    role = Column(String(50), nullable=False, default="user")
    status = Column(String(50), nullable=False, server_default="active")
    active_jti = Column(String(36), nullable=True, index=True)

    unit_id = Column(Integer, ForeignKey("organization_unit.id"), nullable=True)

    skills = Column(JSON, nullable=True)
    max_capacity = Column(Integer, default=100)
    availability_status = Column(String(50), default="available")
    total_lead_score = Column(Integer, default=0, nullable=False)
    last_assigned_at = Column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    unit = relationship("OrganizationUnit", back_populates="users")
    leads_assigned = relationship(
        "Lead",
        back_populates="assigned_officer",
        foreign_keys="Lead.assigned_officer_id",
    )
    consultations_handled = relationship(
        "Consultation", back_populates="officer", foreign_keys="Consultation.officer_id"
    )
    applications_handled = relationship(
        "Application", back_populates="officer", foreign_keys="Application.officer_id"
    )
    assignment_logs_involved = relationship(
        "AssignmentLog",
        back_populates="officer",
        foreign_keys="AssignmentLog.officer_id",
    )
    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    # LƯU Ý QUAN TRỌNG:
    # Các phương thức set_password, check_password, get_reset_password_token
    # đã được gỡ bỏ khỏi model.
    # Logic này sẽ được chuyển đến lớp Services (ví dụ: user_service)
    # để tuân thủ nguyên tắc Single Responsibility: Model chỉ định nghĩa dữ liệu.

```


## 📄 `models\user_session.py`

**Lines:** 86 | **Size:** 3259 bytes

```python
# app/models/user_session.py
"""
Model for tracking user sessions to detect unauthorized access and manage active devices.
"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from .base import Base


class UserSession(Base):
    """
    Model để tracking các session đang hoạt động.
    
    Mỗi session tương ứng với một refresh token và device/browser cụ thể.
    Được sử dụng để:
    - Hiển thị danh sách active sessions cho user
    - Phát hiện login từ IP/device mới (anomaly detection)
    - Cho phép user revoke sessions từ devices cụ thể
    - Audit trail cho security events
    """
    __tablename__ = "user_session"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Session identification
    # refresh_jti là unique identifier cho mỗi refresh token
    # Khi refresh token được rotate, refresh_jti cũng được update
    refresh_jti = Column(String(36), unique=True, nullable=False, index=True)
    
    # Device/Browser info (extracted from User-Agent header)
    ip_address = Column(String(45), nullable=True)  # IPv6 support (max 45 chars)
    user_agent = Column(String(512), nullable=True)  # Full User-Agent string
    device_type = Column(String(50), nullable=True)  # mobile, desktop, tablet
    browser = Column(String(100), nullable=True)  # e.g., "Chrome 120.0"
    os = Column(String(100), nullable=True)  # e.g., "Windows 10"
    
    # Location (optional, requires IP geolocation service like MaxMind GeoIP2)
    country = Column(String(100), nullable=True)  # e.g., "Vietnam"
    city = Column(String(100), nullable=True)  # e.g., "Ho Chi Minh City"
    
    # Session lifecycle
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )
    last_activity_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False
    )
    
    # Security flags
    is_suspicious = Column(Boolean, default=False, nullable=False)  # Flagged by anomaly detection
    revoked_at = Column(DateTime(timezone=True), nullable=True)  # NULL = active, NOT NULL = revoked
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    
    def __repr__(self) -> str:
        return (
            f"<UserSession(id={self.id}, user_id={self.user_id}, "
            f"device={self.device_type}, ip={self.ip_address}, "
            f"active={self.revoked_at is None})>"
        )
    
    @property
    def is_active(self) -> bool:
        """Check if session is still active (not revoked and not expired)."""
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and self.expires_at > now
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at


```


## 📄 `ratelimit.py`

**Lines:** 13 | **Size:** 391 bytes

```python
# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings
REDIS_URL = settings.REDIS_URL  # <-- THAY ĐỔI Ở ĐÂY

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)

RATE_LIMITS = {"auth": "5/minute", "default": "100/hour"}

```


## 📄 `routers\__init__.py`

**Lines:** 1 | **Size:** 0 bytes

```python

```


## 📄 `routers\admin.py`

**Lines:** 1016 | **Size:** 38620 bytes

```python
# app/routers/admin.py
import structlog
import casbin
import pandas as pd
import io
from typing import List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import EmailStr  # <-- BỔ SUNG TypeAdapter, ValidationError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import database, models, schemas, services
from ..core import deps
from ..services import config_service, lead_service, organization_service, pipeline_service
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from ..schemas.permissions import PolicyCreate, RoleAssignment
from ..celery_utils import process_automatic_lead_assignment_task
from app.config import settings

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Admin"])

# --- ĐỊNH NGHĨA DEPENDENCY MỚI ---
PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


# ===============================================================
# POLICY MANAGEMENT ROUTES
# ===============================================================

@router.get(
    "/policies",
    response_model=List[List[str]], # Casbin trả về List[List[str]]
    tags=["Admin - Permissions"],
)
async def get_all_policies(request: Request, current_admin: models.User = PermissionDep):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies

@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def add_new_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thêm một chính sách (quyền) mới."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not added:
        raise DuplicateResourceError("Policy already exists.")

    # Chính xác: Không cần save_policy()

    return {"message": "Policy added successfully."}

@router.delete(
    "/policies",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một chính sách (quyền) cụ thể."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not removed:
        raise ResourceNotFoundError("Policy not found or could not be removed.")

    # Chính xác: Không cần save_policy()

    return {"message": "Policy removed successfully."}

@router.post(
    "/assign-role",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def assign_role_to_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Gán một vai trò cho người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_grouping_policy(f"user:{assignment.user_id}", assignment.role)
    if not added:
        raise DuplicateResourceError("User already has this role.")

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"message": "Role assigned."}

@router.delete(
    "/assign-role",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def remove_role_from_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa (thu hồi) vai trò của người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not removed:
        raise ResourceNotFoundError("Role assignment not found or could not be removed.")

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"message": "Role removed from user."}

# ===============================================================
# USER MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/users",
    response_model=schemas.User,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - User Management"],
)
async def create_new_user(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("user"),
    status: str = Form("active"),
    avatar: Optional[UploadFile] = File(None),
):
    """(Admin only) Tạo một người dùng mới, có hỗ trợ upload avatar."""
    user_in = schemas.AdminUserCreate(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        full_name=full_name,
        role=role,
        status=status,
    )

    if await services.user_service.get_user_by_username(db, user_in.username):
        raise DuplicateResourceError(detail="Username already exists")
    if await services.user_service.get_user_by_email(db, user_in.email):
        raise DuplicateResourceError(detail="Email already exists")

    # Truyền avatar vào hàm service
    return await services.user_service.create_user_by_admin(
        db, user_in, avatar_file=avatar
    )


@router.get(
    "/users", response_model=schemas.UsersPage, tags=["Admin - User Management"]
)
async def get_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """(Admin only) Lấy danh sách tất cả người dùng với phân trang, filter, search."""
    skip = (page - 1) * page_size
    query_params = dict(request.query_params)
    total, users = await services.user_service.get_users(
        db, params=query_params, skip=skip, limit=page_size
    )
    return {"total_count": total, "users": users}


@router.get(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy thông tin chi tiết của một người dùng."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    return db_user


@router.put(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def update_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # <-- Sửa lại thành Optional[str]
    phone_number: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    skills: Optional[str] = Form(None),  # Nhận JSON string từ form-data
    max_capacity: Optional[int] = Form(None),
):
    """(Admin only) Cập nhật người dùng, có hỗ trợ upload avatar."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    if not db_user:
        raise ResourceNotFoundError(detail="User not found")

    # Xây dựng dict chỉ chứa các trường hợp lệ được cung cấp
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()
    if role is not None and role.strip():
        update_dict["role"] = role.strip()
    if status is not None and status.strip():
        update_dict["status"] = status.strip()
    if max_capacity is not None and max_capacity >= 0:
        update_dict["max_capacity"] = max_capacity
    if skills is not None:
        try:
            # Chuyển đổi chuỗi JSON 'skills' từ Form thành đối tượng Python (list)
            import json

            update_dict["skills"] = json.loads(skills)
            if not isinstance(update_dict["skills"], list):
                raise ValueError("Skills must be a JSON list of strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Invalid format for skills. Must be a JSON string of a list (e.g., \'["skill1", "skill2"]\'): {e}',
            )
    # Chỉ xử lý email nếu được cung cấp và không rỗng
    if email is not None and email.strip():
        # Chỉ cần validate định dạng, không cần check DB
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(email.strip())
            update_dict["email"] = valid_email
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid email format: {email.strip()}. Error: {error_detail}",
            )

    # Tạo schema UserUpdate CHỈ với các dữ liệu đã được xác thực
    user_in = schemas.UserUpdate(**update_dict)

    # Truyền avatar vào hàm service
    return await services.user_service.update_user(
        db, db_user, user_in, avatar_file=avatar
    )


# === KẾT THÚC HÀM CẬP NHẬT ===
@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def delete_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một người dùng."""
    if user_id == current_admin.id:
        raise PermissionDeniedError(detail="Admin cannot delete themselves")

    # Bỏ kiểm tra 'is None' vì service đã ném 404
    await services.user_service.delete_user(db, user_id)
    return None


@router.post(
    "/users/{user_id}/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def admin_set_user_password(
    user_id: int,
    password_data: schemas.AdminSetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Admin đặt lại mật khẩu cho người dùng."""
    await services.user_service.set_password_by_admin(
        db, user_id, password_data.new_password
    )
    return None


@router.post(
    "/users/bulk-action",
    status_code=status.HTTP_200_OK,
    tags=["Admin - User Management"],
)
async def bulk_user_action(
    action_data: schemas.BulkActionSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thực hiện hành động hàng loạt (xóa, đổi trạng thái) trên nhiều người dùng."""
    message = await services.user_service.perform_bulk_action(
        db,
        action=action_data.action,
        user_ids=action_data.user_ids,
        admin_user=current_admin,
        new_status=action_data.status,
    )
    return {"message": message}


# ===============================================================
# ORGANIZATION & MAJOR MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một đơn vị tổ chức."""
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một đơn vị tổ chức."""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một đơn vị tổ chức."""
    await organization_service.delete_organization_unit(db, unit_id)
    return None


@router.post(
    "/majors",
    response_model=schemas.Major,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_major(
    major_in: schemas.MajorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một ngành học mới."""
    return await organization_service.create_major(db, major_in)


@router.get(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def get_major_details(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một ngành học."""
    return await organization_service.get_major_by_id(db, major_id)


@router.put(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def update_existing_major(
    major_id: int,
    major_in: schemas.MajorUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một ngành học."""
    return await organization_service.update_major(db, major_id, major_in)


@router.delete(
    "/majors/{major_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_major(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một ngành học."""
    await organization_service.delete_major(db, major_id)
    return None


# ===============================================================
# CONFIG MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def get_assignment_config_route(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy cấu hình phân chia của một đơn vị."""
    params = await config_service.get_assignment_config(db, unit_id)
    return {"params": params}


@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def update_assignment_config_route(
    unit_id: int,
    config_in: schemas.AssignmentConfig,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật cấu hình phân chia của một đơn vị."""
    updated_model = await config_service.update_assignment_config(db, unit_id, config_in.params)
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


@router.get(
    "/skill-rules", response_model=List[schemas.SkillRule], tags=["Admin - Config"]
)
async def get_all_skill_rules_route(
    db: AsyncSession = Depends(database.get_db), current_admin: models.User = PermissionDep
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Config"],
)
async def create_new_skill_rule_route(
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    return await config_service.create_skill_rule(db, rule_in)


@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Config"],
)
async def delete_skill_rule_route(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một quy tắc kỹ năng."""
    await config_service.delete_skill_rule(db, rule_id)
    return None

# ===============================================================
# PIPELINE MANAGEMENT ROUTES (MỚI)
# ===============================================================

@router.get(
    "/pipeline-stages",
    response_model=List[schemas.PipelineStage],
    tags=["Admin - Pipeline Management"],
)
async def get_all_pipeline_stages_list(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Giai đoạn (Stages) trong Pipeline."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.PipelineStage]
    stages_data = await pipeline_service.get_all_pipeline_stages(db)
    return stages_data

@router.post(
    "/pipeline-stages",
    response_model=schemas.PipelineStage,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_pipeline_stage(
    stage_in: schemas.PipelineStageCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Giai đoạn (Stage) mới trong Pipeline."""
    return await pipeline_service.create_pipeline_stage(db, stage_in)


@router.get(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def get_pipeline_stage_details(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Giai đoạn (Stage)."""
    return await pipeline_service.get_pipeline_stage(db, stage_id)




@router.put(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_pipeline_stage(
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Giai đoạn (Stage)."""
    return await pipeline_service.update_pipeline_stage(db, stage_id, stage_in)


@router.delete(
    "/pipeline-stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_pipeline_stage(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Giai đoạn (Stage). (Chỉ thành công nếu không có Status nào liên kết)"""
    await pipeline_service.delete_pipeline_stage(db, stage_id)
    return None


@router.post(
    "/consultation-statuses",
    response_model=schemas.ConsultationStatus,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_consultation_status(
    status_in: schemas.ConsultationStatusCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Trạng thái tư vấn (Status) mới."""
    return await pipeline_service.create_consultation_status(db, status_in)


@router.get(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def get_consultation_status_details(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Trạng thái tư vấn (Status)."""
    return await pipeline_service.get_consultation_status(db, status_id)


@router.put(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_consultation_status(
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Trạng thái tư vấn (Status)."""
    return await pipeline_service.update_consultation_status(db, status_id, status_in)


@router.delete(
    "/consultation-statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_consultation_status(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Trạng thái tư vấn (Status). (Chỉ thành công nếu không có Lead nào sử dụng)"""
    await pipeline_service.delete_consultation_status(db, status_id)
    return None

# ===============================================================
# LEAD MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/leads/{lead_id}/revert-status",
    response_model=schemas.Lead,
    tags=["Admin - Lead Management"],  # Thêm tag mới hoặc dùng tag cũ
    summary="Admin reverts the last status change of a Lead",
)
async def admin_revert_lead_status(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (Đã bao gồm check admin)
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI (Check Casbin)
    reason: Optional[str] = Body(
        None, embed=True, description="Reason for reverting the status"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của một Lead.
    """
    try:
        # Dependency 'LeadAccessDep' đã kiểm tra quyền admin/manager
        updated_lead = await lead_service.revert_last_status(
            db=db, lead_id=lead.id, admin_user=current_user, reason=reason
        )
        return updated_lead
    except (BadRequest, ResourceNotFoundError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        await log.error(
            "Error reverting lead status via API",
            lead_id=lead.id,
            admin_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revert lead status.",
        )


@router.post(
    "/leads/bulk-assign",
    status_code=status.HTTP_202_ACCEPTED, # Trả về 202 vì task chạy nền
    tags=["Admin - Lead Management"],
    summary="Trigger automatic assignment for multiple leads",
)
async def bulk_assign_leads(
    assignment_data: schemas.BulkAssignLeadsSchema, # Sử dụng schema mới
    current_admin: models.User = PermissionDep, # Yêu cầu quyền admin (qua Casbin)
):
    """
    (Admin only) Kích hoạt tác vụ phân công tự động cho một danh sách các Lead ID.
    Các tác vụ sẽ được xử lý dưới nền bởi Celery worker.
    """
    lead_ids = assignment_data.lead_ids
    dispatched_count = 0
    failed_ids = []

    await log.info("Received bulk assign request", admin_id=current_admin.id, lead_count=len(lead_ids))

    for lead_id in lead_ids:
        try:
            # Gọi task Celery cho từng lead_id
            process_automatic_lead_assignment_task.delay(lead_id)
            dispatched_count += 1
            await log.debug("Dispatched assignment task", lead_id=lead_id)
        except Exception as e:
            failed_ids.append(lead_id)
            await log.error(
                "Failed to dispatch assignment task for lead",
                lead_id=lead_id,
                error=str(e),
                exc_info=True # Log traceback nếu có lỗi khi gọi .delay()
            )

    success_rate = (dispatched_count / len(lead_ids)) * 100 if lead_ids else 100
    message = f"Successfully dispatched {dispatched_count}/{len(lead_ids)} ({success_rate:.1f}%) assignment tasks."

    if failed_ids:
        await log.warning("Some tasks failed to dispatch", failed_count=len(failed_ids), failed_ids=failed_ids)
        message += f" Failed to dispatch for {len(failed_ids)} leads."
        # Bạn có thể cân nhắc trả về status code khác nếu có lỗi, ví dụ 207 Multi-Status
        # Hoặc vẫn trả về 202 nhưng kèm thông tin lỗi chi tiết hơn trong body
        # return {"message": message, "failed_ids": failed_ids}

    await log.info("Finished processing bulk assign request", dispatched=dispatched_count, failed=len(failed_ids))
    return {"message": message}


@router.post(
    "/leads/import",
    response_model=schemas.LeadImportResult, # Sử dụng schema kết quả mới
    status_code=status.HTTP_200_OK, # Trả về 200 OK (hoặc 207 Multi-Status nếu muốn chi tiết hơn)
    tags=["Admin - Lead Management"],
    summary="Import leads from a CSV or Excel file",
)
async def import_leads_from_file(
    file: UploadFile = File(..., description="CSV or Excel file containing lead data (.csv, .xlsx)"),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Import leads từ file CSV hoặc Excel.
    File cần có các cột: 'full_name', 'email', 'phone', 'source', 'unit_id', 'major_id' (tùy chọn).
    Endpoint sẽ tạo leads trong DB nhưng **không** tự động phân công.
    Trả về kết quả import bao gồm ID các lead đã tạo và danh sách lỗi.
    """
    await log.info("Received lead import request", admin_id=current_admin.id, filename=file.filename)

    # --- 1. Kiểm tra loại file ---
    file_extension = ""
    if file.filename:
        file_extension = file.filename.rsplit('.', 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        await log.warning("Import failed: Invalid file extension", filename=file.filename, ext=file_extension)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only .csv and .xlsx files are supported."
        )

    # --- 2. Đọc nội dung file vào DataFrame ---
    try:
        content = await file.read()
        if not content:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded.")

        if file_extension == "csv":
            # Dùng io.BytesIO để pandas đọc từ bytes
            df = pd.read_csv(io.BytesIO(content))
        else: # xlsx
            df = pd.read_excel(io.BytesIO(content), engine='openpyxl')

        await log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

    except HTTPException as e:
        raise e # Ném lại lỗi 400
    except Exception as e:
        await log.error("Failed to read or parse file content", filename=file.filename, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}"
        )
    finally:
        await file.close() # Luôn đóng file

    # --- 3. Xử lý dữ liệu và Tạo Leads ---
    required_columns = {'full_name', 'email', 'phone', 'source', 'unit_id'}
    optional_columns = {'major_id'} # Các cột tùy chọn
    # Chuẩn hóa tên cột (viết thường, bỏ dấu cách)
    df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')

    # Kiểm tra các cột bắt buộc
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        await log.warning("Import failed: Missing required columns", missing=list(missing_cols))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is missing required columns: {', '.join(missing_cols)}"
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID # Lấy status mặc định

    # Lấy stage_id tương ứng với initial_status_id (cần cho bulk insert)
    initial_status_obj = await db.get(models.ConsultationStatus, initial_status_id)
    initial_stage_id = initial_status_obj.stage_id if initial_status_obj else None
    if not initial_stage_id:
        await log.error(f"FATAL: Initial status {initial_status_id} not found in DB. Cannot determine initial stage.")
        raise HTTPException(status_code=500, detail="System configuration error: Initial lead status not found.")

    # Lấy danh sách email đã tồn tại để kiểm tra trùng lặp hiệu quả hơn
    existing_emails_in_db = set()
    async for email_tuple in await db.stream(select(models.Lead.email)):
        existing_emails_in_db.add(email_tuple[0])
    emails_in_current_file = set()

    # Lặp qua từng dòng trong DataFrame
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2
        row_data = row.to_dict()
        cleaned_data = {} # Dữ liệu đã được ép kiểu
        validation_errors_for_row = [] # Lỗi ép kiểu

        # --- ✅ BẮT ĐẦU SỬA LỖI ÉP KIỂU ---
        
        # 1. Ép kiểu các trường bắt buộc
        try:
            # Dùng str() và strip() cho các trường text
            cleaned_data['full_name'] = str(row_data.get('full_name', '')).strip()
            cleaned_data['email'] = str(row_data.get('email', '')).strip()
            # Xử lý đặc biệt cho 'phone': luôn chuyển sang string, bỏ ".0" nếu là float
            phone_val = row_data.get('phone')
            cleaned_data['phone'] = str(phone_val).split('.')[0] if pd.notna(phone_val) else ""
            
            cleaned_data['source'] = str(row_data.get('source', '')).strip()
            
            # Xử lý 'unit_id': ép sang int
            unit_id_val = row_data.get('unit_id')
            if pd.notna(unit_id_val):
                cleaned_data['unit_id'] = int(float(unit_id_val))
            else:
                # Nếu unit_id là bắt buộc, Pydantic sẽ bắt lỗi 'missing' sau
                cleaned_data['unit_id'] = None 

        except (ValueError, TypeError, Exception) as e:
            # Lỗi cơ bản khi ép kiểu (ví dụ: unit_id là "abc")
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # 2. Ép kiểu trường tùy chọn 'major_id'
        major_id_val = row_data.get('major_id')
        if pd.notna(major_id_val):
            try:
                cleaned_data['major_id'] = int(float(major_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append("Invalid format for 'major_id', expected a number.")
        else:
            cleaned_data['major_id'] = None
        
        # --- KẾT THÚC SỬA LỖI ÉP KIỂU ---

        # 3. Validate bằng Pydantic
        try:
            # Nếu đã có lỗi ép kiểu, ném lỗi luôn để vào khối except
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Kiểm tra trùng lặp email
            if lead_in.email in existing_emails_in_db or lead_in.email in emails_in_current_file:
                raise ValueError(f"Email '{lead_in.email}' already exists in the database or this file.")

            emails_in_current_file.add(lead_in.email)

            # Chuẩn bị dict để bulk insert (Nếu mọi thứ OK)
            lead_dict = lead_in.model_dump()
            lead_dict['status'] = initial_status_id
            lead_dict['consultation_status_id'] = initial_status_id
            lead_dict['pipeline_stage_id'] = initial_stage_id
            lead_dict['assigned_officer_id'] = None
            lead_dict['assigned_at'] = None
            
            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e: 
             errors.append(schemas.LeadImportError(
                 row_number=row_number,
                 error_message=f"Data validation failed: {e}", # Lỗi Pydantic hoặc lỗi ép kiểu/trùng lặp
                 row_data=row_data
             ))
        except Exception as e: 
             errors.append(schemas.LeadImportError(
                 row_number=row_number,
                 error_message=f"Unexpected error processing row: {e}",
                 row_data=row_data
             ))

    # --- 4. Thực hiện Bulk Insert ---
    created_lead_ids: List[int] = []
    if leads_to_insert:
        try:
            # Sử dụng bulk_insert_mappings để hiệu quả và lấy lại ID
            # Lưu ý: Cần DB và dialect hỗ trợ (asyncpg hỗ trợ)
            # Không cần begin_nested vì chúng ta muốn commit hoặc rollback toàn bộ
            await db.execute(
                 pg_insert(models.Lead),
                 leads_to_insert
             )

            # Lấy ID của các lead vừa tạo (cần query lại dựa trên email chẳng hạn)
            # Hoặc nếu dùng bulk_insert_mappings với return_defaults=True trên bản SQLAlchemy mới hơn
            # results = await db.execute(stmt.returning(models.Lead.id))
            # created_lead_ids = [row[0] for row in results]

            # Cách đơn giản hơn: Query lại các lead vừa tạo dựa trên emails
            inserted_emails = [ld['email'] for ld in leads_to_insert]
            query = select(models.Lead.id).where(models.Lead.email.in_(inserted_emails))
            result = await db.execute(query)
            created_lead_ids = result.scalars().all()

            await db.commit()
            await log.info(f"Successfully bulk inserted {len(created_lead_ids)} leads.")

        except Exception as e:
            await db.rollback()
            await log.error("Bulk lead insertion failed, rolling back.", error=str(e), exc_info=True)
            # Ghi nhận tất cả các dòng đã chuẩn bị là lỗi
            for i, lead_dict in enumerate(leads_to_insert):
                 # Tìm row_number tương ứng (hơi phức tạp, có thể bỏ qua nếu quá khó)
                 # Giả sử lỗi chung cho cả batch
                 errors.append(schemas.LeadImportError(
                     row_number=-(i+1), # Dùng số âm để chỉ lỗi batch
                     error_message=f"Database bulk insert error: {e}",
                     row_data=lead_dict
                 ))
            created_lead_ids = [] # Reset ID vì đã rollback


    # --- 5. Trả về kết quả ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors
    )

    result_summary = result.model_dump(exclude={'errors'})
    if errors:
        await log.warning("Lead import process finished with errors", result=result_summary)
    else:
        await log.info("Lead import process finished successfully", result=result_summary)

    return result
```


## 📄 `routers\auth.py`

**Lines:** 639 | **Size:** 23605 bytes

```python
# app/routers/auth.py
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Body,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security, services
from ..config import settings
from ..core import deps
from ..services import session_service
from ..services.anomaly_detection import AnomalyDetector
from ..celery_utils import send_login_alert_email_task
from ..database import (
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_pipeline,
    safe_redis_set,
)
from ..ratelimit import RATE_LIMITS, limiter

def no_limit(func):
    return func
limit_auth = limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
limit_register = limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit

from ..utils.exceptions import InvalidToken

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMITS["auth"])
async def register_user(
    request: Request,
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    db_user_by_username = await services.user_service.get_user_by_username(
        db, username=user_in.username
    )
    if db_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{user_in.username}' already registered",
        )
    db_user_by_email = await services.user_service.get_user_by_email(
        db, email=user_in.email
    )
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user_in.email}' already registered",
        )
    created_user = await services.user_service.create_user(db=db, user_in=user_in)
    return created_user


@router.post("/login")
@limiter.limit(RATE_LIMITS["auth"])
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    user = await services.user_service.authenticate_user(
        db, username=form_data.username, password=form_data.password
    )
    
    try:
        await services.user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        await log.error(
            "Failed to remove user from global blacklist during login",
            user_id=user.id,
            error=str(e)
        )
    
    # ✅ BƯỚC 2: SỬA HÀM LOGIN
    
    # 1. Tạo Refresh Token TRƯỚC
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
    
    if not refresh_jti or refresh_ttl is None:
        await log.error("Failed to decode REFRESH token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Tạo Access Token, truyền refresh_jti vào
    access_token = security.create_access_token(
        data={"sub": user.username}, refresh_jti=refresh_jti
    )
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)

    if not access_jti:
        await log.error("Failed to decode ACCESS token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # (Đã xóa logic active_jti)

    try:
        await safe_redis_set(f"session:{refresh_jti}", str(user.id), ex=refresh_ttl)
        await log.info(
            "Refresh JTI stored in Redis for session",
            user_id=user.id,
            refresh_jti=refresh_jti[:8] + "..."
        )
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to set refresh JTI in Redis during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not process session")

    # (Giữ nguyên logic tạo session)
    try:
        from datetime import datetime, timedelta, timezone
        ip_address = request.client.host if request.client else None
        user_agent_string = request.headers.get("User-Agent")
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session = await session_service.create_session(
            db=db,
            user_id=user.id,
            refresh_jti=refresh_jti,
            ip_address=ip_address,
            user_agent_string=user_agent_string,
            expires_at=expires_at
        )
        detector = AnomalyDetector(db)
        anomalies = await detector.analyze_login(
            user_id=user.id,
            ip_address=ip_address,
            device_type=session.device_type,
            browser=session.browser,
            os=session.os,
            country=session.country,
            city=session.city,
            login_time=session.created_at
        )
        if anomalies["is_suspicious"]:
            session.is_suspicious = True
            db.add(session)
            try:
                send_login_alert_email_task.delay(
                    email_to=user.email,
                    username=user.username,
                    ip_address=ip_address or "Unknown",
                    user_agent=user_agent_string or "Unknown",
                    device_type=session.device_type or "Unknown",
                    browser=session.browser or "Unknown",
                    os=session.os or "Unknown",
                    anomalies=anomalies
                )
                await log.info(
                    "Login alert email queued for suspicious activity",
                    user_id=user.id,
                    ip_address=ip_address,
                    anomalies=anomalies
                )
            except Exception as email_error:
                await log.warning(
                    "Failed to queue login alert email",
                    user_id=user.id,
                    error=str(email_error)
                )
    except Exception as session_error:
        await log.error(
            "Failed to create session tracking record",
            user_id=user.id,
            error=str(session_error),
            exc_info=True
        )

    # (Giữ nguyên logic commit và response)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception as redis_del_e:
            await log.error(
                "Failed to delete session JTI from Redis after DB commit failure",
                user_id=user.id,
                error=str(redis_del_e),
            )
        await log.error(
            "Failed to commit DB changes during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not save session")

    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            }
        },
        status_code=200
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="strict",
        max_age=int(refresh_ttl),
        path="/api/auth",
    )
    return response


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
    authorization: Annotated[str | None, Header()] = None,
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    access_token = None
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ")[1]

    if access_token:
        access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
        if access_jti and access_ttl is not None and access_ttl > 0:
            try:
                await safe_redis_set(
                    f"blacklist:{access_jti}", "revoked", ex=access_ttl
                )
                await log.info(
                    "Access token blacklisted on logout",
                    jti=access_jti,
                    user_id=current_user.id,
                )
            except Exception as e:
                await log.error(
                    "Failed to blacklist access token on logout",
                    jti=access_jti,
                    error=str(e),
                )

    refresh_jti = None
    try:
        refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
        if refresh_jti:
            await safe_redis_delete(f"session:{refresh_jti}")
            if refresh_ttl and refresh_ttl > 0:
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=refresh_ttl
                )
            else:
                refresh_token_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=int(refresh_token_ttl)
                )
            await log.info(
                "Refresh token blacklisted on logout",
                jti=refresh_jti,
                user_id=current_user.id,
            )
    except Exception as e:
        await log.error(
            "Failed to blacklist refresh token on logout",
            user_id=current_user.id,
            error=str(e),
        )

    if refresh_jti:
        try:
            from sqlalchemy import select
            result = await db.execute(
                select(models.UserSession)
                .where(
                    models.UserSession.refresh_jti == refresh_jti,
                    models.UserSession.user_id == current_user.id
                )
            )
            session = result.scalar_one_or_none()
            if session:
                from datetime import datetime, timezone
                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
                await db.commit()
                await log.info(
                    "Session revoked on logout",
                    session_id=session.id,
                    user_id=current_user.id
                )
        except Exception as session_error:
            await log.warning(
                "Failed to revoke session on logout",
                user_id=current_user.id,
                error=str(session_error)
            )

    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/check-status")
async def check_session_status(
    current_user: models.User = Depends(deps.get_current_user),
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic - Giờ nó sẽ ổn vì get_current_user đã kiểm tra)
    from datetime import datetime, timezone
    from sqlalchemy import and_

    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == current_user.id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > datetime.now(timezone.utc)
            )
        )
    )
    active_sessions = result.scalars().all()

    # (Đoạn check `has_valid_session` này giờ có thể hơi thừa
    # vì `get_current_user` đã làm, nhưng giữ lại cũng không sao)
    has_valid_session = False
    for session in active_sessions:
        stored_user_id = await safe_redis_get(f"session:{session.refresh_jti}")
        if stored_user_id and int(stored_user_id) == current_user.id:
            has_valid_session = True
            break

    if not has_valid_session:
        await log.warning(
            "No valid session found in Redis for user (in check-status)",
            user_id=current_user.id
        )
        raise HTTPException(
            status_code=401,
            detail="Session has been revoked"
        )

    return {
        "status": "active",
        "user_id": current_user.id,
        "username": current_user.username,
        "session_valid": True,
        "active_sessions_count": len(active_sessions)
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RATE_LIMITS["auth"])
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    await services.user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )
    return {
        "msg": "If a user with that email exists, a password reset link will be sent."
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RATE_LIMITS["auth"])
async def perform_password_reset(
    request: Request,
    reset_data: schemas.ResetPasswordSchema, 
    db: AsyncSession = Depends(database.get_db)
):
    # (Giữ nguyên logic)
    return await services.user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def perform_change_password(
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    await services.user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )
    try:
        await services.user_service.invalidate_all_sessions(db, current_user)
        await log.info(
            "All user sessions invalidated after password change",
            user_id=current_user.id,
        )
    except Exception as e:
        await log.critical(
            "Failed to invalidate all sessions after password change, "
            "potential security risk of dangling sessions!",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
    return None


@router.post("/refresh")
async def refresh_access_token(
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Refresh token missing. Please login again."
        )

    credentials_exception = InvalidToken(detail="Invalid or expired refresh token")
    service_unavailable = HTTPException(
        status_code=503, detail="Auth service unavailable"
    )

    try:
        # (STEP 1: Decode - Giữ nguyên)
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            await log.warning("JWT decode error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        old_refresh_jti: str | None = payload.get("jti")
        token_type: str | None = payload.get("type")

        if not username or not old_refresh_jti or token_type != "refresh":
            await log.warning("Invalid refresh token payload", payload=payload)
            raise credentials_exception

        # (STEP 2: Check Blacklist - Giữ nguyên)
        try:
            is_blacklisted = await safe_redis_exists(f"blacklist:{old_refresh_jti}")
            if is_blacklisted:
                await log.warning("Refresh token is blacklisted", jti=old_refresh_jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error("Blacklist check failed", error=str(e), exc_info=True)
            pass

        # (STEP 3: Pessimistic Lock - Giữ nguyên)
        async with db.begin():
            try:
                stmt = (
                    select(models.User)
                    .where(models.User.username == username)
                    .with_for_update(nowait=False)
                )
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()

                if not user:
                    await log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # (STEP 4: Validate JTI - Giữ nguyên)
                stored_user_id = await safe_redis_get(f"session:{old_refresh_jti}")

                if not stored_user_id or int(stored_user_id) != user.id:
                    await log.warning(
                        "Session not found or user mismatch in Redis",
                        user_id=user.id,
                        token_jti=old_refresh_jti,
                        stored_user_id=stored_user_id,
                    )
                    if old_refresh_jti:
                        ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                        try:
                            await safe_redis_set(
                                f"blacklist:{old_refresh_jti}", "reuse_attempt", ex=ttl
                            )
                        except Exception as e_blacklist:
                            await log.error(
                                "Failed to blacklist reuse attempt",
                                jti=old_refresh_jti,
                                error=str(e_blacklist),
                            )
                    raise credentials_exception

                # ✅ BƯỚC 2 (tt): SỬA HÀM REFRESH
                
                # 1. Tạo Refresh Token MỚI TRƯỚC
                new_refresh_token = security.create_refresh_token(
                    data={"sub": username}
                )
                new_refresh_jti, new_refresh_ttl = (
                    security.decode_token_for_invalidation(new_refresh_token)
                )

                if not new_refresh_jti or new_refresh_ttl is None:
                    await log.error("Failed to decode new REFRESH token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # 2. Tạo Access Token MỚI, truyền new_refresh_jti vào
                new_access_token = security.create_access_token(
                    data={"sub": username}, refresh_jti=new_refresh_jti
                )
                new_access_jti, _ = security.decode_token_for_invalidation(
                    new_access_token
                )
                
                if not new_access_jti:
                    await log.error("Failed to decode new ACCESS token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # (Đã xóa logic active_jti)

                # (STEP 6: Update Session - Giữ nguyên)
                try:
                    await session_service.update_session_activity(
                        db=db,
                        old_refresh_jti=old_refresh_jti,
                        new_refresh_jti=new_refresh_jti,
                        user_id=user.id
                    )
                except Exception as session_error:
                    await log.warning(
                        "Failed to update session activity",
                        user_id=user.id,
                        error=str(session_error)
                    )

                await log.info("DB changes staged", user_id=user.id)

                # (STEP 7: Update Redis - Giữ nguyên)
                try:
                    async with safe_redis_pipeline(transaction=True) as pipe:
                        pipe.delete(f"session:{old_refresh_jti}")
                        pipe.set(
                            f"session:{new_refresh_jti}",
                            str(user.id),
                            ex=new_refresh_ttl,
                        )
                        pipe.set(f"blacklist:{old_refresh_jti}", "rotated", ex=300)
                        await pipe.execute()
                    await log.info("✅ Redis update successful (session rotated)", user_id=user.id)
                except Exception as e_redis:
                    await log.error(
                        "❌ Redis pipeline failed, will rollback DB",
                        user_id=user.id,
                        error=str(e_redis),
                        exc_info=True,
                    )
                    raise service_unavailable

                await log.info("✅ Token rotation completed successfully", user_id=user.id)

                # (STEP 8: Response - Giữ nguyên)
                response = JSONResponse(
                    content={
                        "access_token": new_access_token,
                        "token_type": "bearer",
                    },
                    status_code=200
                )
                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    httponly=True,
                    secure=settings.APP_ENV == "production",
                    samesite="strict",
                    max_age=int(new_refresh_ttl),
                    path="/api/auth",
                )
                return response

            except InvalidToken:
                raise credentials_exception
            except HTTPException:
                raise

    except (JWTError, InvalidToken):
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        await log.error(
            "Unhandled exception in refresh token endpoint", error=str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
```


## 📄 `routers\leads.py`

**Lines:** 168 | **Size:** 6604 bytes

```python
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..core.deps import get_lead_for_user

from ..services import insights_service, lead_service

router = APIRouter(tags=["Leads"])

PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


@router.post("", response_model=schemas.Lead, status_code=status.HTTP_201_CREATED)
async def create_new_lead(
    lead_in: schemas.LeadCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Tạo một Lead mới."""
    return await lead_service.create_lead(db, lead_in)


@router.get("", response_model=schemas.LeadsPage)
async def get_all_leads(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    # === ⭐️ THÊM CÁC THAM SỐ QUERY ===
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    assigned_officer_id: Optional[int] = Query(
        None, description="Filter by assigned officer ID"
    ),
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    major_id: Optional[int] = Query(None, description="Filter by major ID"),
    source: Optional[str] = Query(
        None, description="Filter by source (comma-separated)"
    ),
    search: Optional[str] = Query(
        None, description="Search term for name, email, phone"
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", description="Sort order (asc or desc)"),
    # === KẾT THÚC THÊM THAM SỐ ===
):
    """Lấy danh sách Leads (có phân trang, filter, search, sort)."""
    skip = (page - 1) * page_size
    total, leads = await lead_service.get_leads(
        db,
        skip=skip,
        limit=page_size,
        # === ⭐️ TRUYỀN THAM SỐ VÀO SERVICE ===
        status=status,
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        major_id=major_id,
        source=source,
        search=search,
        sort_by=sort_by,
        order=order,
        # === KẾT THÚC TRUYỀN THAM SỐ ===
    )
    return {"total_count": total, "leads": leads}


@router.get("/{lead_id}", response_model=schemas.Lead)
async def get_lead_details(
    lead: models.Lead = LeadAccessDep,
):
    """Lấy thông tin chi tiết của một Lead."""
    return lead


@router.put("/{lead_id}", response_model=schemas.Lead)
async def update_existing_lead(
    lead_in: schemas.LeadUpdate,
    lead: models.Lead = LeadAccessDep,
    # Lấy current_user từ Casbin check hoặc get_current_user
    current_user: models.User = PermissionDep, # <<< LẤY USER TỪ DEPENDENCY
    db: AsyncSession = Depends(database.get_db),
):
    """Cập nhật một Lead (chỉ Admin/Manager)."""
    # <<< SỬA Ở ĐÂY: Truyền current_user vào service >>>
    return await lead_service.update_lead(db, lead.id, lead_in, updated_by=current_user)


@router.post(
    "/{lead_id}/consultations",
    response_model=schemas.Consultation,
    status_code=status.HTTP_201_CREATED,
)
async def add_new_consultation(
    consultation_in: schemas.ConsultationCreate,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Thêm một ghi chú tư vấn mới cho Lead (Đã xác thực 2 lớp)."""
    # Service 'add_consultation' có logic check quyền sở hữu
    # nhưng check ở đây vẫn an toàn hơn
    return await lead_service.add_consultation(
        db, lead.id, current_user.id, consultation_in
    )


@router.post("/{lead_id}/assign", response_model=schemas.Lead)
async def assign_lead_manually(
    assign_data: schemas.AssignLead,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin/Manager only) Gán thủ công một Lead (Đã xác thực 2 lớp)."""
    return await lead_service.assign_lead_manually(
        db, lead.id, assign_data.officer_id, current_user
    )

@router.post("/{lead_id}/action", response_model=schemas.Lead)
async def perform_lead_action(
    action_data: schemas.LeadAction,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Xử lý hành động (reject/reassign) của Officer (Đã xác thực 2 lớp)."""
    return await lead_service.process_officer_action(
        db, lead.id, current_user, action_data.action, action_data.reason
    )


@router.get("/{lead_id}/timeline", response_model=List[schemas.TimelineItem])
async def get_lead_timeline(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy lịch sử tổng hợp (timeline) của một Lead (Đã xác thực quyền)."""
    return await lead_service.get_lead_timeline(db, lead.id)


@router.get("/{lead_id}/insights", response_model=schemas.LeadInsights)
async def get_lead_insights(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    db: AsyncSession = Depends(database.get_db),
):
    """Lấy các chỉ số insight 360 độ của một Lead (Đã xác thực quyền)."""
    timeline = await lead_service.get_lead_timeline(db, lead.id)
    return await insights_service.get_lead_insights(db, lead, timeline)


@router.delete(
    "/{lead_id}/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_a_consultation(
    consultation_id: int,
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (IDOR Check)
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI (Casbin Check)
    db: AsyncSession = Depends(database.get_db),
):
    """(Admin only) Xóa một ghi chú tư vấn (Đã xác thực 2 lớp)."""
    await lead_service.delete_consultation(db, lead.id, consultation_id, current_user)
    return None
```


## 📄 `routers\organization.py`

**Lines:** 34 | **Size:** 1117 bytes

```python
# app/routers/organization.py
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas
from ..core import deps
from ..services import organization_service

router = APIRouter(tags=["Organization"])


@router.get("/organization-units", response_model=List[schemas.OrganizationUnit])
async def get_all_organization_units(
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách tất cả các đơn vị."""
    return await organization_service.get_all_organization_units(db)


@router.get("/majors", response_model=List[schemas.Major])
async def get_filtered_majors(
    unitId: int,
    search: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách ngành học, lọc theo unitId và tìm kiếm."""
    return await organization_service.get_majors_by_unit_tree(
        db, unit_id=unitId, search_term=search
    )

```


## 📄 `routers\pipeline.py`

**Lines:** 23 | **Size:** 975 bytes

```python
# app/routers/pipeline.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas, models
from ..core import deps
from ..services import pipeline_service

router = APIRouter(tags=["Pipeline"])

PermissionDep = Depends(deps.check_permission)

@router.get("/all", response_model=schemas.FullPipeline)
async def get_full_pipeline(
    db: AsyncSession = Depends(database.get_db),
    # <<< SỬA Ở ĐÂY: Đổi dependency để kiểm tra quyền >>>
    current_user: models.User = PermissionDep, # Yêu cầu Casbin check
    # Hoặc dùng: current_user: models.User = deps.OfficerRequired, # Nếu chỉ officer trở lên
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}
```


## 📄 `routers\profile.py`

**Lines:** 77 | **Size:** 3025 bytes

```python
# app/routers/profile.py
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError  # <-- BỔ SUNG TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, services
from ..core import deps

router = APIRouter(tags=["Profile"])
PermissionDep = Depends(deps.check_permission)

@router.get("", response_model=schemas.User)
async def read_current_user_profile(
    current_user: models.User = PermissionDep, # <-- THAY ĐỔI
):
    """
    Lấy thông tin profile của chính người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền GET /api/profile)
    """
    return current_user


# === HÀM ĐÃ ĐƯỢỢC CẬP NHẬT ===
@router.put("", response_model=schemas.User)
async def update_current_user_profile(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
):
    """
    Cập nhật thông tin profile cho người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền PUT /api/profile)
    """
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()

    # --- SỬA LỖI LOGIC TẠI ĐÂY ---
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)
            
            # Chỉ kiểm tra DB nếu email thực sự thay đổi
            if valid_email != current_user.email:
                existing_user = await services.user_service.get_user_by_email(
                    db, valid_email
                )
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
                update_dict["email"] = valid_email
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
    # --- KẾT THÚC SỬA LỖI ---
    
    update_data = schemas.UserUpdate(**update_dict)

    updated_user = await services.user_service.update_profile(
        db, db_user=current_user, user_in=update_data, avatar_file=avatar
    )
    return updated_user

```


## 📄 `routers\sessions.py`

**Lines:** 218 | **Size:** 6554 bytes

```python
# app/routers/sessions.py
"""
API endpoints for managing user sessions.
Allows users to view active sessions, revoke specific sessions, and revoke all other sessions.
"""
from typing import List, Optional

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security  # ✅ FIX: Import security from app, not app.core
from ..core import deps
from ..services import session_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=schemas.UserSessionListResponse)
async def get_active_sessions(
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
    refresh_token: Optional[str] = Cookie(None, alias="refresh_token"),  # ✅ SECURITY FIX: Read from HttpOnly cookie
):
    """
    Get all active sessions for the current user.

    Returns:
        List of active sessions with device info, IP address, and last activity.

    Security:
        - Requires authentication
        - Users can only see their own sessions
        - Current session is identified by refresh token cookie
    """
    await log.info("Fetching active sessions", user_id=current_user.id)

    # ✅ SECURITY FIX: Identify current session from refresh token cookie
    current_refresh_jti = None
    if refresh_token:
        try:
            payload = security.decode_token(refresh_token)
            current_refresh_jti = payload.get("jti")
            await log.info("Current session identified", refresh_jti=current_refresh_jti)
        except Exception as e:
            await log.warning("Failed to decode refresh token for session identification", error=str(e))
            # Continue without marking current session

    try:
        sessions = await session_service.get_active_sessions(
            db,
            current_user.id,
            current_refresh_jti=current_refresh_jti  # Pass current JTI to mark current session
        )

        await log.info(
            "Active sessions retrieved",
            user_id=current_user.id,
            session_count=len(sessions)
        )

        # Mark current session in response
        current_session_id = None
        for session in sessions:
            if current_refresh_jti and session.refresh_jti == current_refresh_jti:
                session.is_current = True
                current_session_id = session.id

        return schemas.UserSessionListResponse(
            sessions=sessions,
            total=len(sessions),
            current_session_id=current_session_id
        )
    
    except Exception as e:
        await log.error(
            "Failed to fetch active sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions"
        )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: int,
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke a specific session.

    Args:
        session_id: ID of the session to revoke

    Security:
        - Requires authentication
        - Users can only revoke their own sessions

    Raises:
        404: Session not found or doesn't belong to user
    """
    await log.info(
        "Revoking session",
        user_id=current_user.id,
        session_id=session_id
    )

    try:
        success = await session_service.revoke_session(
            db=db,
            session_id=session_id,
            user_id=current_user.id
        )

        if not success:
            await log.warning(
                "Session not found or already revoked",
                user_id=current_user.id,
                session_id=session_id
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already revoked"
            )

        await log.info(
            "Session revoked successfully",
            user_id=current_user.id,
            session_id=session_id
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        await log.error(
            "Failed to revoke session",
            user_id=current_user.id,
            session_id=session_id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke session"
        )


@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_other_sessions(
    current_session_id: int = None,  # Optional: ID of current session to preserve
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke all sessions except optionally the current one.

    Args:
        current_session_id: Optional ID of session to preserve (usually current session)

    Useful when:
        - User suspects account compromise
        - User wants to logout from all other devices
        - Security best practice after password change

    Security:
        - Requires authentication
        - Only revokes user's own sessions
        - Can optionally preserve current session

    Returns:
        204 No Content on success
    """
    await log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        preserve_session_id=current_session_id
    )

    try:
        revoked_count = await session_service.revoke_all_other_sessions(
            db=db,
            user_id=current_user.id,
            except_session_id=current_session_id
        )

        await log.info(
            "All other sessions revoked",
            user_id=current_user.id,
            revoked_count=revoked_count
        )

        return None  # 204 No Content

    except Exception as e:
        await log.error(
            "Failed to revoke all other sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke sessions"
        )





```


## 📄 `routers\users.py`

**Lines:** 18 | **Size:** 488 bytes

```python
# app/routers/users.py
from fastapi import APIRouter

from .. import models, schemas
from ..core import deps

router = APIRouter(tags=["Users"])


@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = deps.CurrentUser):
    """
    Lấy thông tin của chính người dùng đang đăng nhập.

    Endpoint này được bảo vệ. Bạn phải cung cấp một Bearer Token hợp lệ.
    """
    return current_user

```


## 📄 `schemas\__init__.py`

**Lines:** 76 | **Size:** 1775 bytes

```python
# flake8: noqa: F401
# app/schemas/__init__.py

# Giúp import dễ dàng hơn bằng cách "export" các schema quan trọng ra ngoài

# Schemas từ config.py
from .config import AssignmentConfig, ScoringConfig, SkillRule, SkillRuleCreate

# Schemas từ lead.py
from .lead import (
    AssignLead,
    Consultation,
    ConsultationCreate,
    Lead,
    LeadAction,
    LeadImportError,      # <-- Đảm bảo cái này cũng được export
    LeadImportResult,
    LeadCreate,
    LeadInsights,
    LeadsPage,
    LeadUpdate,
    TimelineItem,
    AssignmentLog,
    BulkAssignLeadsSchema # <-- THÊM DÒNG NÀY
)

# Schemas từ organization.py
from .organization import (
    Major,
    MajorCreate,
    MajorUpdate,
    OrganizationUnit,
    OrganizationUnitCreate,
    OrganizationUnitUpdate,
    OrganizationUnitShallow # Đảm bảo export cả Shallow
)

# Schemas từ pipeline.py
from .pipeline import (
    ConsultationStatus,
    ConsultationStatusCreate,
    ConsultationStatusUpdate,
    FullPipeline,
    PipelineStage,
    PipelineStageCreate,
    PipelineStageUpdate,
)

# Schemas từ user.py
from .user import (
    AdminSetPasswordSchema,
    AdminUserCreate,
    BulkActionSchema,
    ChangePasswordSchema,
    ForgotPasswordSchema,
    LoginSchema,
    RefreshTokenRequest,
    ResetPasswordSchema,
    Token,
    TokenData,
    User,
    UserCreate,
    UsersPage,
    UserUpdate,
)

# Schemas từ user_session.py
from .user_session import (
    UserSessionCreate,
    UserSessionUpdate,
    UserSessionResponse,
    UserSessionListResponse,
)

# Schemas từ permissions.py (Nếu có, như trong file testing.md)
from .permissions import PolicyCreate, RoleAssignment
```


## 📄 `schemas\config.py`

**Lines:** 29 | **Size:** 554 bytes

```python
# app/schemas/config.py
from typing import Dict, Any, Optional

from pydantic import BaseModel, ConfigDict


class AssignmentConfig(BaseModel):
    params: Optional[Dict[str, Any]] = None # Có thể là None hoặc dict


class ScoringConfig(BaseModel):
    params: Any


class SkillRuleBase(BaseModel):
    lead_attribute: str
    attribute_value: str
    required_skill: str


class SkillRuleCreate(SkillRuleBase):
    pass


class SkillRule(SkillRuleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

```


## 📄 `schemas\lead.py`

**Lines:** 148 | **Size:** 3869 bytes

```python
# app/schemas/lead.py
from datetime import datetime
from typing import List, Dict, Literal, Optional, Union, Any

from pydantic import BaseModel, EmailStr, ConfigDict, Field

from .organization import Major, OrganizationUnitShallow
from .pipeline import ConsultationStatus, PipelineStage

# Import các schema cần thiết để lồng vào
from .user import User

# -----------------
# SCHEMAS HÀNH ĐỘNG VÀ DỮ LIỆU PHỤ
# -----------------


class ConsultationBase(BaseModel):
    method: str
    notes: str
    outcome: Optional[str] = None
    duration_minutes: Optional[int] = None


class ConsultationCreate(ConsultationBase):
    status_id: str


class Consultation(ConsultationBase):
    id: int
    consultation_date: datetime
    officer_id: int
    consultation_status_id: Optional[str] = None
    officer: Optional[User] = None
    consultation_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True)


class AssignmentLog(BaseModel):
    id: int
    method: Optional[str] = None
    timestamp: datetime
    reason: Optional[str] = None
    officer_id: int
    officer: Optional[User] = None

    model_config = ConfigDict(from_attributes=True)


class TimelineItem(BaseModel):
    type: Literal["consultation", "assignment"]
    timestamp: datetime
    data: Union[Consultation, AssignmentLog]


class LeadInsights(BaseModel):
    engagement_score: int
    fit_score: int
    urgency_score: int
    overall_score: int
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class AssignLead(BaseModel):
    officer_id: int


class LeadAction(BaseModel):
    action: Literal["reject", "reassign"]
    reason: str


# -----------------
# SCHEMAS CHÍNH CỦA LEAD
# -----------------


class LeadBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    source: str
    unit_id: int
    major_id: Optional[int] = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    unit_id: Optional[int] = None
    major_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    education_level: Optional[str] = None
    gpa: Optional[float] = None
    location: Optional[str] = None
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class Lead(LeadBase):
    id: int
    status: str
    lead_score: int
    created_at: datetime
    updated_at: datetime
    assigned_at: Optional[datetime] = None
    assigned_officer_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    pipeline_stage_id: Optional[str] = None

    major: Optional[Major] = None
    # THAY ĐỔI Ở ĐÂY: Sử dụng OrganizationUnitShallow
    unit: Optional[OrganizationUnitShallow] = None
    assigned_officer: Optional[User] = None
    pipeline_stage: Optional[PipelineStage] = None
    consultation_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True)


class LeadsPage(BaseModel):
    total_count: int
    leads: List[Lead]


class BulkAssignLeadsSchema(BaseModel):
    lead_ids: List[int] = Field(..., min_length=1)


class LeadImportError(BaseModel):
    row_number: int # Số dòng trong file gốc (bắt đầu từ 1 hoặc 2 tùy header)
    error_message: str
    row_data: Optional[Dict[str, Any]] = None # Dữ liệu gốc của dòng bị lỗi (tùy chọn)

class LeadImportResult(BaseModel):
    total_rows_processed: int
    successful_imports: int
    failed_imports: int
    created_lead_ids: List[int] = []
    errors: List[LeadImportError] = []
```


## 📄 `schemas\organization.py`

**Lines:** 76 | **Size:** 2033 bytes

```python
# app/schemas/organization.py
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


# --- Schemas cho Major (Không đổi) ---
class MajorBase(BaseModel):
    name: str
    code: str
    unit_id: int


class MajorCreate(MajorBase):
    pass


class MajorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    unit_id: Optional[int] = None


class Major(MajorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# --- TÁI CẤU TRÚC HOÀN TOÀN SCHEMAS CHO ORGANIZATIONUNIT ---


# Bước 1: Tạo một schema "Nông" (Shallow) không có bất kỳ quan hệ nào.
# Schema này sẽ được sử dụng bên trong các quan hệ lồng nhau để phá vỡ vòng lặp.
class OrganizationUnitShallow(BaseModel):
    id: int
    name: str
    type: str
    parent_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# Bước 2: Tạo schema Create/Update không cần quan hệ lồng nhau.
class OrganizationUnitCreate(BaseModel):
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


class OrganizationUnitUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


# Bước 3: Tạo schema "Sâu" (Deep) để trả về cho API.
# Schema này sẽ sử dụng schema "Nông" cho các thuộc tính đệ quy.
class OrganizationUnit(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = None

    # === ĐÂY LÀ PHẦN SỬA LỖI QUAN TRỌNG NHẤT ===
    parent: Optional[OrganizationUnitShallow] = None
    children: List[OrganizationUnitShallow] = []
    # === KẾT THÚC SỬA LỖI ===

    majors: List[Major] = []

    model_config = ConfigDict(from_attributes=True)

```


## 📄 `schemas\permissions.py`

**Lines:** 19 | **Size:** 788 bytes

```python
# app/schemas/permissions.py
from pydantic import BaseModel, Field

class Policy(BaseModel):
    """Schema để đọc một policy."""
    subject: str
    object: str
    action: str

class PolicyCreate(BaseModel):
    """Schema để tạo một policy mới."""
    subject: str = Field(..., description="Chủ thể, vd: 'role:manager' hoặc 'user:123'")
    object: str = Field(..., description="Đối tượng, vd: '/api/leads/*' hoặc '/api/admin/users'")
    action: str = Field(..., description="Hành động, vd: 'GET', 'POST', '*'")

class RoleAssignment(BaseModel):
    """Schema để gán vai trò cho người dùng."""
    user_id: int = Field(..., gt=0)
    role: str = Field(..., description="Vai trò (đã có tiền tố), vd: 'role:officer'")
```


## 📄 `schemas\pipeline.py`

**Lines:** 58 | **Size:** 1600 bytes

```python
# app/schemas/pipeline.py
from typing import List, Optional  # <-- THÊM Optional

from pydantic import BaseModel, Field, ConfigDict


# --- Schemas cho PipelineStage ---

class PipelineStageBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    order: int = Field(..., gt=0)


class PipelineStageCreate(PipelineStageBase):
    id: str = Field(..., min_length=3, max_length=50)


class PipelineStageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    order: Optional[int] = Field(None, gt=0)


class PipelineStage(PipelineStageBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schemas cho ConsultationStatus ---

class ConsultationStatusBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    color_code: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")  # Validate mã màu HEX
    stage_id: str


class ConsultationStatusCreate(ConsultationStatusBase):
    id: str = Field(..., min_length=3, max_length=50)


class ConsultationStatusUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    color_code: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    stage_id: Optional[str] = None


class ConsultationStatus(ConsultationStatusBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schema chung ---

class FullPipeline(BaseModel):
    # Dùng schema PipelineStage và ConsultationStatus
    stages: List[PipelineStage]
    statuses: List[ConsultationStatus]
```


## 📄 `schemas\user.py`

**Lines:** 176 | **Size:** 4799 bytes

```python
# NOTE: Các schema này được sử dụng cho các endpoint của /auth
# app/schemas/user.py
# NOTE: Các schema này được sử dụng cho các endpoint của /auth
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, constr, field_validator, model_validator, ConfigDict


# === TÁCH LOGIC RA HÀM RIÊNG ĐỂ TÁI SỬ DỤNG ===
def validate_password_strength_logic(v: str) -> str:
    """Hàm helper chứa logic kiểm tra độ mạnh mật khẩu."""
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[@$!%*?&]", v):
        raise ValueError("Password must contain at least one special character")
    return v


# === KẾT THÚC TÁCH LOGIC ===

PasswordStr = constr(min_length=8, strip_whitespace=True)


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    status: str


class UserCreate(BaseModel):
    """
    Schema cho user registration.
    backend chỉ cần nhận username, email, password, full_name.
    """
    username: str
    email: EmailStr
    password: PasswordStr
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class ResetPasswordSchema(BaseModel):
    """
    Schema cho reset password endpoint.
    backend chỉ cần nhận token và new_password.
    """
    token: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class ChangePasswordSchema(BaseModel):
    """
    Schema cho change password endpoint.
    backend chỉ cần nhận old_password và new_password.
    """
    old_password: str
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class AdminSetPasswordSchema(BaseModel):
    """
    Schema cho admin set password endpoint.
    backend chỉ cần nhận new_password.
    """
    new_password: PasswordStr

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Validate password strength
        return validate_password_strength_logic(v)


class BulkActionSchema(BaseModel):
    """Schema để validate hành động hàng loạt."""

    action: Literal["delete", "change_status"]
    user_ids: List[int]
    status: Optional[Literal["active", "pending", "banned"]] = None

    @model_validator(mode="after")
    def check_status_for_change_status_action(self) -> "BulkActionSchema":
        if self.action == "change_status" and self.status is None:
            raise ValueError("Status is required for 'change_status' action.")
        return self


# --- Các schema còn lại không đổi ---


class AdminUserCreate(UserCreate):
    role: str = "user"
    status: str = "active"


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    max_capacity: Optional[int] = None
    skills: Optional[List[str]] = None


class UsersPage(BaseModel):
    total_count: int
    users: List["User"]


class User(UserBase):
    id: int
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None
    unit_id: Optional[int] = None
    skills: Optional[List[str]] = None
    availability_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserBase):
    id: int
    password_hash: str

    model_config = ConfigDict(from_attributes=True)


class LoginSchema(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class RefreshTokenRequest(BaseModel):
    """Schema cho request body của endpoint /refresh."""

    refresh_token: str

```


## 📄 `schemas\user_session.py`

**Lines:** 61 | **Size:** 1797 bytes

```python
# app/schemas/user_session.py
"""
Pydantic schemas for UserSession model.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserSessionBase(BaseModel):
    """Base schema for UserSession."""
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class UserSessionCreate(UserSessionBase):
    """Schema for creating a new session."""
    user_id: int
    refresh_jti: str = Field(..., min_length=36, max_length=36)
    expires_at: datetime
    is_suspicious: bool = False


class UserSessionUpdate(BaseModel):
    """Schema for updating session (mainly last_activity_at and refresh_jti)."""
    refresh_jti: Optional[str] = Field(None, min_length=36, max_length=36)
    last_activity_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class UserSessionResponse(UserSessionBase):
    """Schema for returning session data to client."""
    id: int
    user_id: int
    refresh_jti: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    is_suspicious: bool
    revoked_at: Optional[datetime] = None
    
    # Computed fields
    is_active: bool = Field(default=True, description="Whether session is active (not revoked and not expired)")
    is_current: bool = Field(default=False, description="Whether this is the current session")
    
    model_config = ConfigDict(from_attributes=True)


class UserSessionListResponse(BaseModel):
    """Schema for returning list of sessions."""
    sessions: list[UserSessionResponse]
    total: int
    current_session_id: Optional[int] = None


```


## 📄 `security.py`

**Lines:** 125 | **Size:** 3763 bytes

```python
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
```


## 📄 `services\__init__.py`

**Lines:** 16 | **Size:** 572 bytes

```python
# flake8: noqa: F401
# app/services/__init__.py

# Dòng này sẽ import các module vào package services,
# giúp chúng ta có thể gọi `services.user_service`, `services.insights_service`...
# hực hiện đúng vai trò của mình là điều phối request đến service và trả về response, đồng thời xử lý các validation đầu vào cơ bản và phân quyền
from . import (
    assignment_service,
    config_service,
    insights_service,
    lead_service,
    organization_service,
    pipeline_service,
    user_service,
)

```


## 📄 `services\anomaly_detection.py`

**Lines:** 307 | **Size:** 9403 bytes

```python
# app/services/anomaly_detection.py
"""
Anomaly detection service for identifying suspicious login activities.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models

log = structlog.get_logger(__name__)


class AnomalyDetector:
    """
    Detects suspicious login patterns and anomalies.
    """
    
    # Thresholds for anomaly detection
    MAX_FAILED_LOGINS_PER_HOUR = 5
    MAX_SESSIONS_PER_USER = 10
    SUSPICIOUS_COUNTRY_CHANGE_HOURS = 2  # Hours between logins from different countries
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def check_new_ip_address(
        self,
        user_id: int,
        ip_address: Optional[str]
    ) -> bool:
        """
        Check if this IP address has been used before by this user.
        
        Args:
            user_id: User ID
            ip_address: IP address to check
        
        Returns:
            True if this is a new IP address, False otherwise
        """
        if not ip_address:
            return False
        
        # Query for any previous session from this IP
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.ip_address == ip_address,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()
        
        is_new = existing_session is None
        
        if is_new:
            await log.warning(
                "New IP address detected",
                user_id=user_id,
                ip_address=ip_address
            )
        
        return is_new
    
    async def check_new_device(
        self,
        user_id: int,
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str]
    ) -> bool:
        """
        Check if this device/browser/OS combination is new for this user.
        
        Args:
            user_id: User ID
            device_type: Device type (PC, Mobile, Tablet)
            browser: Browser name
            os: Operating system
        
        Returns:
            True if this is a new device combination
        """
        if not all([device_type, browser, os]):
            return False
        
        # Query for any previous session with same device fingerprint
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.device_type == device_type,
                    models.UserSession.browser == browser,
                    models.UserSession.os == os,
                )
            )
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()
        
        is_new = existing_session is None
        
        if is_new:
            await log.warning(
                "New device detected",
                user_id=user_id,
                device_type=device_type,
                browser=browser,
                os=os
            )
        
        return is_new
    
    async def check_impossible_travel(
        self,
        user_id: int,
        current_country: Optional[str],
        current_city: Optional[str]
    ) -> bool:
        """
        Detect impossible travel: login from different countries in short time.
        
        This is a simplified version. In production, you would:
        - Calculate actual distance between locations
        - Consider realistic travel time
        - Use geolocation APIs
        
        Args:
            user_id: User ID
            current_country: Current login country
            current_city: Current login city
        
        Returns:
            True if impossible travel detected
        """
        if not current_country:
            return False
        
        # Get most recent session (within last N hours)
        time_threshold = datetime.now(timezone.utc) - timedelta(
            hours=self.SUSPICIOUS_COUNTRY_CHANGE_HOURS
        )
        
        result = await self.db.execute(
            select(models.UserSession)
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.created_at >= time_threshold,
                    models.UserSession.country.isnot(None),
                    models.UserSession.country != current_country
                )
            )
            .order_by(models.UserSession.created_at.desc())
            .limit(1)
        )
        recent_session = result.scalar_one_or_none()
        
        if recent_session:
            await log.warning(
                "Impossible travel detected",
                user_id=user_id,
                previous_country=recent_session.country,
                current_country=current_country,
                time_diff_hours=(
                    datetime.now(timezone.utc) - recent_session.created_at
                ).total_seconds() / 3600
            )
            return True
        
        return False
    
    async def check_excessive_sessions(self, user_id: int) -> bool:
        """
        Check if user has too many active sessions.
        
        Args:
            user_id: User ID
        
        Returns:
            True if user has excessive active sessions
        """
        result = await self.db.execute(
            select(func.count(models.UserSession.id))
            .where(
                and_(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None)
                )
            )
        )
        session_count = result.scalar()
        
        is_excessive = session_count >= self.MAX_SESSIONS_PER_USER
        
        if is_excessive:
            await log.warning(
                "Excessive active sessions detected",
                user_id=user_id,
                session_count=session_count,
                threshold=self.MAX_SESSIONS_PER_USER
            )
        
        return is_excessive
    
    async def check_unusual_login_time(
        self,
        user_id: int,
        login_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if login time is unusual compared to user's typical pattern.
        
        This is a simplified version. In production, you would:
        - Build user behavior profile
        - Detect logins outside typical hours
        - Consider timezone
        
        Args:
            user_id: User ID
            login_time: Login timestamp (default: now)
        
        Returns:
            True if login time is unusual
        """
        if login_time is None:
            login_time = datetime.now(timezone.utc)
        
        # Get user's typical login hours (simplified: just check if night time)
        hour = login_time.hour
        
        # Consider 2 AM - 6 AM as unusual (this is very simplified)
        is_unusual = 2 <= hour < 6
        
        if is_unusual:
            await log.info(
                "Unusual login time detected",
                user_id=user_id,
                hour=hour
            )
        
        return is_unusual
    
    async def analyze_login(
        self,
        user_id: int,
        ip_address: Optional[str],
        device_type: Optional[str],
        browser: Optional[str],
        os: Optional[str],
        country: Optional[str] = None,
        city: Optional[str] = None,
        login_time: Optional[datetime] = None
    ) -> Dict[str, bool]:
        """
        Comprehensive anomaly analysis for a login attempt.
        
        Args:
            user_id: User ID
            ip_address: IP address
            device_type: Device type
            browser: Browser name
            os: Operating system
            country: Country (optional)
            city: City (optional)
            login_time: Login timestamp (optional)
        
        Returns:
            Dictionary of anomaly flags:
            {
                "new_ip": bool,
                "new_device": bool,
                "impossible_travel": bool,
                "excessive_sessions": bool,
                "unusual_time": bool,
                "is_suspicious": bool  # True if ANY anomaly detected
            }
        """
        anomalies = {
            "new_ip": await self.check_new_ip_address(user_id, ip_address),
            "new_device": await self.check_new_device(user_id, device_type, browser, os),
            "impossible_travel": await self.check_impossible_travel(user_id, country, city),
            "excessive_sessions": await self.check_excessive_sessions(user_id),
            "unusual_time": await self.check_unusual_login_time(user_id, login_time),
        }
        
        # Mark as suspicious if ANY anomaly detected
        anomalies["is_suspicious"] = any(anomalies.values())
        
        if anomalies["is_suspicious"]:
            await log.warning(
                "Suspicious login detected",
                user_id=user_id,
                anomalies=anomalies
            )
        
        return anomalies


```


## 📄 `services\assignment_service.py`

**Lines:** 184 | **Size:** 10886 bytes

```python
# app/services/assignment_service.py
from datetime import datetime, timezone
import logging
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError # Dùng để bắt LockNotAvailableError
from celery.exceptions import Retry # Dùng để retry task

from .. import models
from ..config import settings

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)

ACTIVE_LEAD_STATUSES_FOR_WORKLOAD = settings.ACTIVE_LEAD_STATUSES_FOR_WORKLOAD

# Thêm tham số logger=None
async def automatically_assign_lead(lead_id: int, db: AsyncSession, logger: logging.Logger = None):
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.
    """
    log = logger or default_log
    await log.info(f"[Lead ID: {lead_id}] Auto-assign task started")

    try:
        # Sử dụng transaction lồng nhau để kiểm soát rollback tốt hơn
        async with db.begin_nested():
            # === BƯỚC 1: Lấy VÀ KHÓA Lead (Giữ nguyên nowait=True hoặc đổi sang skip_locked=True) ===
            # Việc khóa lead ít khi xung đột hơn, nhưng nowait giúp phát hiện sớm
            # nếu có transaction khác đang xử lý chính lead này.
            stmt = select(models.Lead).where(models.Lead.id == lead_id).with_for_update(nowait=True)
            result = await db.execute(stmt)
            lead = result.scalar_one_or_none()

            # --- Kiểm tra trạng thái Lead ---
            if not lead:
                await log.warning(f"[Lead ID: {lead_id}] Lead not found, skipping assignment.")
                return # Kết thúc task nếu lead không tồn tại
            elif lead.assigned_officer_id:
                await log.info(f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping.")
                return # Kết thúc task nếu lead đã được gán
            else:
                lead_unit_id = lead.unit_id
                await log.debug(f"[Lead ID: {lead_id}] Lead found and locked (Unit: {lead_unit_id}). Status: '{lead.status}'")

                # === BƯỚC 2: Khóa các Officer liên quan (SỬ DỤNG SKIP LOCKED) ===
                available_officers_query = (
                    select(models.User)
                    .where(
                        models.User.role == "officer",
                        models.User.status == "active",
                        models.User.availability_status == "available", # Chỉ lấy officer đang sẵn sàng
                        models.User.unit_id == lead_unit_id, # Cùng đơn vị với Lead
                    )
                    # ✅ CẢI TIẾN: Bỏ qua các officer đang bị khóa bởi transaction khác
                    .with_for_update(skip_locked=True)
                )
                officer_results = await db.execute(available_officers_query)
                # Lấy danh sách officer chưa bị khóa
                available_officers = officer_results.scalars().all()

                # --- Xử lý khi không có Officer ---
                if not available_officers:
                    await log.warning(f"[Lead ID: {lead_id}] No available (and unlocked) officers found for unit {lead_unit_id}. Setting status to unassigned.")
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # Ghi lại lịch sử thay đổi trạng thái (Optional nhưng nên có)
                    # await _log_lead_state_change(...) # Cần hàm helper này nếu muốn log
                    db.add(lead)
                    # Commit transaction lồng nhau ở đây vì đã kết thúc logic
                    # await db.commit() # Không cần commit tường minh khi dùng `async with`
                    return # Kết thúc task

                await log.debug(f"[Lead ID: {lead_id}] Found {len(available_officers)} available officers for unit {lead_unit_id}.")

                # === BƯỚC 3: TÍNH TOÁN WORKLOAD (Chỉ cho các officer lấy được) ===
                officer_ids = [o.id for o in available_officers]
                workload_stmt = (
                    select(models.Lead.assigned_officer_id, func.count(models.Lead.id).label("workload"))
                    .where(
                        models.Lead.assigned_officer_id.in_(officer_ids),
                        # Chỉ đếm các lead đang thực sự "active" trong workload
                        models.Lead.status.in_(ACTIVE_LEAD_STATUSES_FOR_WORKLOAD),
                    ).group_by(models.Lead.assigned_officer_id)
                )
                workload_results = await db.execute(workload_stmt)
                workload_map = {row.assigned_officer_id: row.workload for row in workload_results}
                await log.debug(f"[Lead ID: {lead_id}] Calculated workloads for available officers: {workload_map}")

                # === BƯỚC 4: Xây dựng Danh sách Officer Hợp lệ (còn capacity) ===
                officer_loads = []
                for officer in available_officers:
                    workload = workload_map.get(officer.id, 0)
                    # Kiểm tra capacity (đảm bảo max_capacity không phải None và > 0)
                    capacity = officer.max_capacity if officer.max_capacity is not None else 100 # Giá trị mặc định an toàn
                    if capacity <= 0: capacity = 1 # Tránh chia cho 0

                    if workload < capacity:
                        utilization = workload / capacity
                        officer_loads.append({
                            "officer": officer,
                            "workload": workload,
                            "utilization": utilization,
                            # Xử lý last_assigned_at là None (coalesce)
                            "last_assigned": officer.last_assigned_at or datetime.min.replace(tzinfo=timezone.utc),
                        })
                    else:
                         await log.debug(f"[Lead ID: {lead_id}] Officer {officer.id} skipped (at full capacity: {workload}/{capacity})")


                # --- Xử lý khi tất cả Officer đã đầy tải ---
                if not officer_loads:
                    await log.warning(f"[Lead ID: {lead_id}] All available officers ({len(available_officers)}) in unit {lead_unit_id} are at full capacity. Setting status to unassigned.")
                    lead.status = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
                    # await _log_lead_state_change(...)
                    db.add(lead)
                    # await db.commit()
                    return # Kết thúc task

                # === BƯỚC 5: Sắp xếp và Chọn Officer ===
                # Ưu tiên:
                # 1. Utilization thấp nhất (ít % đầy nhất)
                # 2. Capacity còn lại nhiều nhất (nếu utilization bằng nhau)
                # 3. Được gán lần cuối xa nhất (nếu cả 2 trên bằng nhau)
                officer_loads.sort(key=lambda x: (
                    x["utilization"],
                    -(x["officer"].max_capacity - x["workload"]) if x["officer"].max_capacity is not None else 0, # Ưu tiên người còn nhiều slot trống hơn
                    x["last_assigned"], # Sắp xếp theo datetime object
                ))

                chosen_officer_data = officer_loads[0]
                chosen_one = chosen_officer_data["officer"]
                chosen_workload = chosen_officer_data["workload"]
                await log.info(
                    f"[Lead ID: {lead_id}] Selected officer {chosen_one.id} ({chosen_one.username}). "
                    f"Current Workload: {chosen_workload}, Max Capacity: {chosen_one.max_capacity}, "
                    f"Utilization: {chosen_officer_data['utilization']:.2f}, "
                    f"Last Assigned: {chosen_officer_data['last_assigned']}"
                )

                # === BƯỚC 6: Gán Lead, Cập nhật Officer và Ghi Log Assignment ===
                now_utc = datetime.now(timezone.utc)
                lead.assigned_officer_id = chosen_one.id
                lead.assigned_at = now_utc
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

                chosen_one.last_assigned_at = now_utc

                log_entry = models.AssignmentLog(
                    lead_id=lead.id, # Lead ID chắc chắn đã có
                    officer_id=chosen_one.id,
                    method="automatic",
                    reason="Assigned by system (utilization routing)",
                    timestamp=now_utc,
                )

                # await _log_lead_state_change(...) # Ghi lại sự thay đổi trạng thái lead

                # Thêm tất cả các thay đổi vào session
                db.add_all([lead, chosen_one, log_entry])
                await log.info(f"[Lead ID: {lead_id}] Lead assignment successful to officer {chosen_one.id}.")

        # Kết thúc `async with db.begin_nested()` - Tự động commit nếu không có lỗi

    except OperationalError as e:
        # Bắt lỗi "LockNotAvailableError" (chủ yếu cho việc khóa Lead ban đầu)
        if "could not obtain lock" in str(e).lower() or "lock not available" in str(e).lower():
            await log.warning(f"[Lead ID: {lead_id}] Lock contention detected (possibly on Lead row). Retrying task in 5s...")
            # Ném lỗi Retry để Celery tự động thử lại task sau
            raise Retry(exc=e, countdown=5, max_retries=5) # Giới hạn số lần retry
        else:
            # Nếu là lỗi OperationalError khác (vd: mất kết nối), log và ném ra
            await log.error(f"[Lead ID: {lead_id}] OperationalError during transaction.", exc_info=True)
            # Rollback sẽ tự động xảy ra khi exception thoát khỏi `async with`
            raise e # Ném lại lỗi để Celery biết task thất bại
    except Exception as e:
        # Bất kỳ lỗi nào khác cũng sẽ được log và ném ra
        await log.error(f"[Lead ID: {lead_id}] Auto-assign task failed unexpectedly within transaction.", exc_info=True)
        # Rollback tự động
        raise e # Ném lại lỗi để Celery biết task thất bại

    await log.info(f"[Lead ID: {lead_id}] Auto-assign task finished successfully.")
```


## 📄 `services\config_service.py`

**Lines:** 206 | **Size:** 7456 bytes

```python
# app/services/config_service.py
import json  # 👈 *** ADD IMPORT ***
from typing import Any, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas

# 👈 *** ADD REDIS IMPORTS ***
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..utils.exceptions import ResourceNotFoundError

log = structlog.get_logger(__name__)

# === ⭐️ CONFIGURATION CACHE SETTINGS ⭐️ ===
CONFIG_CACHE_TTL_SECONDS = 3600  # Cache config for 1 hour


async def get_assignment_config(db: AsyncSession, unit_id: int) -> dict:
    """
    Lấy cấu hình phân chia của một đơn vị.
    ✅ FIXED: Uses Redis Cache-Aside pattern.
    """
    cache_key = f"config:assignment:{unit_id}"
    await log.debug("Fetching assignment config", unit_id=unit_id, cache_key=cache_key) # THÊM await

    # 1. Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            await log.debug("Cache hit for assignment config", unit_id=unit_id) # THÊM await
            return json.loads(cached_data)
    except Exception as e_redis_get:
        # Log error but proceed to DB query (fail-open)
        await log.error( # THÊM await
            "Failed to get assignment config from cache",
            unit_id=unit_id,
            error=str(e_redis_get),
        )

    await log.debug("Cache miss for assignment config, querying DB", unit_id=unit_id) # THÊM await
    # 2. Cache Miss: Query DB
    config = await db.scalar(
        select(models.OfficerAssignmentConfig).where(
            models.OfficerAssignmentConfig.unit_id == unit_id
        )
    )
    
    # === TÁCH KIỂM TRA ===
    if not config:
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found."
        )
    
    # Kiểm tra params (cột JSON có thể cần truy cập)
    config_params = config.params
    
    if not config_params: # Nếu params là None hoặc {}
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found or has no params."
        )
    # === KẾT THÚC TÁCH ===

    # 3. Store in cache
    try:
        await safe_redis_set(
            cache_key, json.dumps(config_params), ex=CONFIG_CACHE_TTL_SECONDS
        )
        await log.debug( # THÊM await
            "Stored assignment config in cache",
            unit_id=unit_id,
            ttl=CONFIG_CACHE_TTL_SECONDS,
        )
    except Exception as e_redis_set:
        await log.error( # THÊM await
            "Failed to set assignment config in cache",
            unit_id=unit_id,
            error=str(e_redis_set),
        )

    return config_params


async def update_assignment_config(
    db: AsyncSession, unit_id: int, params: Any
) -> models.OfficerAssignmentConfig:
    """
    Cập nhật cấu hình phân chia của một đơn vị.
    Sử dụng commit/rollback tường minh.
    """
    cache_key = f"config:assignment:{unit_id}"
    try:
        # Logic tìm hoặc tạo config
        config = await db.scalar(
            select(models.OfficerAssignmentConfig)
            .where(models.OfficerAssignmentConfig.unit_id == unit_id)
            .with_for_update()  # Lock the row
        )
        
        if not config:
            unit = await db.get(models.OrganizationUnit, unit_id)
            if not unit:
                raise ResourceNotFoundError(
                    detail=f"Organization Unit with id {unit_id} not found."
                )
            config = models.OfficerAssignmentConfig(unit_id=unit_id, params=params)
            await log.info("Creating new assignment config", unit_id=unit_id)
        else:
            config.params = params
            await log.info("Updating existing assignment config", unit_id=unit_id)

        db.add(config)
        
        # === THAY ĐỔI CHÍNH ===
        # 1. Commit thay đổi vào DB
        await db.commit()
        # 2. Refresh để load lại cột 'params' sau khi commit
        # (Chỉ định rõ 'params' để đảm bảo nó được load)
        await db.refresh(config, attribute_names=['params'])
        
        config_to_return = config
        # === KẾT THÚC THAY ĐỔI ===

        # --- Invalidate Cache SAU KHI DB commit thành công ---
        try:
            deleted_count = await safe_redis_delete(cache_key)
            if deleted_count > 0:
                await log.info("Invalidated assignment config cache", unit_id=unit_id)
            else:
                await log.debug("No assignment config cache to invalidate", unit_id=unit_id)
        except Exception as e_redis_del:
            await log.error(
                "Failed to invalidate assignment config cache after update",
                unit_id=unit_id,
                error=str(e_redis_del),
            )

        return config_to_return

    except Exception as e:
        await db.rollback() # Rollback nếu có lỗi TRƯỚC KHI commit
        await log.error(
            "Failed to update assignment config",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e # Ném lại lỗi (ví dụ: ResourceNotFoundError)


# --- Skill Rules (Consider caching if needed) ---


async def get_all_skill_rules(db: AsyncSession) -> List[models.SkillRequirementRule]:
    # NOTE: Caching this might be complex due to potential updates.
    # If this list is large and frequently accessed, consider Redis caching
    # with appropriate invalidation when rules are created/deleted.
    # For now, let's keep it simple.
    result = await db.execute(select(models.SkillRequirementRule))
    return result.scalars().all()


async def create_skill_rule(
    db: AsyncSession, rule_in: schemas.SkillRuleCreate
) -> models.SkillRequirementRule:
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = models.SkillRequirementRule(**rule_in.model_dump())
        db.add(db_rule)
        await db.commit()
        await db.refresh(db_rule)
        # Invalidate cache for get_all_skill_rules if implemented
        # await safe_redis_delete("config:all_skill_rules")
        return db_rule
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create skill rule",
            rule=rule_in.model_dump_json(),
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_skill_rule(db: AsyncSession, rule_id: int):
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = await db.get(models.SkillRequirementRule, rule_id)
        if not db_rule:
            raise ResourceNotFoundError(
                detail=f"Skill rule with id {rule_id} not found."
            )
        await db.delete(db_rule)
        await db.commit()
        # Invalidate cache for get_all_skill_rules if implemented
        # await safe_redis_delete("config:all_skill_rules")
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete skill rule", rule_id=rule_id, error=str(e), exc_info=True
        )
        raise e

```


## 📄 `services\insights_service.py`

**Lines:** 227 | **Size:** 8543 bytes

```python
# app/services/insights_service.py
from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy import select  # <-- THÊM select
from sqlalchemy import func, case
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import settings

log = structlog.get_logger(__name__)


async def _calculate_engagement_score(db: AsyncSession, lead_id: int) -> int:
    """
    Tính điểm tương tác.
    ✅ FIXED: Tổng hợp (Aggregate) tại CSDL, chỉ trả về 1 hàng.
    """
    score = 0
    points_config = settings.LEAD_SCORING_ENGAGEMENT_POINTS
    now = datetime.now(timezone.utc)

    # === BẮT ĐẦU TỐI ƯU HÓA ===
    # 1. Xây dựng truy vấn tổng hợp
    
    # Định nghĩa các trường hợp (case) cho điểm
    outcome_score_case = case(
        (models.Consultation.outcome == "successful", points_config["outcome"]["successful"]),
        (models.Consultation.outcome == "follow-up", points_config["outcome"]["follow-up"]),
        (models.Consultation.outcome == "failed", points_config["outcome"]["failed"]),
        else_=0
    )
    
    method_score_case = case(
        (models.Consultation.method == "meeting", points_config["method"]["meeting"]),
        (models.Consultation.method == "call", points_config["method"]["call"]),
        (models.Consultation.method == "email", points_config["method"]["email"]),
        else_=0
    )
    
    duration_score_calc = (
        (models.Consultation.duration_minutes // 10) * points_config["duration_bonus_per_10_min"]
    )

    # Truy vấn tổng hợp
    stmt = (
        select(
            func.count(models.Consultation.id).label("total_count"),
            func.sum(outcome_score_case).label("total_outcome_score"),
            func.sum(method_score_case).label("total_method_score"),
            func.sum(duration_score_calc).label("total_duration_score"),
            func.max(models.Consultation.consultation_date).label("last_consultation_date")
        )
        .where(
            models.Consultation.lead_id == lead_id,
            models.Consultation.consultation_date <= now,
            models.Consultation.duration_minutes.between(0, 480)
        )
    )

    # 2. Thực thi truy vấn (chỉ trả về 1 hàng)
    result = await db.execute(stmt)
    agg_data = result.one_or_none()
    # === KẾT THÚC TỐI ƯU HÓA ===

    if not agg_data or agg_data.total_count == 0:
        return 0

    # 3. Logic tính toán (giờ đã cực kỳ đơn giản)
    score += agg_data.total_count * points_config["consultation_count_multiplier"]
    score += (agg_data.total_outcome_score or 0)
    score += (agg_data.total_method_score or 0)
    score += (agg_data.total_duration_score or 0)


    # 4. Tính phạt (sử dụng dữ liệu đã lấy)
    last_consultation_date = agg_data.last_consultation_date
    if last_consultation_date:
        if last_consultation_date.tzinfo is None:
            last_consultation_date = last_consultation_date.replace(tzinfo=timezone.utc)

        days_since_last_contact = (now - last_consultation_date).days
        if days_since_last_contact > 3:
            penalty = abs(points_config["inactivity_penalty_per_day"])
            score -= (days_since_last_contact - 3) * penalty

    return max(0, min(score, points_config["max_score"]))


def _calculate_fit_score(lead: models.Lead) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_FIT_POINTS
    score += points_config["source"].get(lead.source, 0)
    if lead.gpa:
        for threshold, points in sorted(
            points_config["gpa_thresholds"].items(), reverse=True
        ):
            if lead.gpa >= threshold:
                score += points
                break
    if lead.education_level:
        score += points_config["education_level"].get(lead.education_level, 0)
    if lead.location:
        score += points_config["location"].get(lead.location, 0)
    return max(0, min(score, points_config["max_score"]))


def _calculate_urgency_score(
    lead: models.Lead, timeline: List[dict]
) -> int:
    # ... (Hàm này giữ nguyên, không thay đổi) ...
    score = 0
    points_config = settings.LEAD_SCORING_URGENCY_POINTS
    if hasattr(lead, "pipeline_stage") and lead.pipeline_stage:
        score += lead.pipeline_stage.order * points_config["stage_order_multiplier"]
    else:
        initial_stage_order = 1
        score += initial_stage_order * points_config["stage_order_multiplier"]

    stage_changes = []
    sorted_timeline = sorted(timeline, key=lambda x: x["timestamp"])

    for item in sorted_timeline:
        consultation_status = None
        if item["type"] == "consultation":
            if hasattr(item["data"], "consultation_status"):
                consultation_status = item["data"].consultation_status

        if consultation_status:
            stage_id = consultation_status.stage_id
            if not stage_changes or stage_changes[-1]["stage_id"] != stage_id:
                stage_changes.append(
                    {"stage_id": stage_id, "timestamp": item["timestamp"]}
                )

    for i in range(1, len(stage_changes)):
        ts_i = stage_changes[i]["timestamp"]
        ts_prev = stage_changes[i - 1]["timestamp"]
        if ts_i.tzinfo is None:
            ts_i = ts_i.replace(tzinfo=timezone.utc)
        if ts_prev.tzinfo is None:
            ts_prev = ts_prev.replace(tzinfo=timezone.utc)

        time_diff_days = (ts_i - ts_prev).days
        if time_diff_days <= 3:
            score += points_config["fast_conversion_bonus"]
        elif time_diff_days > 14:
            score -= abs(points_config["slow_conversion_penalty"])

    return max(0, min(score, points_config["max_score"]))


async def get_lead_insights(
    db: AsyncSession,
    lead: models.Lead,
    timeline: List[dict],
) -> schemas.LeadInsights:
    """
    Lấy các chỉ số insight 360 độ của một Lead.
    ✅ FIXED: Không refresh 'consultations', thay vào đó gọi
    hàm _calculate_engagement_score đã tối ưu.
    """
    await log.debug("Calculating insights for lead", lead_id=lead.id)

    # === ⭐️ THAY ĐỔI QUAN TRỌNG Ở ĐÂY ⭐️ ===
    try:
        # BỎ "consultations" khỏi danh sách refresh
        await db.refresh(lead, ["assignment_logs", "pipeline_stage"])
        await log.debug(
            "Lead object refreshed (minimal) before insight calculation",
            lead_id=lead.id
        )
    except Exception as e:
        await log.error(
            "Failed to refresh lead object before calculating insights",
            lead_id=lead.id,
            error=str(e),
            exc_info=True,
        )
    # === KẾT THÚC THAY ĐỔI ===

    # Tính toán điểm số
    
    # 1. Gọi hàm async mới (chạy song song)
    engagement_score_task = _calculate_engagement_score(db, lead.id)
    
    # 2. Các hàm sync cũ (vẫn cần 'lead' object)
    fit_score = _calculate_fit_score(lead)
    urgency_score = _calculate_urgency_score(lead, timeline)

    # 3. Lấy kết quả
    engagement_score = await engagement_score_task

    # (Logic còn lại giữ nguyên)
    weights = settings.LEAD_SCORING_WEIGHTS
    overall_score = (
        (engagement_score * weights["engagement"])
        + (fit_score * weights["fit"])
        + (urgency_score * weights["urgency"])
    )

    if lead.officer_rating:
        try:
            rating_contribution = (
                int(lead.officer_rating) * weights["officer_rating_multiplier"]
            ) * weights["officer_rating_weight"]
            overall_score += rating_contribution
        except (ValueError, TypeError):
            await log.warning(
                "Invalid officer_rating during insight calculation",
                lead_id=lead.id,
                rating=lead.officer_rating,
            )

    overall_score_final = int(min(max(overall_score, 0), 100))

    return schemas.LeadInsights(
        engagement_score=int(engagement_score),
        fit_score=int(fit_score),
        urgency_score=int(urgency_score),
        overall_score=overall_score_final,
        officer_rating=lead.officer_rating,
        officer_summary=lead.officer_summary,
    )
```


## 📄 `services\lead_service.py`

**Lines:** 998 | **Size:** 43368 bytes

```python
# app/services/lead_service.py
from datetime import datetime, timezone, timedelta # Thêm timedelta nếu cần (hiện tại không dùng trực tiếp)
from typing import List, Optional, Tuple

import structlog
from sqlalchemy import func, or_, select, desc # Thêm desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .. import models, schemas
from ..config import settings
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


async def _log_lead_state_change(
    db: AsyncSession,
    lead: models.Lead,
    old_state: dict,
    new_state: dict,
    changed_by: Optional[models.User] = None,
    reason: str = "State updated"
):
    """
    Hàm helper tập trung để ghi lại bất kỳ thay đổi trạng thái nào của Lead.
    """
    # Chỉ ghi log nếu thực sự có thay đổi
    if old_state == new_state:
        await log.debug("No state change detected, skipping history log.", lead_id=getattr(lead, 'id', None)) # Thêm getattr phòng trường hợp lead chưa có ID
        return

    # Flush để lấy ID nếu chưa có (ví dụ khi tạo mới)
    if lead.id is None:
        try:
            await db.flush([lead]) # Flush chỉ đối tượng lead
            # Kiểm tra lại ID sau khi flush
            if lead.id is None:
                await log.error("Failed to obtain Lead ID after flush, cannot log history.", lead_email=lead.email)
                # Có thể raise lỗi ở đây nếu việc log history là bắt buộc
                return # Hoặc bỏ qua việc log nếu ID không lấy được
        except Exception as e:
            # Nếu flush bị lỗi (ví dụ: lỗi FK khác), ta log và raise ngay
            await log.error("Failed to flush Lead object before logging history", lead_email=lead.email, error=str(e))
            raise # Ném lỗi ban đầu (ví dụ: IntegrityError) lên để service xử lý

    history_entry = models.LeadStatusHistory(
        lead_id=lead.id, # Giờ chắc chắn có ID
        changed_by_user_id=changed_by.id if changed_by else None,
        reason=reason,

        old_status=old_state.get("status"),
        old_consultation_status_id=old_state.get("consultation_status_id"),
        old_pipeline_stage_id=old_state.get("pipeline_stage_id"),
        old_assigned_officer_id=old_state.get("assigned_officer_id"),

        new_status=new_state.get("status"),
        new_consultation_status_id=new_state.get("consultation_status_id"),
        new_pipeline_stage_id=new_state.get("pipeline_stage_id"),
        new_assigned_officer_id=new_state.get("assigned_officer_id"),
    )
    db.add(history_entry)
    await log.info(
        "Lead state change history logged",
        lead_id=lead.id,
        reason=reason,
        old=old_state,
        new=new_state
    )

def _get_current_lead_state(lead: models.Lead) -> dict:
    """Helper để chụp nhanh trạng thái hiện tại của Lead."""
    return {
        "status": lead.status,
        "consultation_status_id": lead.consultation_status_id,
        "pipeline_stage_id": lead.pipeline_stage_id,
        "assigned_officer_id": lead.assigned_officer_id,
    }

async def get_lead_by_id(
    db: AsyncSession, lead_id: int
) -> models.Lead:
    """
    Lấy chi tiết Lead bằng ID (Detail View).
    Hàm này giữ nguyên eager loading đầy đủ
    vì nó cần thiết cho Timeline và Insights.
    """
    query = (
        select(models.Lead)
        .options(
            selectinload(models.Lead.major),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
            # Load sâu consultations và logs để dùng cho timeline/insights
            selectinload(models.Lead.consultations).options(
                joinedload(models.Consultation.officer),
                joinedload(models.Consultation.consultation_status),
            ),
            selectinload(models.Lead.assignment_logs).options(
                joinedload(models.AssignmentLog.officer)
            ),
        )
        .where(models.Lead.id == lead_id)
    )
    result = await db.execute(query)
    lead = result.scalar_one_or_none()
    if not lead:
        raise ResourceNotFoundError(
            detail=f"Lead with id {lead_id} not found"
        )
    return lead


async def get_leads(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 10,
    status: Optional[str] = None,
    assigned_officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    major_id: Optional[int] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
) -> Tuple[int, List[models.Lead]]:
    """
    Lấy danh sách Leads (List View) - Đã tối ưu hóa eager loading.
    """

    # === Xây dựng query cơ bản ===
    base_query = select(models.Lead)
    count_query = select(func.count(models.Lead.id)) # Đếm dựa trên query gốc

    # === Áp dụng filter ===
    filters = []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            filters.append(models.Lead.status.in_(statuses))
    if assigned_officer_id is not None:
        filters.append(models.Lead.assigned_officer_id == assigned_officer_id)
    if unit_id is not None:
        filters.append(models.Lead.unit_id == unit_id)
    if major_id is not None:
        filters.append(models.Lead.major_id == major_id)
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            filters.append(models.Lead.source.in_(sources))

    # === Áp dụng search ===
    if search:
        search_term = f"%{search.strip()}%"
        search_conditions = or_(
            models.Lead.full_name.ilike(search_term),
            models.Lead.email.ilike(search_term),
            models.Lead.phone.ilike(search_term),
        )
        filters.append(search_conditions)

    # Áp dụng tất cả filters vào cả hai query
    if filters:
        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

    # === Thực thi count query ===
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one_or_none() or 0

    if total_count == 0:
        return 0, []

    # === Áp dụng sắp xếp ===
    sort_column = getattr(models.Lead, sort_by, models.Lead.created_at)
    if order.lower() == "desc":
        leads_query = base_query.order_by(sort_column.desc())
    else:
        leads_query = base_query.order_by(sort_column.asc())

    # === Áp dụng eager loading tối ưu và pagination ===
    leads_query = (
        leads_query.options(
            selectinload(models.Lead.major),
            selectinload(models.Lead.unit).options(
                selectinload(models.OrganizationUnit.parent),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.Lead.assigned_officer),
            selectinload(models.Lead.pipeline_stage),
            selectinload(models.Lead.consultation_status),
        )
        .offset(skip)
        .limit(limit)
    )

    # === Thực thi query lấy dữ liệu ===
    leads_result = await db.execute(leads_query)
    leads = leads_result.scalars().unique().all()

    return total_count, leads


async def create_lead(db: AsyncSession, lead_in: schemas.LeadCreate) -> models.Lead:
    """Tạo Lead mới, ném DuplicateResourceError nếu trùng."""
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task
    try:
        # Kiểm tra trùng lặp email + unit_id
        existing_lead_query = (
            select(models.Lead)
            .where(
                models.Lead.email == lead_in.email.strip(),
                models.Lead.unit_id == lead_in.unit_id,
            )
            .with_for_update() # Khóa để tránh race condition khi tạo
        )
        existing_lead_result = await db.execute(existing_lead_query)
        if existing_lead_result.scalar_one_or_none():
            raise DuplicateResourceError(
                detail="Lead with this email already exists in the unit."
            )

        # Chuẩn bị dữ liệu và tạo đối tượng Lead
        create_data = lead_in.model_dump()
        create_data["email"] = create_data["email"].strip()
        create_data["phone"] = create_data["phone"].strip()
        db_lead = models.Lead(**create_data)

        # Lấy trạng thái ban đầu từ DB
        initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
        initial_status = await db.get(models.ConsultationStatus, initial_status_id)

        # Trạng thái "trước khi tạo"
        old_state = _get_current_lead_state(models.Lead()) # Trạng thái rỗng

        # Gán trạng thái ban đầu cho Lead mới
        db_lead.status = initial_status_id
        db_lead.consultation_status_id = initial_status_id
        if initial_status:
            db_lead.pipeline_stage_id = initial_status.stage_id
        else:
            # Ghi log cảnh báo nếu không tìm thấy status mặc định
            await log.warning(
                "Initial consultation status not found during lead creation.",
                status_id=initial_status_id
            )
            # Có thể gán giá trị mặc định an toàn hơn ở đây hoặc ném lỗi nếu cần
            db_lead.pipeline_stage_id = None # Hoặc một stage_id mặc định khác

        # Trạng thái "sau khi gán"
        new_state = _get_current_lead_state(db_lead)

        # Thêm Lead vào session (chưa commit)
        db.add(db_lead)

        # Ghi log lịch sử thay đổi (cần flush để lấy lead.id)
        await _log_lead_state_change(
            db,
            db_lead,
            old_state,
            new_state,
            changed_by=None, # Không có user nào thay đổi khi tạo
            reason="Lead created"
        )

        # Commit transaction
        await db.commit()
        # Refresh để lấy dữ liệu mới nhất (bao gồm cả ID nếu chưa flush)
        await db.refresh(db_lead)
        await log.info(
            "New lead created successfully", lead_id=db_lead.id, email=db_lead.email
        )

        # Dispatch Celery task SAU KHI commit thành công
        try:
            process_automatic_lead_assignment_task.delay(db_lead.id)
            await log.info("Auto-assignment task dispatched successfully", lead_id=db_lead.id)
        except Exception as e:
            # Ghi log lỗi nếu không dispatch được, nhưng không rollback transaction
            await log.error(
                "Failed to dispatch Celery auto-assignment task",
                lead_id=db_lead.id,
                error=str(e),
                exc_info=True,
            )

        # Trả về đối tượng Lead đã được load đầy đủ (bao gồm relations)
        return await get_lead_by_id(db, db_lead.id)

    except Exception as e:
        # Rollback nếu có bất kỳ lỗi nào xảy ra trong khối try
        await db.rollback()
        await log.error(
            "Failed to create lead",
            lead_email=lead_in.email,
            error=str(e),
            exc_info=True,
        )
        raise e # Ném lại lỗi để router xử lý


async def update_lead(
    db: AsyncSession, lead_id: int, lead_in: schemas.LeadUpdate, updated_by: models.User
) -> models.Lead:
    """
    Cập nhật Lead một cách an toàn, ghi log lịch sử.
    """
    async with db.begin_nested(): # Sử dụng transaction lồng nhau
        try:
            # Lấy và khóa Lead để cập nhật
            stmt = (
                select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            )
            result = await db.execute(stmt)
            db_lead = result.scalar_one_or_none()

            if not db_lead:
                raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found")

            # Lưu trạng thái cũ trước khi thay đổi
            old_state = _get_current_lead_state(db_lead)

            # Lấy dữ liệu cập nhật từ schema Pydantic
            update_data = lead_in.model_dump(exclude_unset=True)

            # Làm sạch dữ liệu chuỗi (strip whitespace)
            for key, value in update_data.items():
                if isinstance(value, str):
                    update_data[key] = value.strip()

            # Kiểm tra trùng lặp email nếu email được cập nhật
            if "email" in update_data and update_data["email"] != db_lead.email:
                existing_lead_query = select(models.Lead).where(
                    models.Lead.email == update_data["email"],
                    models.Lead.unit_id == db_lead.unit_id, # Trong cùng unit
                    models.Lead.id != lead_id, # Loại trừ chính lead này
                )
                existing_lead_result = await db.execute(existing_lead_query)
                if existing_lead_result.scalar_one_or_none():
                    raise DuplicateResourceError(
                        detail="Another lead with this email already exists in the unit."
                    )

            # Cập nhật các trường thông thường
            for key, value in update_data.items():
                # Xử lý consultation_status_id riêng
                if key != "consultation_status_id":
                    setattr(db_lead, key, value)

            # Xử lý cập nhật consultation_status_id (nếu có)
            if "consultation_status_id" in update_data:
                new_status_id = update_data["consultation_status_id"]
                if new_status_id: # Nếu có status ID mới
                    # Lấy đối tượng ConsultationStatus từ DB
                    new_status = await db.get(models.ConsultationStatus, new_status_id)
                    if not new_status:
                        raise BadRequest(
                            detail=f"Consultation status with id '{new_status_id}' not found."
                        )
                    # Cập nhật cả 3 trường liên quan
                    db_lead.consultation_status_id = new_status.id
                    db_lead.pipeline_stage_id = new_status.stage_id
                    db_lead.status = new_status.id # Đồng bộ status chính
                else: # Nếu status ID mới là None (hiếm khi xảy ra khi update)
                    db_lead.consultation_status_id = None
                    db_lead.pipeline_stage_id = None
                    db_lead.status = "unknown" # Hoặc một trạng thái mặc định khác

            # Lấy trạng thái mới sau khi cập nhật
            new_state = _get_current_lead_state(db_lead)

            # Thêm đối tượng vào session (đánh dấu là dirty)
            db.add(db_lead)

            # Ghi log lịch sử nếu có thay đổi
            await _log_lead_state_change(
                db,
                db_lead,
                old_state,
                new_state,
                changed_by=updated_by,
                reason=f"Lead details updated by {updated_by.role}"
            )

            await log.info("Lead updated successfully within transaction", lead_id=lead_id)
            # Transaction sẽ commit khi ra khỏi `async with db.begin_nested()`

        except Exception as e:
            # Rollback tự động xảy ra khi có lỗi trong `async with`
            await log.error(
                "Failed to update lead, rolling back nested transaction",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,
            )
            raise e # Ném lại lỗi để router xử lý

        # Trả về lead đã được tải đầy đủ (bao gồm relations)
        # Gọi lại get_lead_by_id để đảm bảo dữ liệu mới nhất và relations
        return await get_lead_by_id(db, lead_id)


async def add_consultation(
    db: AsyncSession, lead_id: int, officer_id: int, data: schemas.ConsultationCreate
) -> models.Consultation:
    """
    Thêm consultation mới, cập nhật trạng thái Lead và ghi log lịch sử.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead (dùng get_lead_by_id để có relations)
            lead = await get_lead_by_id(db, lead_id)
            # Lấy Officer
            officer = await db.get(models.User, officer_id)
            if not officer:
                raise ResourceNotFoundError(f"Officer with id {officer_id} not found.")

            # Kiểm tra quyền: Officer phải được gán cho Lead này
            if lead.assigned_officer_id != officer_id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            # Lấy ConsultationStatus mới từ DB
            new_status = await db.get(models.ConsultationStatus, data.status_id)
            if not new_status:
                raise ResourceNotFoundError(
                    detail=f"Consultation status with id {data.status_id} not found."
                )

            # Lưu trạng thái Lead cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật trạng thái Lead theo status mới của consultation
            lead.consultation_status_id = new_status.id
            lead.pipeline_stage_id = new_status.stage_id
            lead.status = new_status.id # Đồng bộ status chính

            # Chuẩn bị dữ liệu để tạo Consultation
            create_consult_data = data.model_dump(exclude={"status_id"})
            if "notes" in create_consult_data and create_consult_data["notes"]:
                create_consult_data["notes"] = create_consult_data["notes"].strip()

            # Tạo đối tượng Consultation mới
            new_consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                consultation_status_id=new_status.id, # Gán status ID cho consultation
                **create_consult_data,
            )

            # Thêm các đối tượng vào session
            db.add(new_consultation)
            db.add(lead) # Đánh dấu lead là dirty

            # Lấy trạng thái Lead mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái Lead
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=officer,
                reason=f"Consultation added: {data.method}"
            )

            # Không cần commit ở đây, `async with` sẽ xử lý

            # Flush để lấy ID cho consultation mới (cần cho refresh)
            await db.flush([new_consultation])

            # Refresh consultation mới để tải relations (officer, consultation_status)
            await db.refresh(new_consultation, ["officer", "consultation_status"])

            await log.info(
                "New consultation added for lead",
                lead_id=lead_id,
                consultation_id=new_consultation.id,
                officer_id=officer_id,
            )
            return new_consultation # Trả về consultation đã được refresh

        except Exception as e:
            # Rollback tự động
            await log.error(
                "Failed to add consultation",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e


async def assign_lead_manually(
    db: AsyncSession, lead_id: int, officer_id: int, assigner: models.User
) -> models.Lead:
    """
    Gán lead thủ công cho một officer, cập nhật trạng thái và ghi logs.
    """
    async with db.begin_nested():
        try:
            # Lấy Lead và Officer
            lead = await get_lead_by_id(db, lead_id)
            officer = await db.get(models.User, officer_id)

            # Kiểm tra Officer hợp lệ
            if not officer:
                raise ResourceNotFoundError(
                    detail=f"User (Officer) with id {officer_id} not found."
                )
            if officer.role != "officer":
                raise PermissionDeniedError(
                    detail=f"User with id {officer_id} is not an officer."
                )

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)

            # Cập nhật Lead
            lead.assigned_officer_id = officer.id
            lead.assigned_at = datetime.now(timezone.utc)
            # Cập nhật status thành 'assigned' nếu đang ở trạng thái ban đầu/chờ gán lại
            if lead.status in [settings.DEFAULT_INITIAL_LEAD_STATUS_ID, settings.DEFAULT_REASSIGN_LEAD_STATUS, "new"] or not lead.status:
                lead.status = settings.DEFAULT_ASSIGNED_LEAD_STATUS

            # Cập nhật Officer
            officer.last_assigned_at = datetime.now(timezone.utc)
            db.add(officer) # Đánh dấu officer là dirty

            # Tạo Assignment Log
            log_reason = f"Manually assigned by {assigner.role} {assigner.username}"
            log_entry = models.AssignmentLog(
                lead_id=lead_id,
                officer_id=officer_id,
                method="manual",
                reason=log_reason,
                timestamp=datetime.now(timezone.utc) # Thêm timestamp
            )
            db.add(lead) # Đánh dấu lead là dirty
            db.add(log_entry)

            # Lấy trạng thái mới
            new_state = _get_current_lead_state(lead)

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=assigner,
                reason=log_reason
            )

            await log.info(
                "Lead assigned manually",
                lead_id=lead_id,
                officer_id=officer_id,
                assigner_id=assigner.id,
            )
            # Commit transaction

        except Exception as e:
            # Rollback tự động
            await log.error(
                "Failed to assign lead manually",
                lead_id=lead_id,
                officer_id=officer_id,
                error=str(e),
                exc_info=True,
            )
            raise e

        # Trả về lead đã được tải đầy đủ sau khi commit thành công
        return await get_lead_by_id(db, lead_id)


async def get_lead_timeline(db: AsyncSession, lead_id: int) -> List[dict]:
    """Lấy timeline tổng hợp của Lead (consultations và assignment logs)."""
    # Lấy lead (có thể không cần full eager loading ban đầu)
    lead_query = select(models.Lead).where(models.Lead.id == lead_id)
    lead_result = await db.execute(lead_query)
    lead = lead_result.scalar_one_or_none()
    if not lead:
         raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

    # THÊM DÒNG NÀY: Refresh để đảm bảo relations được tải mới nhất
    await db.refresh(lead, ['consultations', 'assignment_logs'])
    await log.debug("Refreshed lead consultations and assignment logs for timeline", lead_id=lead_id)

    timeline_items = []
    # Thêm consultations vào timeline
    if lead.consultations:
        for c in lead.consultations:
            # Refresh thêm consultation để lấy relations của nó (officer, status)
            # Hoặc đảm bảo get_lead_by_id đã load sâu
            # Cách an toàn: refresh consultation trước khi validate/dump
            await db.refresh(c, ['officer', 'consultation_status'])
            timeline_items.append(
                schemas.TimelineItem(type="consultation", data=schemas.Consultation.model_validate(c), timestamp=c.consultation_date).model_dump()
            )
    # Thêm assignment logs vào timeline
    if lead.assignment_logs:
        for log_entry in lead.assignment_logs:
            # Refresh thêm assignment log để lấy officer
            await db.refresh(log_entry, ['officer'])
            timeline_items.append(
                schemas.TimelineItem(type="assignment", data=schemas.AssignmentLog.model_validate(log_entry), timestamp=log_entry.timestamp).model_dump()
            )

    # Sắp xếp timeline theo timestamp giảm dần (mới nhất trước)
    timeline_items.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline_items


async def delete_consultation(
    db: AsyncSession, lead_id: int, consultation_id: int, current_user: models.User
):
    """(Admin only) Xóa một consultation và cập nhật lại trạng thái Lead."""
    try:
        # Lấy Lead (không cần eager load consultations ở đây)
        lead_query = select(models.Lead).where(models.Lead.id == lead_id)
        lead_result = await db.execute(lead_query)
        lead = lead_result.scalar_one_or_none()
        if not lead:
             raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

        # Lấy Consultation cần xóa
        consultation = await db.get(models.Consultation, consultation_id)
        if not consultation:
            raise ResourceNotFoundError(
                detail=f"Consultation with id {consultation_id} not found."
            )
        # Kiểm tra consultation thuộc đúng Lead
        if consultation.lead_id != lead_id:
            raise BadRequest(
                detail="Consultation does not belong to the specified lead."
            )

        # Kiểm tra quyền Admin
        if current_user.role != "admin":
            raise PermissionDeniedError(detail="Only admins can delete consultations.")

        # Lưu trạng thái cũ của Lead trước khi xóa consultation
        old_state = _get_current_lead_state(lead)

        # Xóa consultation
        await db.delete(consultation)
        await log.info("Consultation marked for deletion", consultation_id=consultation_id)

        # Tìm consultation gần nhất còn lại để cập nhật trạng thái Lead
        remaining_consultations_query = (
            select(models.Consultation)
            .where(models.Consultation.lead_id == lead.id)
            .order_by(models.Consultation.consultation_date.desc(), models.Consultation.id.desc()) # Sắp xếp cả theo ID để ổn định
        )
        remaining_consultations_result = await db.execute(remaining_consultations_query)
        latest_consultation = remaining_consultations_result.scalars().first()

        new_status_id = None
        new_stage_id = None
        # Nếu còn consultation khác
        if latest_consultation and latest_consultation.consultation_status_id:
            latest_status = await db.get(
                models.ConsultationStatus, latest_consultation.consultation_status_id
            )
            if latest_status:
                new_status_id = latest_status.id
                new_stage_id = latest_status.stage_id
                await log.info(f"Reverting lead status to latest remaining consultation's status: {new_status_id}", lead_id=lead_id)
            else:
                 await log.warning(f"Status '{latest_consultation.consultation_status_id}' not found for latest consultation {latest_consultation.id}", lead_id=lead_id)
        # Nếu không còn consultation nào, revert về trạng thái ban đầu
        else:
            initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
            initial_status = await db.get(models.ConsultationStatus, initial_status_id)
            if initial_status:
                new_status_id = initial_status.id
                new_stage_id = initial_status.stage_id
                await log.info(f"Reverting lead status to initial status: {new_status_id}", lead_id=lead_id)
            else:
                await log.warning(f"Initial status '{initial_status_id}' not found when reverting lead status.", lead_id=lead_id)
                # Gán giá trị an toàn nếu không tìm thấy status ban đầu
                new_status_id = "unknown"
                new_stage_id = None

        # Cập nhật trạng thái Lead
        lead.consultation_status_id = new_status_id
        lead.pipeline_stage_id = new_stage_id
        lead.status = new_status_id # Đồng bộ status chính
        db.add(lead) # Đánh dấu lead là dirty

        # Lấy trạng thái mới sau khi cập nhật
        new_state = _get_current_lead_state(lead)

        # Ghi log lịch sử thay đổi trạng thái Lead do xóa consultation
        await _log_lead_state_change(
            db,
            lead,
            old_state,
            new_state,
            changed_by=current_user,
            reason=f"Admin deleted consultation ID {consultation_id}"
        )

        # Commit transaction (xóa consultation và cập nhật lead)
        await db.commit()
        await log.info(
            "Consultation deleted and lead status reverted by admin",
            admin_id=current_user.id,
            lead_id=lead_id,
            consultation_id=consultation_id,
            new_lead_status=new_status_id
        )
    except Exception as e:
        # Rollback nếu có lỗi
        await db.rollback()
        await log.error(
            "Failed to delete consultation",
            lead_id=lead_id,
            consultation_id=consultation_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def process_officer_action(
    db: AsyncSession, lead_id: int, officer: models.User, action: str, reason: str
) -> models.Lead:
    """
    Xử lý hành động (reject/reassign) của Officer trên Lead, ghi logs và dispatch task.
    """
    # Di chuyển import vào đây để phá vỡ circular import
    from ..celery_utils import process_automatic_lead_assignment_task
    trigger_reassignment = False # Biến cờ để dispatch task sau commit
    try:
        async with db.begin_nested():
            # Lấy Lead (có thể không cần full eager loading ở đây)
            lead_query = select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                 raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Kiểm tra quyền: Officer phải được gán
            if lead.assigned_officer_id != officer.id:
                raise PermissionDeniedError(detail="You are not assigned to this lead.")

            log_method = "" # Method cho AssignmentLog
            log_reason = reason.strip() if reason else "No reason provided by officer"

            # Lưu trạng thái cũ
            old_state = _get_current_lead_state(lead)
            new_state = old_state.copy() # Tạo bản sao để sửa đổi

            if action == "reassign":
                new_state["status"] = settings.DEFAULT_REASSIGN_LEAD_STATUS
                new_state["assigned_officer_id"] = None
                # Giữ nguyên consult/stage
                new_state["consultation_status_id"] = lead.consultation_status_id
                new_state["pipeline_stage_id"] = lead.pipeline_stage_id
                lead.assigned_at = None
                # THÊM DÒNG NÀY:
                lead.assigned_officer = None # <-- Set cả relationship thành None
                log_method = "officer_reassign"
                trigger_reassignment = True
                await log.info("Officer requested lead reassignment", lead_id=lead_id, officer_id=officer.id)
            
            elif action == "reject":
                lost_status_id = settings.DEFAULT_LOST_LEAD_STATUS_ID
                new_state["status"] = lost_status_id # Chuyển status chính sang LOST
                log_method = "officer_reject"

                # Tìm ConsultationStatus tương ứng với LOST
                lost_consult_status = await db.get(
                    models.ConsultationStatus, lost_status_id
                )
                if lost_consult_status:
                    new_state["consultation_status_id"] = lost_consult_status.id
                    new_state["pipeline_stage_id"] = lost_consult_status.stage_id
                    await log.info(f"Setting consultation status and stage to LOST status '{lost_status_id}'", lead_id=lead_id)
                else:
                    await log.warning(
                        f"Consultation status '{lost_status_id}' (Lost) not found. Lead status set, but consult/stage might be inconsistent.",
                        lead_id=lead_id,
                    )
                    # Giữ nguyên consult/stage cũ hoặc set là None/unknown nếu cần
                    new_state["consultation_status_id"] = None
                    new_state["pipeline_stage_id"] = None

                await log.info("Officer rejected lead", lead_id=lead_id, officer_id=officer.id)

            else:
                # Hành động không hợp lệ
                raise BadRequest(
                    detail=f"Invalid action: {action}. Allowed actions: 'reject', 'reassign'."
                )

            # Cập nhật các trường của Lead dựa trên new_state
            lead.status = new_state["status"]
            lead.consultation_status_id = new_state["consultation_status_id"]
            lead.pipeline_stage_id = new_state["pipeline_stage_id"]
            lead.assigned_officer_id = new_state["assigned_officer_id"]
            # assigned_at đã được xử lý trong 'reassign'

            # Ghi log lịch sử thay đổi trạng thái
            await _log_lead_state_change(
                db,
                lead,
                old_state,
                new_state,
                changed_by=officer,
                reason=log_reason
            )

            # Tạo AssignmentLog cho hành động này
            log_entry = models.AssignmentLog(
                lead_id=lead.id,
                officer_id=officer.id, # Ghi lại officer thực hiện action
                method=log_method,
                reason=log_reason,
                timestamp=datetime.now(timezone.utc),
            )
            db.add(lead) # Đánh dấu lead là dirty
            db.add(log_entry)

            # Commit transaction bên trong
            await log.info(f"Processed officer action '{action}' within transaction", lead_id=lead_id)

        # Dispatch Celery task SAU KHI transaction thành công (nếu cần)
        if trigger_reassignment:
            try:
                process_automatic_lead_assignment_task.delay(lead.id)
                await log.info("Re-assignment task dispatched for lead", lead_id=lead.id)
            except Exception as e:
                await log.error(
                    "Failed to dispatch Celery re-assignment task after officer action",
                    lead_id=lead.id,
                    error=str(e),
                    exc_info=True,
                )
                # Không rollback transaction vì hành động chính đã thành công

        # Trả về lead đã được tải đầy đủ
        return await get_lead_by_id(db, lead_id)

    except (PermissionDeniedError, BadRequest, ResourceNotFoundError) as e: # Thêm ResourceNotFoundError
        # Rollback nếu lỗi validation hoặc không tìm thấy
        await db.rollback()
        await log.warning(
            "Officer action failed validation or resource not found",
            lead_id=lead_id,
            officer_id=getattr(officer, 'id', None), # Lấy ID an toàn
            action=action,
            detail=getattr(e, 'detail', str(e)),
        )
        raise e
    except Exception as e:
        # Rollback cho các lỗi không mong muốn khác
        await db.rollback()
        await log.error(
            "Failed to process officer action",
            lead_id=lead_id,
            officer_id=getattr(officer, 'id', None),
            action=action,
            error=str(e),
            exc_info=True,
        )
        raise e


async def revert_last_status(
    db: AsyncSession,
    lead_id: int,
    admin_user: models.User,
    reason: Optional[str] = None, # Cho phép reason là None
) -> models.Lead:
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của Lead về trạng thái trước đó.
    """
    final_reason = reason.strip() if reason else "Admin reverted last status change"
    try:
        async with db.begin_nested():
            # Lấy Lead (không cần eager load quá nhiều)
            lead_query = select(models.Lead).where(models.Lead.id == lead_id).with_for_update()
            lead_result = await db.execute(lead_query)
            lead = lead_result.scalar_one_or_none()
            if not lead:
                 raise ResourceNotFoundError(detail=f"Lead with id {lead_id} not found.")

            # Tìm bản ghi lịch sử gần nhất
            last_history_entry = await db.scalar(
                select(models.LeadStatusHistory)
                .where(models.LeadStatusHistory.lead_id == lead_id)
                .order_by(models.LeadStatusHistory.changed_at.desc(), models.LeadStatusHistory.id.desc()) # Sắp xếp cả theo ID
                .limit(1)
            )

            if not last_history_entry:
                raise BadRequest(detail="No status history found for this lead to revert.")

            # Trạng thái "đích" để hoàn tác về chính là trạng thái "cũ" trong bản ghi history
            if last_history_entry.old_status is None and \
               last_history_entry.old_consultation_status_id is None and \
               last_history_entry.old_pipeline_stage_id is None and \
               last_history_entry.old_assigned_officer_id is None:
                raise BadRequest(
                    detail="Cannot revert to the initial state (before any status change recorded)."
                )

            # Lấy trạng thái hiện tại của Lead
            current_state = _get_current_lead_state(lead)

            # Xây dựng trạng thái cần hoàn tác về
            revert_to_state = {
                "status": last_history_entry.old_status,
                "consultation_status_id": last_history_entry.old_consultation_status_id,
                "pipeline_stage_id": last_history_entry.old_pipeline_stage_id,
                "assigned_officer_id": last_history_entry.old_assigned_officer_id,
            }

            # Kiểm tra xem có cần hoàn tác không
            if current_state == revert_to_state:
                await log.info(
                    "Lead state is already the same as the previous recorded state, no revert needed.",
                    lead_id=lead_id
                )
                # Trả về lead hiện tại nếu không có gì thay đổi
                return await get_lead_by_id(db, lead_id) # Vẫn gọi get_lead_by_id để đảm bảo eager loading

            await log.info(
                "Admin reverting lead state",
                lead_id=lead_id,
                admin_id=admin_user.id,
                from_state=current_state,
                to_state=revert_to_state,
                reason=final_reason
            )

            # Ghi log lịch sử cho hành động hoàn tác này
            await _log_lead_state_change(
                db,
                lead,
                old_state=current_state, # Trạng thái cũ là trạng thái hiện tại
                new_state=revert_to_state, # Trạng thái mới là trạng thái cần revert về
                changed_by=admin_user,
                reason=final_reason
            )

            # Cập nhật các trường của Lead về trạng thái cũ
            lead.status = revert_to_state["status"]
            lead.consultation_status_id = revert_to_state["consultation_status_id"]
            lead.pipeline_stage_id = revert_to_state["pipeline_stage_id"]
            lead.assigned_officer_id = revert_to_state["assigned_officer_id"]

            # Cập nhật assigned_at nếu officer được khôi phục từ trạng thái không có officer
            if (revert_to_state["assigned_officer_id"] is not None and
                current_state["assigned_officer_id"] is None):
                 lead.assigned_at = datetime.now(timezone.utc)
            elif revert_to_state["assigned_officer_id"] is None:
                 lead.assigned_at = None # Xóa assigned_at nếu revert về trạng thái không gán

            db.add(lead) # Đánh dấu lead là dirty

            # Commit transaction
            await log.info("Revert lead status completed within transaction", lead_id=lead_id)

    except (BadRequest, ResourceNotFoundError) as e:
        await db.rollback()
        await log.warning("Failed to revert lead status due to validation error", lead_id=lead_id, detail=getattr(e, 'detail', str(e)))
        raise e
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to revert lead status",
            lead_id=lead_id,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        raise e

    # Trả về lead đã được tải đầy đủ sau khi commit thành công
    return await get_lead_by_id(db, lead_id)
```


## 📄 `services\organization_service.py`

**Lines:** 261 | **Size:** 9199 bytes

```python
# app/services/organization_service.py
from typing import List, Optional

import structlog  # <-- BỔ SUNG
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)  # <-- BỔ SUNG

# --- OrganizationUnit Services ---


async def get_all_organization_units(db: AsyncSession) -> List[models.OrganizationUnit]:
    """Lấy danh sách tất cả các đơn vị, tải háo hức các quan hệ."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent).options(
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.majors),
        )
        .order_by(models.OrganizationUnit.name)
    )
    result = await db.execute(query)
    return result.scalars().unique().all()


async def get_organization_unit_by_id(
    db: AsyncSession, unit_id: int
) -> Optional[models.OrganizationUnit]:
    """Lấy chi tiết một đơn vị, tải háo hức các quan hệ."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent).options(
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.majors),
        )
        .where(models.OrganizationUnit.id == unit_id)
    )
    result = await db.execute(query)
    unit = result.scalars().unique().one_or_none()
    if not unit:
        raise ResourceNotFoundError(
            detail=f"Organization Unit with id {unit_id} not found."
        )
    return unit


async def create_organization_unit(
    db: AsyncSession, unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    try:
        if unit_in.parent_id:
            parent_unit = await db.get(models.OrganizationUnit, unit_in.parent_id)
            if not parent_unit:
                raise ResourceNotFoundError(
                    detail=f"Parent unit with id {unit_in.parent_id} not found."
                )

        db_unit = models.OrganizationUnit(**unit_in.model_dump())
        db.add(db_unit)
        await db.commit()
        await db.refresh(db_unit)
        # Tải lại đầy đủ relations trước khi trả về
        return await get_organization_unit_by_id(db, db_unit.id)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create organization unit",
            unit_name=unit_in.name,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_organization_unit(
    db: AsyncSession, unit_id: int, unit_in: schemas.OrganizationUnitUpdate
) -> models.OrganizationUnit:
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        update_data = unit_in.model_dump(exclude_unset=True)

        if "parent_id" in update_data:
            new_parent_id = update_data["parent_id"]
            if new_parent_id is None:
                db_unit.parent_id = None
            else:
                if new_parent_id == unit_id:
                    raise DuplicateResourceError(
                        detail="A unit cannot be its own parent."
                    )
                parent_unit = await db.get(models.OrganizationUnit, new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )
                db_unit.parent_id = new_parent_id

        for key, value in update_data.items():
            if key != "parent_id":
                setattr(db_unit, key, value)

        db.add(db_unit)
        await db.commit()
        # Tải lại đầy đủ relations
        return await get_organization_unit_by_id(db, unit_id)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_organization_unit(db: AsyncSession, unit_id: int):
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        if db_unit.children or db_unit.majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains child units or majors."
            )
        await db.delete(db_unit)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Major Services ---


async def get_major_by_id(db: AsyncSession, major_id: int) -> Optional[models.Major]:
    major = await db.get(models.Major, major_id)
    if not major:
        raise ResourceNotFoundError(detail=f"Major with id {major_id} not found.")
    return major


async def create_major(db: AsyncSession, major_in: schemas.MajorCreate) -> models.Major:
    try:
        existing_major_query = select(models.Major).where(
            models.Major.code == major_in.code
        )
        existing_major = await db.execute(existing_major_query)
        if existing_major.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Major with code '{major_in.code}' already exists."
            )

        db_major = models.Major(**major_in.model_dump())
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)
        return db_major
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create major",
            major_code=major_in.code,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_major(
    db: AsyncSession, major_id: int, major_in: schemas.MajorUpdate
) -> models.Major:
    try:
        db_major = await get_major_by_id(db, major_id)
        update_data = major_in.model_dump(exclude_unset=True)

        if "code" in update_data and update_data["code"] != db_major.code:
            existing_major_query = select(models.Major).where(
                models.Major.code == update_data["code"]
            )
            if (await db.execute(existing_major_query)).scalar_one_or_none():
                raise DuplicateResourceError(
                    detail=f"Major with code '{update_data['code']}' already exists."
                )

        for key, value in update_data.items():
            setattr(db_major, key, value)
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)
        return db_major
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def delete_major(db: AsyncSession, major_id: int):
    try:
        db_major = await get_major_by_id(db, major_id)
        await db.delete(db_major)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def get_majors_by_unit_tree(
    db: AsyncSession, unit_id: int, search_term: str = None
) -> List[models.Major]:
    """Lấy danh sách ngành học thuộc về một đơn vị và tất cả các đơn vị con cháu của nó."""
    if not unit_id:
        return []

    sql = text(
        """
        WITH RECURSIVE unit_hierarchy AS (
           SELECT id FROM organization_unit WHERE id = :unit_id
           UNION ALL
           SELECT u.id FROM organization_unit u JOIN unit_hierarchy uh ON u.parent_id = uh.id
        )
        SELECT id FROM unit_hierarchy;
    """
    )
    result = await db.execute(sql, {"unit_id": unit_id})
    all_related_unit_ids = [row[0] for row in result]

    query = select(models.Major).filter(models.Major.unit_id.in_(all_related_unit_ids))
    if search_term:
        # 1. Làm sạch và tạo pattern an toàn
        safe_pattern = f"%{search_term.strip()}%"

        # 2. Truyền TOÀN BỘ pattern như một tham số
        # SQLAlchemy sẽ tự động escape nó
        query = query.filter(models.Major.name.ilike(safe_pattern))

    majors_result = await db.execute(query.order_by(models.Major.name).limit(20))
    return majors_result.scalars().all()

```


## 📄 `services\pipeline_service.py`

**Lines:** 366 | **Size:** 13745 bytes

```python
# app/services/pipeline_service.py
import json
from typing import List

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas  # <-- THÊM schemas
# --- THÊM CÁC IMPORTS SAU ---
from ..config import settings
from ..database import (
    safe_redis_delete,
    safe_redis_get,
    safe_redis_set,
)
from ..utils.exceptions import (  # <-- THÊM
    DuplicateResourceError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

# --- ĐỊNH NGHĨA KEY VÀ TTL ---
PIPELINE_STAGES_CACHE_KEY = "pipeline:all_stages"
PIPELINE_STATUSES_CACHE_KEY = "pipeline:all_statuses"
# Sử dụng TTL chung từ file config
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS


# ===============================================================
# CHỨC NĂNG CACHE (Giữ nguyên)
# ===============================================================

async def get_all_pipeline_stages(db: AsyncSession) -> List[dict]:
    """Lấy tất cả Pipeline Stages (Hỗ trợ Cache)."""
    await log.debug("Fetching all pipeline stages", cache_key=PIPELINE_STAGES_CACHE_KEY)

    # 1. Thử cache trước
    try:
        cached_data = await safe_redis_get(PIPELINE_STAGES_CACHE_KEY)
        if cached_data:
            await log.debug("Cache hit for pipeline stages")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        await log.error(
            "Failed to get pipeline stages from cache",
            cache_key=PIPELINE_STAGES_CACHE_KEY,
            error=str(e_redis_get),
        )

    await log.debug("Cache miss for pipeline stages, querying DB")
    
    # 2. Cache Miss: Query DB
    query = select(models.PipelineStage).order_by(models.PipelineStage.order)
    result = await db.execute(query)
    stages_models = result.scalars().all()

    # 3. Chuyển đổi models sang list[dict]
    stages_data = [
        {"id": s.id, "name": s.name, "order": s.order}
        for s in stages_models
    ]

    # 4. Lưu vào cache
    try:
        await safe_redis_set(
            PIPELINE_STAGES_CACHE_KEY, json.dumps(stages_data), ex=CACHE_TTL
        )
        await log.debug("Stored pipeline stages in cache", ttl=CACHE_TTL)
    except Exception as e_redis_set:
        await log.error(
            "Failed to set pipeline stages in cache",
            cache_key=PIPELINE_STAGES_CACHE_KEY,
            error=str(e_redis_set),
        )

    return stages_data


async def get_all_consultation_statuses(
    db: AsyncSession,
) -> List[dict]:
    """Lấy tất cả Consultation Statuses (Hỗ trợ Cache)."""
    await log.debug("Fetching all consultation statuses", cache_key=PIPELINE_STATUSES_CACHE_KEY)
    
    # 1. Thử cache
    try:
        cached_data = await safe_redis_get(PIPELINE_STATUSES_CACHE_KEY)
        if cached_data:
            await log.debug("Cache hit for consultation statuses")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        await log.error(
            "Failed to get consultation statuses from cache",
            cache_key=PIPELINE_STATUSES_CACHE_KEY,
            error=str(e_redis_get),
        )

    await log.debug("Cache miss for consultation statuses, querying DB")
    
    # 2. Cache Miss: Query DB
    query = select(models.ConsultationStatus)
    result = await db.execute(query)
    statuses_models = result.scalars().all()

    # 3. Chuyển đổi models sang list[dict]
    statuses_data = [
        {"id": s.id, "name": s.name, "color_code": s.color_code, "stage_id": s.stage_id}
        for s in statuses_models
    ]

    # 4. Lưu vào cache
    try:
        await safe_redis_set(
            PIPELINE_STATUSES_CACHE_KEY, json.dumps(statuses_data), ex=CACHE_TTL
        )
        await log.debug("Stored consultation statuses in cache", ttl=CACHE_TTL)
    except Exception as e_redis_set:
        await log.error(
            "Failed to set consultation statuses in cache",
            cache_key=PIPELINE_STATUSES_CACHE_KEY,
            error=str(e_redis_set),
        )

    return statuses_data


async def invalidate_pipeline_cache():
    """Xóa cache của pipeline (stages và statuses)."""
    try:
        await safe_redis_delete(PIPELINE_STAGES_CACHE_KEY)
        await safe_redis_delete(PIPELINE_STATUSES_CACHE_KEY)
        await log.info(
            "Pipeline cache invalidated successfully.",
            keys=[PIPELINE_STAGES_CACHE_KEY, PIPELINE_STATUSES_CACHE_KEY],
        )
    except Exception as e:
        await log.error("Failed to invalidate pipeline cache", error=str(e))


# ===============================================================
# HELPER (NỘI BỘ)
# ===============================================================

async def _get_stage_by_id(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    stage = await db.get(models.PipelineStage, stage_id)
    if not stage:
        raise ResourceNotFoundError(detail=f"Pipeline Stage '{stage_id}' not found.")
    return stage

async def _get_status_by_id(db: AsyncSession, status_id: str) -> models.ConsultationStatus:
    status = await db.get(models.ConsultationStatus, status_id)
    if not status:
        raise ResourceNotFoundError(detail=f"Consultation Status '{status_id}' not found.")
    return status

# ===============================================================
# CRUD CHO PIPELINE STAGE (MỚI)
# ===============================================================

async def create_pipeline_stage(
    db: AsyncSession, stage_in: schemas.PipelineStageCreate
) -> models.PipelineStage:
    try:
        # 1. Kiểm tra ID đã tồn tại
        existing_id = await db.get(models.PipelineStage, stage_in.id)
        if existing_id:
            raise DuplicateResourceError(f"Pipeline Stage ID '{stage_in.id}' already exists.")
        
        # 2. Kiểm tra 'order' đã tồn tại
        existing_order = await db.scalar(
            select(models.PipelineStage).where(models.PipelineStage.order == stage_in.order)
        )
        if existing_order:
            raise DuplicateResourceError(f"Pipeline Stage order '{stage_in.order}' already exists.")
            
        # 3. Tạo
        db_stage = models.PipelineStage(**stage_in.model_dump())
        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)
        
        # 4. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Created new pipeline stage, cache invalidated", stage_id=db_stage.id)
        
        return db_stage
    except Exception as e:
        await db.rollback()
        await log.error("Failed to create pipeline stage", error=str(e), exc_info=True)
        raise e


async def get_pipeline_stage(db: AsyncSession, stage_id: str) -> models.PipelineStage:
    """Lấy chi tiết 1 stage (không cache, vì chỉ dùng cho admin)."""
    return await _get_stage_by_id(db, stage_id)


async def update_pipeline_stage(
    db: AsyncSession, stage_id: str, stage_in: schemas.PipelineStageUpdate
) -> models.PipelineStage:
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        update_data = stage_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra 'order' (nếu thay đổi)
        if "order" in update_data and update_data["order"] != db_stage.order:
            existing_order = await db.scalar(
                select(models.PipelineStage)
                .where(models.PipelineStage.order == update_data["order"])
            )
            if existing_order:
                raise DuplicateResourceError(f"Pipeline Stage order '{update_data['order']}' already in use.")

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_stage, key, value)
        
        db.add(db_stage)
        await db.commit()
        await db.refresh(db_stage)
        
        # 3. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Updated pipeline stage, cache invalidated", stage_id=db_stage.id)
        
        return db_stage
    except Exception as e:
        await db.rollback()
        await log.error("Failed to update pipeline stage", stage_id=stage_id, error=str(e), exc_info=True)
        raise e


async def delete_pipeline_stage(db: AsyncSession, stage_id: str):
    try:
        db_stage = await _get_stage_by_id(db, stage_id)
        
        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        child_status_count = await db.scalar(
            select(func.count(models.ConsultationStatus.id))
            .where(models.ConsultationStatus.stage_id == stage_id)
        )
        if child_status_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete stage '{stage_id}'. It has {child_status_count} consultation statuses linked to it."
            )
            
        # 2. Xóa
        await db.delete(db_stage)
        await db.commit()
        
        # 3. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Deleted pipeline stage, cache invalidated", stage_id=stage_id)
        
    except Exception as e:
        await db.rollback()
        await log.error("Failed to delete pipeline stage", stage_id=stage_id, error=str(e), exc_info=True)
        raise e


# ===============================================================
# CRUD CHO CONSULTATION STATUS (MỚI)
# ===============================================================

async def create_consultation_status(
    db: AsyncSession, status_in: schemas.ConsultationStatusCreate
) -> models.ConsultationStatus:
    try:
        # 1. Kiểm tra ID
        existing_id = await db.get(models.ConsultationStatus, status_in.id)
        if existing_id:
            raise DuplicateResourceError(f"Consultation Status ID '{status_in.id}' already exists.")
            
        # 2. Kiểm tra Stage cha
        await _get_stage_by_id(db, status_in.stage_id) # Sẽ ném 404 nếu stage_id không tồn tại
            
        # 3. Tạo
        db_status = models.ConsultationStatus(**status_in.model_dump())
        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)
        
        # 4. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Created new consultation status, cache invalidated", status_id=db_status.id)
        
        return db_status
    except Exception as e:
        await db.rollback()
        await log.error("Failed to create consultation status", error=str(e), exc_info=True)
        raise e


async def get_consultation_status(db: AsyncSession, status_id: str) -> models.ConsultationStatus:
    """Lấy chi tiết 1 status (không cache, vì chỉ dùng cho admin)."""
    return await _get_status_by_id(db, status_id)


async def update_consultation_status(
    db: AsyncSession, status_id: str, status_in: schemas.ConsultationStatusUpdate
) -> models.ConsultationStatus:
    try:
        db_status = await _get_status_by_id(db, status_id)
        update_data = status_in.model_dump(exclude_unset=True)

        # 1. Kiểm tra Stage cha (nếu thay đổi)
        if "stage_id" in update_data and update_data["stage_id"] != db_status.stage_id:
            await _get_stage_by_id(db, update_data["stage_id"]) # Ném 404 nếu không tìm thấy

        # 2. Cập nhật
        for key, value in update_data.items():
            setattr(db_status, key, value)
            
        db.add(db_status)
        await db.commit()
        await db.refresh(db_status)
        
        # 3. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Updated consultation status, cache invalidated", status_id=db_status.id)
        
        return db_status
    except Exception as e:
        await db.rollback()
        await log.error("Failed to update consultation status", status_id=status_id, error=str(e), exc_info=True)
        raise e


async def delete_consultation_status(db: AsyncSession, status_id: str):
    try:
        db_status = await _get_status_by_id(db, status_id)
        
        # 1. KIỂM TRA RÀNG BUỘC (QUAN TRỌNG)
        lead_count = await db.scalar(
            select(func.count(models.Lead.id))
            .where(models.Lead.consultation_status_id == status_id)
        )
        if lead_count > 0:
            raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is currently used by {lead_count} leads."
            )
        
        # (Tùy chọn) Kiểm tra xem có consultation nào đang dùng ID này không
        consultation_count = await db.scalar(
            select(func.count(models.Consultation.id))
            .where(models.Consultation.consultation_status_id == status_id)
        )
        if consultation_count > 0:
             raise DuplicateResourceError(
                f"Cannot delete status '{status_id}'. It is linked to {consultation_count} consultation history records."
            )

        # 2. Xóa
        await db.delete(db_status)
        await db.commit()
        
        # 3. Hủy cache
        await invalidate_pipeline_cache()
        await log.info("Deleted consultation status, cache invalidated", status_id=status_id)
        
    except Exception as e:
        await db.rollback()
        await log.error("Failed to delete consultation status", status_id=status_id, error=str(e), exc_info=True)
        raise e
```


## 📄 `services\session_service.py`

**Lines:** 392 | **Size:** 10928 bytes

```python
# app/services/session_service.py
"""
Service layer for managing user sessions.
Handles session creation, tracking, anomaly detection, and revocation.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from .. import models, schemas
from ..config import settings
from ..database import safe_redis_set, safe_redis_delete  # ✅ FIX: Import safe_redis_delete

log = structlog.get_logger(__name__)


async def create_session(
    db: AsyncSession,
    user_id: int,
    refresh_jti: str,
    ip_address: Optional[str],
    user_agent_string: Optional[str],
    expires_at: datetime,
) -> models.UserSession:
    """
    Create a new session record when user logs in.
    
    Args:
        db: Database session
        user_id: User ID
        refresh_jti: Refresh token JTI
        ip_address: Client IP address
        user_agent_string: User-Agent header string
        expires_at: Session expiration time (same as refresh token expiry)
    
    Returns:
        Created UserSession instance
    """
    # Parse User-Agent to extract device info
    device_type = "unknown"
    browser = "Unknown"
    os = "Unknown"
    
    if user_agent_string:
        try:
            user_agent = parse_user_agent(user_agent_string)
            
            # Determine device type
            if user_agent.is_mobile:
                device_type = "mobile"
            elif user_agent.is_tablet:
                device_type = "tablet"
            elif user_agent.is_pc:
                device_type = "desktop"
            else:
                device_type = "bot" if user_agent.is_bot else "unknown"
            
            # Extract browser info
            browser_family = user_agent.browser.family
            browser_version = user_agent.browser.version_string
            browser = f"{browser_family} {browser_version}" if browser_version else browser_family
            
            # Extract OS info
            os_family = user_agent.os.family
            os_version = user_agent.os.version_string
            os = f"{os_family} {os_version}" if os_version else os_family
            
        except Exception as e:
            await log.warning(
                "Failed to parse User-Agent",
                user_agent=user_agent_string,
                error=str(e)
            )
    
    # Create session record
    session = models.UserSession(
        user_id=user_id,
        refresh_jti=refresh_jti,
        ip_address=ip_address,
        user_agent=user_agent_string,
        device_type=device_type,
        browser=browser,
        os=os,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
        is_suspicious=False,
    )
    
    db.add(session)
    await db.flush()  # Get session.id without committing
    
    await log.info(
        "Session created",
        session_id=session.id,
        user_id=user_id,
        ip_address=ip_address,
        device_type=device_type,
        browser=browser,
        os=os
    )
    
    return session


async def check_new_ip_address(db: AsyncSession, user_id: int, ip_address: Optional[str]) -> bool:
    """
    Check if this IP address has been used before by this user.
    
    Args:
        db: Database session
        user_id: User ID
        ip_address: IP address to check
    
    Returns:
        True if this is a new IP address, False otherwise
    """
    if not ip_address:
        return False
    
    # Query for any previous session from this IP
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.ip_address == ip_address,
            )
        )
        .limit(1)
    )
    existing_session = result.scalar_one_or_none()
    
    is_new = existing_session is None
    
    if is_new:
        await log.warning(
            "New IP address detected for user",
            user_id=user_id,
            ip_address=ip_address
        )
    
    return is_new


async def get_active_sessions(
    db: AsyncSession,
    user_id: int,
    current_refresh_jti: Optional[str] = None
) -> list[models.UserSession]:
    """
    Get all active sessions for a user.
    
    Args:
        db: Database session
        user_id: User ID
        current_refresh_jti: Current refresh token JTI (to mark as current)
    
    Returns:
        List of active UserSession instances
    """
    now = datetime.now(timezone.utc)
    
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > now
            )
        )
        .order_by(models.UserSession.last_activity_at.desc())
    )
    
    sessions = result.scalars().all()
    
    await log.info(
        "Retrieved active sessions",
        user_id=user_id,
        session_count=len(sessions)
    )
    
    return list(sessions)


async def revoke_session(
    db: AsyncSession,
    session_id: int,
    user_id: int
) -> bool:
    """
    Revoke a specific session.

    Args:
        db: Database session
        session_id: Session ID to revoke
        user_id: User ID (for authorization check)

    Returns:
        True if session was revoked, False if not found
    """
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.id == session_id,
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None)  # Only revoke active sessions
            )
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        await log.warning(
            "Session not found for revocation or already revoked",
            session_id=session_id,
            user_id=user_id
        )
        return False

    # Mark as revoked
    session.revoked_at = datetime.now(timezone.utc)
    db.add(session)

    # Blacklist the refresh token in Redis AND delete session key
    try:
        ttl = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            # Add to blacklist
            await safe_redis_set(
                f"blacklist:{session.refresh_jti}",
                "revoked_by_user",
                ex=ttl
            )
            # ✅ FIX: Delete session key from Redis for immediate revocation
            await safe_redis_delete(f"session:{session.refresh_jti}")
            await log.info(
                "Session key deleted from Redis",
                session_id=session_id,
                refresh_jti=session.refresh_jti[:8] + "..."
            )
    except Exception as redis_error:
        await log.warning(
            "Failed to blacklist/delete refresh token in Redis",
            session_id=session_id,
            error=str(redis_error)
        )
        # Continue anyway - database revocation is sufficient

    await db.commit()

    await log.info(
        "Session revoked",
        session_id=session_id,
        user_id=user_id,
        refresh_jti=session.refresh_jti
    )

    return True


async def update_session_activity(
    db: AsyncSession,
    old_refresh_jti: str,
    new_refresh_jti: str,
    user_id: int
) -> Optional[models.UserSession]:
    """
    Update session's last_activity_at and refresh_jti when token is refreshed.
    
    Args:
        db: Database session
        old_refresh_jti: Old refresh token JTI
        new_refresh_jti: New refresh token JTI
        user_id: User ID
    
    Returns:
        Updated UserSession instance, or None if not found
    """
    result = await db.execute(
        select(models.UserSession)
        .where(
            and_(
                models.UserSession.refresh_jti == old_refresh_jti,
                models.UserSession.user_id == user_id
            )
        )
    )
    session = result.scalar_one_or_none()
    
    if session:
        session.last_activity_at = datetime.now(timezone.utc)
        session.refresh_jti = new_refresh_jti
        db.add(session)
        
        await log.debug(
            "Session activity updated",
            session_id=session.id,
            user_id=user_id,
            old_jti=old_refresh_jti[:8],
            new_jti=new_refresh_jti[:8]
        )
    else:
        await log.warning(
            "Session not found for activity update",
            old_refresh_jti=old_refresh_jti[:8],
            user_id=user_id
        )
    
    return session


async def revoke_all_other_sessions(
    db: AsyncSession,
    user_id: int,
    except_session_id: Optional[int] = None
) -> int:
    """
    Revoke all sessions except optionally one specific session.

    Args:
        db: Database session
        user_id: User ID
        except_session_id: Optional session ID to keep active (usually current session)

    Returns:
        Number of sessions revoked
    """
    now = datetime.now(timezone.utc)

    # Build query conditions
    conditions = [
        models.UserSession.user_id == user_id,
        models.UserSession.revoked_at.is_(None)
    ]

    # Exclude specific session if provided
    if except_session_id is not None:
        conditions.append(models.UserSession.id != except_session_id)

    # Get all active sessions (except the one to preserve)
    result = await db.execute(
        select(models.UserSession).where(and_(*conditions))
    )
    sessions = result.scalars().all()

    # Revoke all
    revoked_count = 0
    for session in sessions:
        session.revoked_at = now
        db.add(session)

        # Blacklist in Redis AND delete session key
        try:
            ttl = int((session.expires_at - now).total_seconds())
            if ttl > 0:
                # Add to blacklist
                await safe_redis_set(
                    f"blacklist:{session.refresh_jti}",
                    "revoked_by_user",
                    ex=ttl
                )
                # ✅ FIX: Delete session key from Redis for immediate revocation
                await safe_redis_delete(f"session:{session.refresh_jti}")
        except Exception as redis_error:
            await log.warning(
                "Failed to blacklist/delete refresh token in Redis",
                session_id=session.id,
                error=str(redis_error)
            )
            # Continue anyway

        revoked_count += 1

    await db.commit()

    await log.info(
        "Revoked all other sessions",
        user_id=user_id,
        except_session_id=except_session_id,
        revoked_count=revoked_count
    )

    return revoked_count


```


## 📄 `services\user_service.py`

**Lines:** 667 | **Size:** 25059 bytes

```python

# app/services/user_service.py
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .. import models, schemas

from ..config import settings
from ..database import safe_redis_delete, safe_redis_set, safe_redis_pipeline
from ..security import (
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_password_reset_token,
)
from ..utils import file_helpers
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


# --- Các hàm lấy User (Read-only, không cần rollback) ---


async def get_user_by_username(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    query = select(models.User).where(models.User.username == username.strip())
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
        await db.refresh(user) # Vẫn refresh
        return user # <-- SỬA: Trả về user
    return None # <-- SỬA: Trả về None nếu không tìm thấy


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    cleaned_email = email.strip()
    query = select(models.User).where(models.User.email == cleaned_email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
         await db.refresh(user) # Vẫn refresh
         return user # <-- SỬA: Trả về user
    return None # <-- SỬA: Trả về None nếu không tìm thấy


async def get_user_by_id(db: AsyncSession, user_id: int) -> models.User:
    user = await db.get(models.User, user_id)
    if not user:
        raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
    await db.refresh(user) # <-- THÊM DÒNG NÀY
    return user


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> models.User:
    """
    Xác thực người dùng.
    ✅ FIXED: Chống Timing Attack bằng cách luôn thực hiện hash comparison.
    """
    user = await get_user_by_username(db, username)

    # === ⭐️ SỬA LỖI TIMING ATTACK ===
    # 1. Chuẩn bị một dummy hash hợp lệ (phải bắt đầu bằng $2b$ và có độ dài đúng)
    # Bạn có thể tạo hash này một lần từ một mật khẩu ngẫu nhiên.
    # Ví dụ: get_password_hash("a_very_random_dummy_password_for_timing_attack")
    dummy_hash = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"  # Thay bằng hash thật

    # 2. Xác định hash nào sẽ được dùng để kiểm tra
    hash_to_check = user.password_hash if user else dummy_hash

    # 3. LUÔN LUÔN thực hiện việc kiểm tra mật khẩu (tốn thời gian)
    is_password_valid = verify_password(password, hash_to_check)

    # 4. KIỂM TRA KẾT QUẢ SAU KHI ĐÃ VERIFY
    # Lỗi nếu user không tồn tại HOẶC mật khẩu không hợp lệ
    if not user or not is_password_valid:
        await log.warning("Authentication failed", username=username, reason="Invalid user or password")
        raise InvalidCredentials()

    await db.refresh(user) # <-- THÊM DÒNG NÀY
    await log.info("Authentication successful", username=username)
    return user


# --- Hàm Tạo User ---


async def create_user(db: AsyncSession, user_in: schemas.UserCreate) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        db_user = models.User(
            username=user_in.username.strip(),
            email=user_in.email.strip(),
            full_name=user_in.full_name,
            password_hash=hashed_password,
            role="user",
            status="active",
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create user",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


async def create_user_by_admin(
    db: AsyncSession,
    user_in: schemas.AdminUserCreate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        db_user = models.User(
            username=user_in.username.strip(),
            email=user_in.email.strip(),
            full_name=user_in.full_name,
            password_hash=hashed_password,
            role=user_in.role,
            status=user_in.status,
            avatar_url=None,
        )
        if avatar_file:
            await log.debug(
                "Processing avatar for new admin-created user",
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt bởi khối except bên ngoài
            new_avatar_url = await file_helpers.save_avatar(avatar_file)
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Avatar saved for new user", user=user_in.username, url=new_avatar_url
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create user by admin",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Lấy danh sách User (Read-only) ---


async def get_users(
    db: AsyncSession, params: Dict[str, Any], skip: int = 0, limit: int = 100
) -> Tuple[int, List[models.User]]:
    # ... (Không thay đổi, read-only) ...
    query = select(models.User)

    allowed_filters = {
        "role": models.User.role,
        "status": models.User.status,
    }
    text_search_fields = [
        models.User.username,
        models.User.full_name,
        models.User.email,
    ]

    for key, value in params.items():
        if key in allowed_filters and value:
            values_to_filter = [v.strip() for v in value.split(",")]
            query = query.filter(allowed_filters[key].in_(values_to_filter))
        elif key == "search" and value:
            search_term = f"%{value.strip()}%"
            search_conditions = [
                field.ilike(search_term) for field in text_search_fields
            ]
            query = query.filter(or_(*search_conditions))

    count_query = select(func.count()).select_from(query.alias())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    sort = params.get("sort", "id")
    order = params.get("order", "asc")
    if hasattr(models.User, sort):
        sort_column = getattr(models.User, sort)
        if order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

    paged_query = query.offset(skip).limit(limit)
    users_result = await db.execute(paged_query)
    users = users_result.scalars().all()

    return total_count, users


# --- Hàm Cập nhật User ---


async def update_user(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"] != db_user.email:
            # get_user_by_email đã có refresh bên trong
            existing_user = await get_user_by_email(db, update_data["email"])
            # So sánh ID an toàn vì existing_user đã được refresh (nếu tìm thấy)
            if existing_user and existing_user.id != user_id_for_logging: # Sử dụng biến cục bộ
                raise DuplicateResourceError(
                    detail="Email already registered by another user"
                )

        for field, value in update_data.items():
            if value is not None:
                setattr(
                    db_user, field, value.strip() if isinstance(value, str) else value
                )

        if avatar_file:
            await log.debug(
                "Processing avatar update for user",
                user_id=db_user.id,
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Avatar updated successfully for user",
                user_id=db_user.id,
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update user",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_profile(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field in ["full_name", "phone_number", "email"]:
                if value is not None:
                    setattr(
                        db_user,
                        field,
                        value.strip() if isinstance(value, str) else value,
                    )

        if avatar_file:
            await log.debug(
                "Processing profile avatar update",
                user_id=user_id_for_logging, 
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Profile avatar updated successfully",
                user_id=user_id_for_logging, 
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update profile",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Xóa User ---


async def delete_user(db: AsyncSession, user_id: int):
    """Xóa một user. Ném ResourceNotFound nếu không tìm thấy."""
    try:
        user_to_delete = await db.get(models.User, user_id)
        if not user_to_delete:
            raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
        await db.delete(user_to_delete)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error("Failed to delete user", user_id=user_id, error=str(e), exc_info=True)
        raise e


# --- Logic Password (Hàm handle_forgot_password chỉ đọc, không commit) ---


async def handle_forgot_password(db: AsyncSession, email_in: str):
    from ..celery_utils import send_password_reset_email_task
    cleaned_email = email_in.strip()
    user = await get_user_by_email(db, email=cleaned_email)
    if not user:
        await log.debug("User not found for forgot password request", email=cleaned_email)
        return

    await log.info(
        "User found for forgot password request. Sending reset email.", user_id=user.id
    )
    token = create_password_reset_token(email=user.email)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    send_password_reset_email_task.delay(
        email_to=user.email, reset_url=reset_url, username=user.username
    )
    # Không raise lỗi ở đây vì đã trả về 202 cho client


async def reset_password(
    db: AsyncSession, token: str, new_password: str
) -> models.User:
    """Đặt lại mật khẩu từ token. Ném InvalidToken hoặc ResourceNotFound."""
    try:
        email = verify_password_reset_token(token)
        if not email:
            await log.warning("Invalid reset token attempt", token_prefix=token[:10])
            raise InvalidToken()
        
        user = await get_user_by_email(db, email=email)
        if not user:
            await log.warning("Reset token for non-existent user", email=email)
            raise ResourceNotFoundError(
                detail="User associated with this token not found."
            )

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info("User password reset successfully", user_id=user.id)
        return user
    except Exception as e:
        await db.rollback()
        await log.error("Failed to reset password", token=token, error=str(e), exc_info=True)
        raise e


async def change_password(
    db: AsyncSession, user: models.User, old_password: str, new_password: str
):
    """Người dùng tự đổi mật khẩu. Ném BadRequest nếu mật khẩu cũ sai."""
    user_id_for_logging = user.id
    try:
        if not verify_password(old_password, user.password_hash):
            raise BadRequest(detail="Incorrect old password")

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info("User changed password successfully", user_id=user_id_for_logging)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to change password", user_id=user_id_for_logging, error=str(e), exc_info=True
        )
        raise e

async def remove_user_from_global_blacklist(user_id: int):
    """Xóa user khỏi global blacklist (thường gọi sau khi login thành công)."""
    blacklist_key = f"user_blacklist:{user_id}"
    try:
        deleted_count = await safe_redis_delete(blacklist_key)
        if deleted_count > 0:
            await log.info("Removed user from global blacklist", user_id=user_id)
    except Exception as e:
        await log.error("Failed to remove user from global blacklist", user_id=user_id, error=str(e))
        raise # Ném lại lỗi để router có thể bắt


async def set_password_by_admin(
    db: AsyncSession, user_id: int, new_password: str
) -> models.User:
    """Admin đặt lại mật khẩu cho người dùng. Ném ResourceNotFound."""
    try:
        user = await get_user_by_id(db, user_id)  # Hàm này đã raise 404
        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info(
            "Admin set password for user successfully",
            admin_user="admin",
            user_id=user.id,
        )
        return user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to set password by admin",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def invalidate_all_sessions(db: AsyncSession, user: models.User):
    """
    Vô hiệu hóa tất cả các phiên hoạt động của người dùng (thường sau khi đổi mật khẩu).
    """
    try:
        # 1. Xóa JTI đang hoạt động trong DB
        user.active_jti = None
        db.add(user)

        # 2. Xóa JTI refresh token hiện tại khỏi Redis
        try:
            # Lấy TẤT CẢ các session (kể cả đã hết hạn) để đảm bảo blacklist JTI
            result = await db.execute(
                select(models.UserSession).where(models.UserSession.user_id == user.id)
            )
            all_sessions = result.scalars().all()
            
            async with safe_redis_pipeline(transaction=True) as pipe:
                for session in all_sessions:
                    # Xóa key session đang active
                    pipe.delete(f"session:{session.refresh_jti}")
                    # Blacklist JTI của session đó
                    ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                    pipe.set(f"blacklist:{session.refresh_jti}", "password_changed", ex=max(60, ttl))
            
            await log.info(
                f"Invalidated all {len(all_sessions)} session keys/JTIs in Redis", 
                user_id=user.id
            )
        except Exception as e_redis_del:
            await log.error(
                "Failed to clear multi-session keys from Redis",
                user_id=user.id,
                error=str(e_redis_del),
            )

        # 3. Thêm user ID vào blacklist toàn cục trên Redis
        # Thời gian sống bằng thời gian sống tối đa của refresh token
        # (Để đảm bảo mọi token cũ đều bị chặn cho đến khi hết hạn tự nhiên)
        max_token_lifetime_seconds = int(
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )

        # Đảm bảo TTL không âm
        if max_token_lifetime_seconds <= 0:
            max_token_lifetime_seconds = 60  # Đặt TTL tối thiểu là 1 phút

        try:
            blacklist_key = f"user_blacklist:{user.id}"
            await safe_redis_set(
                blacklist_key, "sessions_invalidated", ex=max_token_lifetime_seconds
            )
            await log.info(
                "User added to global blacklist",
                user_id=user.id,
                ttl_seconds=max_token_lifetime_seconds,
            )
        except Exception as e_redis_set:
            # Lỗi nghiêm trọng nếu không thể blacklist user, rollback DB
            await log.error(
                "CRITICAL: Failed to add user to global blacklist, rolling back DB changes",
                user_id=user.id,
                error=str(e_redis_set),
            )
            await db.rollback()  # Rollback việc xóa active_jti
            raise  # Ném lại lỗi để báo 500

        # 4. Commit DB (chỉ khi Redis blacklist thành công)
        await db.commit()
        await log.info("All sessions invalidated successfully for user", user_id=user.id)

    except Exception as e:
        # Bắt các lỗi khác (ngoài lỗi Redis blacklist đã xử lý)
        await db.rollback()
        await log.error(
            "Failed to invalidate sessions",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # Không ném lại lỗi ở đây trừ khi lỗi Redis blacklist xảy ra
        if "Failed to add user to global blacklist" not in str(e):
            # Ném lỗi khác để router xử lý (vd: lỗi DB commit)
            raise HTTPException(status_code=500, detail="Could not invalidate sessions")


# --- Logic Logout ---


async def logout_user(db: AsyncSession, user: models.User):
    try:
        user.active_jti = None
        db.add(user)
        await db.commit()
        await log.info("User logged out successfully", user_id=user.id)
    except Exception as e:
        await db.rollback()
        await log.error("Failed to logout user", user_id=user.id, error=str(e), exc_info=True)
        raise e


# --- Bulk Action ---

async def perform_bulk_action(
    db: AsyncSession,
    action: str,
    user_ids: List[int],
    admin_user: models.User,
    new_status: Optional[str] = None,
):
    """
    Performs bulk actions (delete, change_status) on users.
    ✅ IMPROVED: Validates 'new_status' before querying DB for 'change_status'.
    """
    try:
        # --- IMPROVEMENT: Validate input BEFORE DB query ---
        if action == "change_status":
            # Check if new_status is provided and valid *early*
            if new_status not in ["active", "pending", "banned"]:
                await log.warning(
                    "Bulk action failed: Invalid status value provided.",
                    action=action,
                    provided_status=new_status,
                    admin_id=admin_user.id
                )
                raise BadRequest(detail=f"Invalid status value: {new_status}")
        elif action not in ["delete"]: # Check if action itself is valid
             await log.warning(
                    "Bulk action failed: Unsupported action.",
                    action=action,
                    admin_id=admin_user.id
                )
             raise BadRequest(detail=f"Unsupported bulk action: {action}.")
        # --- END IMPROVEMENT ---

        # Proceed only if the action and status (if applicable) are valid

        # Query users *after* initial validation
        query = select(models.User).where(models.User.id.in_(user_ids))
        users_to_process_result = await db.execute(query)
        users_to_process = users_to_process_result.scalars().all()

        if not users_to_process:
            # It's okay if no users match, just return an appropriate message
            await log.info("Bulk action: No users found matching provided IDs.", user_ids=user_ids, admin_id=admin_user.id)
            return "No users found for the provided IDs. 0 users affected."
            # raise ResourceNotFoundError(detail="No users found for the provided IDs.") # Changed behavior

        processed_count = 0
        message = ""
        if action == "delete":
            ids_to_delete = []
            for user in users_to_process:
                if user.id == admin_user.id:
                    await log.warning(
                        "Admin attempted to delete self during bulk action, skipping.",
                        admin_id=admin_user.id,
                    )
                    continue
                await db.delete(user) # Mark for deletion
                ids_to_delete.append(user.id)
                processed_count += 1
            message = f"Successfully deleted {processed_count} users."
            await log.info(
                "Admin bulk deleted users",
                admin_id=admin_user.id,
                deleted_ids=ids_to_delete,
            )

        elif action == "change_status":
            # We already validated new_status earlier
            ids_changed = []
            for user in users_to_process:
                if user.status != new_status: # Only update if status is different
                    user.status = new_status
                    db.add(user) # Mark for update
                    ids_changed.append(user.id)
                    processed_count += 1
                else:
                    await log.debug("Skipping status update for user already in desired state.", user_id=user.id, status=new_status)

            message = f"Successfully updated status to '{new_status}' for {processed_count} users."
            if ids_changed: # Only log if changes were actually made
                await log.info(
                    "Admin bulk changed user status",
                    admin_id=admin_user.id,
                    changed_ids=ids_changed,
                    new_status=new_status,
                )

        await db.commit() # Commit all changes (deletes or updates)
        return message

    except Exception as e:
        await db.rollback() # Ensure rollback on any error
        await log.error(
            "Failed to perform bulk action",
            action=action,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        # Re-raise the original exception if it's a known validation error,
        # otherwise raise a generic error.
        if isinstance(e, (BadRequest, ResourceNotFoundError)):
             raise e
        else:
             # You might want to raise a more generic 500 error here
             # depending on your desired API behavior for unexpected errors.
             raise # Re-raise the original unexpected error for now

```


## 📄 `utils\__init__.py`

**Lines:** 3 | **Size:** 114 bytes

```python
# app/utils/__init__.py
# File này để trống để đánh dấu thư mục utils là một Python package.

```


## 📄 `utils\exceptions.py`

**Lines:** 55 | **Size:** 1954 bytes

```python
# app/utils/exceptions.py
from fastapi import status  # Bỏ HTTPException và JSONResponse khỏi đây

# === Định nghĩa lại các lớp Exception tùy chỉnh ===


class BaseAppException(Exception):
    """Lớp cơ sở cho các exception tùy chỉnh trong ứng dụng."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An internal server error occurred."

    def __init__(self, detail: str = None):
        if detail is not None:
            self.detail = detail


class ResourceNotFoundError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_404_NOT_FOUND
    detail = "The requested resource was not found."


class DuplicateResourceError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_409_CONFLICT
    detail = "This resource already exists."


class PermissionDeniedError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_403_FORBIDDEN
    detail = "You do not have permission to perform this action."


class AuthenticationError(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Authentication required."
    headers = {"WWW-Authenticate": "Bearer"}  # Giữ lại headers nếu cần


class InvalidCredentials(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Incorrect username or password."


class InvalidToken(AuthenticationError):  # Kế thừa từ AuthenticationError
    detail = "Could not validate credentials (invalid or expired token)."


class BadRequest(BaseAppException):  # Kế thừa từ BaseAppException
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request."


# === KẾT THÚC ĐỊNH NGHĨA LẠI ===

# Các global handler đã được định nghĩa trong main.py, không cần ở đây nữa.

```


## 📄 `utils\file_helpers.py`

**Lines:** 242 | **Size:** 10257 bytes

```python
# app/utils/file_helpers.py
import os
import uuid
from pathlib import Path  # 👈 *** THÊM IMPORT NÀY ***

import aiofiles
import magic
import structlog
from fastapi import HTTPException, UploadFile, status

from ..config import settings

log = structlog.get_logger(__name__)
# === ⭐️ SỬ DỤNG GIÁ TRỊ TỪ settings ⭐️ ===
# Chuyển thành set để check nhanh hơn
ALLOWED_EXTENSIONS = set(settings.ALLOWED_AVATAR_EXTENSIONS)
ALLOWED_MIME_TYPES = set(settings.ALLOWED_AVATAR_MIME_TYPES)
MAX_CONTENT_LENGTH = settings.MAX_AVATAR_CONTENT_LENGTH  # Đã tính toán trong config.py
UPLOAD_FOLDER = (
    settings.AVATAR_UPLOAD_FOLDER
)  # Đã tính toán và đảm bảo tồn tại trong config.py
# === KẾT THÚC SỬ DỤNG settings ===


async def save_avatar(file: UploadFile, old_avatar_url: str = None) -> str:
    """
    Lưu file avatar một cách an toàn:
    1. Kiểm tra extension.
    2. Đọc file vào bộ nhớ.
    3. Kiểm tra kích thước thật (size).
    4. Kiểm tra nội dung (magic bytes/MIME type).
    5. Tạo tên file duy nhất (UUID).
    6. Kiểm tra Path Traversal.
    7. Xóa file cũ (nếu có).
    8. Lưu file mới.

    Trả về URL tương đối của file đã lưu.
    Ném HTTPException nếu có lỗi.
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected."
        )

    # 1. Kiểm tra extension (bước lọc cơ bản)
    file_extension = ""
    if "." in file.filename:
        # Lấy phần sau dấu chấm cuối cùng
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if not file_extension or file_extension not in ALLOWED_EXTENSIONS:
        await log.warning(
            "Upload rejected: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
        )

    # 2. Đọc file vào bộ nhớ (an toàn hơn file.size, tránh TOCTOU)
    try:
        content = await file.read()
    except Exception as e:
        await log.error(
            "Failed to read uploaded file content", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read file content.",
        )

    # 3. Kiểm tra kích thước thật của nội dung đã đọc
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
        )
    if len(content) > MAX_CONTENT_LENGTH:
        await log.warning(
            "Upload rejected: File size exceeded limit",
            filename=file.filename,
            size=len(content),
            limit=MAX_CONTENT_LENGTH,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, # <-- Thay đổi ở đây
            detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB.",
        )

    # 4. Kiểm tra Magic Bytes (MIME type) - Bước bảo mật quan trọng nhất!
    try:
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in ALLOWED_MIME_TYPES:
            await log.warning(
                "Upload rejected: Invalid MIME type detected",
                filename=file.filename,
                detected_mime=mime_type,
                allowed_mimes=list(ALLOWED_MIME_TYPES),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                # Không tiết lộ MIME type chi tiết cho client
                detail=f"File content is not a valid image format. Allowed: {', '.join(sorted(list(ALLOWED_EXTENSIONS)))}.",
            )
        await log.debug("MIME type validated", filename=file.filename, mime_type=mime_type)
    except HTTPException:
        raise  # Ném lại lỗi 400 từ check MIME
    except Exception as e:
        await log.error(
            "Magic bytes check failed",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not verify file content.",
        )

    # --- Nếu tất cả kiểm tra đã qua ---

    # 5. Tạo tên file mới duy nhất (an toàn)
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)

    # 6. KIỂM TRA PATH TRAVERSAL (DEFENSE-IN-DEPTH)
    try:
        # Lấy đường dẫn tuyệt đối, chuẩn hóa (resolve) mọi '..'
        # strict=True đảm bảo thư mục upload thực sự tồn tại (đã được tạo trong config.py)
        upload_folder_abs = Path(UPLOAD_FOLDER).resolve(strict=True)
        # strict=False vì file chưa tồn tại khi resolve
        file_path_abs = Path(file_path).resolve(strict=False)

        # Kiểm tra xem đường dẫn file có nằm TRONG thư mục upload không
        # Dùng commonpath hoặc is_relative_to (Python 3.9+)
        # if not file_path_abs.is_relative_to(upload_folder_abs): # Cần Python 3.9+
        if os.path.commonpath([upload_folder_abs, file_path_abs]) != str(
            upload_folder_abs
        ):
            await log.critical(
                "🚨 PATH TRAVERSAL ATTEMPT DETECTED!",
                filename=file.filename,  # Log tên file gốc để điều tra
                generated_path=file_path,
                resolved_path=str(file_path_abs),
                upload_dir=str(upload_folder_abs),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path detected.",  # Thông báo chung chung cho client
            )
    except HTTPException:
        raise  # Ném lại lỗi 400
    except Exception as e:
        # Bắt lỗi nếu resolve path thất bại (vd: tên file chứa ký tự không hợp lệ)
        await log.error(
            "Path validation/resolution failed", filename=file.filename, error=str(e)
        )
        raise HTTPException(
            status_code=400, detail="Invalid characters in filename or path."
        )

    # 7. Xóa file avatar cũ (nếu có) - An toàn hơn
    if old_avatar_url:
        try:
            # Chỉ lấy phần tên file từ URL (vd: /static/.../abc.png -> abc.png)
            old_file_name = os.path.basename(old_avatar_url)
            # Kiểm tra cơ bản tên file cũ
            if (
                old_file_name
                and ".." not in old_file_name
                and "/" not in old_file_name
                and "\\" not in old_file_name
            ):
                old_file_path = os.path.join(UPLOAD_FOLDER, old_file_name)
                # Kiểm tra lại đường dẫn tuyệt đối trước khi xóa
                old_file_path_abs = Path(old_file_path).resolve(strict=False)
                # if old_file_path_abs.is_relative_to(upload_folder_abs): # Python 3.9+
                if os.path.commonpath([upload_folder_abs, old_file_path_abs]) == str(
                    upload_folder_abs
                ):
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                        await log.info("Old avatar deleted successfully", path=old_file_path)
                    else:
                        await log.debug(
                            "Old avatar file not found, nothing to delete",
                            path=old_file_path,
                        )
                else:
                    await log.warning(
                        "Skipping deletion of potentially unsafe old avatar path",
                        old_url=old_avatar_url,
                        resolved_path=str(old_file_path_abs),
                    )
            else:
                await log.warning(
                    "Invalid old avatar URL format, skipping deletion",
                    old_url=old_avatar_url,
                )
        except Exception as e:
            # Không raise lỗi nếu xóa file cũ thất bại, chỉ log lại
            await log.error(
                "Failed to delete old avatar file", url=old_avatar_url, error=str(e)
            )

    # 8. Lưu file mới (ghi nội dung đã đọc và validate)
    try:
        async with aiofiles.open(file_path, "wb") as buffer:
            await buffer.write(content)
        await log.info("New avatar saved successfully", path=file_path, size=len(content))
    except Exception as e:
        await log.error("Failed to save new avatar file", path=file_path, error=str(e))
        # Cố gắng xóa file vừa tạo nếu lưu thất bại
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save avatar file.",
        )

    # Trả về URL tương đối để lưu vào DB
    # Tính toán đường dẫn tương đối từ thư mục static gốc
    try:
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
        relative_upload_path = os.path.relpath(UPLOAD_FOLDER, static_dir)
        # Đảm bảo dùng dấu / cho URL
        url_path = (
            f"/static/{relative_upload_path.replace(os.sep, '/')}/{unique_filename}"
        )
        return url_path
    except ValueError:
        await log.error(
            "Could not determine relative path for avatar URL",
            upload_folder=UPLOAD_FOLDER,
        )
        # Fallback trả về đường dẫn tuyệt đối (ít lý tưởng hơn)
        return file_path

```
