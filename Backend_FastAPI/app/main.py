# app/main.py
import asyncio  # ✅ V5: Thêm import
import logging
import os  # ✅ Import os để check path
import uuid
from contextlib import asynccontextmanager
from pathlib import Path  # ✅ Import Path để tạo absolute path

import casbin
import socketio  # ✅ V5: Thêm import
import structlog
import ujson
from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
from casbin_async_sqlalchemy_adapter import Base as CasbinBase
from fastapi import Depends, FastAPI, Request, Response, status  # ✅ V5: Thêm Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles  # ✅ Import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import database
from .celery_utils import celery_app
from .config import settings
from .database import engine as async_db_engine
from .database import redis_client as main_redis_client
from .database import safe_redis_ping
from .ratelimit import limiter
from .routers import (
    admin,
    auth,
    leads,
    notification_preferences,
    notifications,
    officer,
    organization,
    pipeline,
    profile,
    sessions,
    users
)

# ✅ V5: Import SIO, LUA loader, và Prometheus
from .socket_manager import load_rate_limit_script, sio
from .utils.exceptions import (
    AuthenticationError,
    BadRequest,
    BaseAppException,
    DuplicateResourceError,
    InvalidToken,
    PermissionDeniedError,
    ResourceNotFoundError,
)

# === Cấu hình Structured Logging ===
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        (
            structlog.dev.ConsoleRenderer()
            if settings.APP_ENV == "development"
            else structlog.processors.JSONRenderer(serializer=ujson.dumps)
        ),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    # ✅ SỬA LỖI (V5): Chuyển sang đồng bộ (sync) để không cần `await`
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Cấu hình handler cho logging
log_handler = logging.StreamHandler()
root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(log_handler)
root_logger.setLevel(settings.LOG_LEVEL.upper())

# === ✅ BẮT ĐẦU TẮT TIẾNG LOG THỪA ===

# Tắt log ồn ào của SQLAlchemy
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

# Tắt log DEBUG của Uvicorn (chỉ hiển thị INFO trở lên)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)

# ❗️ Tắt log DEBUG của Socket.IO và Engine.IO (QUAN TRỌNG NHẤT)
# Đây là những dòng log như "Sending packet...", "Received packet..."
logging.getLogger("socketio").setLevel(logging.INFO)
logging.getLogger("engineio").setLevel(logging.INFO)

# Tắt log DEBUG của thư viện user-agents
logging.getLogger("user_agents").setLevel(logging.INFO)

# === ✅ KẾT THÚC TẮT TIẾNG LOG THỪA ===

# Cấu hình log uvicorn
logging.getLogger("uvicorn.access").handlers.clear()
logging.getLogger("uvicorn.access").addHandler(log_handler)
logging.getLogger("uvicorn.error").handlers.clear()
logging.getLogger("uvicorn.error").addHandler(log_handler)

# Logger chính của app (giờ là đồng bộ)
log = structlog.get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- LOGIC STARTUP ---
    log.info("--- FastAPI application startup ---", environment=settings.APP_ENV)

    try:
        # (Giữ nguyên logic Casbin)
        async with async_db_engine.begin() as conn:
            await conn.run_sync(CasbinBase.metadata.create_all)
        log.info("Casbin 'casbin_rule' table checked/created.")
        adapter = AsyncCasbinAdapter(async_db_engine)
        log.info(f"Casbin Adapter successfully initialized: Type={type(adapter)}")
        enforcer = casbin.AsyncEnforcer("auth_model.conf", adapter)
        await enforcer.load_policy()
        app.state.enforcer = enforcer
        log.info("✅ Casbin AsyncEnforcer initialized and policies loaded.")

        # ✅ DEPRECATED: Default policies are now managed via Alembic migration
        # Migration: i4j5k6l7m8n9_add_default_casbin_policies.py
        #
        # This fallback logic is kept for backward compatibility only.
        # If this runs, it means the migration hasn't been executed yet.
        if not enforcer.get_policy():
            log.warning(
                "⚠️ No Casbin policies found! Adding default policies as FALLBACK. "
                "This should NOT happen in production if migrations are run correctly. "
                "Please run: alembic upgrade head"
            )
            # Admin policies (explicit paths due to keyMatch4 limitations)
            await enforcer.add_policy("role:admin", "/*", ".*")
            await enforcer.add_policy("role:admin", "/api/*", ".*")
            await enforcer.add_policy("role:admin", "/api/admin/*", ".*")
            await enforcer.add_policy("role:admin", "/api/admin/users/*", ".*")
            await enforcer.add_policy("role:admin", "/api/admin/roles/*", ".*")
            await enforcer.add_policy("role:admin", "/api/admin/policies/*", ".*")

            # ← PHASE 3 & 4: Very explicit sync endpoints (new paths to avoid route conflicts)
            await enforcer.add_policy("role:admin", "/api/admin/sync/status", "GET")
            await enforcer.add_policy("role:admin", "/api/admin/sync/users", "POST")
            await enforcer.add_policy("role:admin", "/api/admin/sync/*", ".*")
            await enforcer.add_policy("role:admin", "/api/admin/roles", "GET")
            await enforcer.add_policy("role:admin", "/api/admin/policies", "GET")
            await enforcer.add_policy("role:admin", "/api/admin/policies/statistics", "GET")
            await enforcer.add_policy("role:admin", "/api/admin/policies/suggestions", "GET")

            await enforcer.add_policy("role:manager", "/api/admin/users", ".*")
            await enforcer.add_policy("role:manager", "/api/leads/*", ".*")
            await enforcer.add_policy("role:manager", "/api/leads", "GET")
            await enforcer.add_policy("role:officer", "/api/leads", "GET")
            await enforcer.add_policy("role:officer", "/api/leads/{lead_id}", "GET")
            await enforcer.add_policy(
                "role:officer", "/api/leads/{lead_id}/consultations", "POST"
            )
            await enforcer.add_policy(
                "role:officer", "/api/leads/{lead_id}/action", "POST"
            )
            await enforcer.add_policy("role:user", "/api/profile", "GET")
            await enforcer.add_policy("role:user", "/api/profile", "PUT")
            await enforcer.add_policy("role:officer", "/api/profile", "GET")
            await enforcer.add_policy("role:officer", "/api/profile", "PUT")
            await enforcer.add_policy("role:manager", "/api/profile", "GET")
            await enforcer.add_policy("role:manager", "/api/profile", "PUT")

            # Notification policies - all authenticated users can access their own notifications
            await enforcer.add_policy("role:user", "/api/notifications", "GET")
            await enforcer.add_policy("role:user", "/api/notifications/mark-as-read", "POST")
            await enforcer.add_policy("role:user", "/api/notifications/mark-all-as-read", "POST")
            await enforcer.add_policy("role:user", "/api/notifications/{notification_id}", "DELETE")
            await enforcer.add_policy("role:officer", "/api/notifications", "GET")
            await enforcer.add_policy("role:officer", "/api/notifications/mark-as-read", "POST")
            await enforcer.add_policy("role:officer", "/api/notifications/mark-all-as-read", "POST")
            await enforcer.add_policy("role:officer", "/api/notifications/{notification_id}", "DELETE")
            await enforcer.add_policy("role:manager", "/api/notifications", "GET")
            await enforcer.add_policy("role:manager", "/api/notifications/mark-as-read", "POST")
            await enforcer.add_policy("role:manager", "/api/notifications/mark-all-as-read", "POST")
            await enforcer.add_policy("role:manager", "/api/notifications/{notification_id}", "DELETE")

            # ✅ SECURITY FIX: Organization policies - all authenticated users can read, admin can write
            # READ operations - accessible by all authenticated users
            await enforcer.add_policy("role:user", "/api/organization-units", "GET")
            await enforcer.add_policy("role:user", "/api/organization-units/tree-with-aggregation", "GET")
            await enforcer.add_policy("role:user", "/api/programs", "GET")
            await enforcer.add_policy("role:user", "/api/programs/{program_id}/offerings", "GET")
            await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info", "GET")
            await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
            await enforcer.add_policy("role:user", "/api/offerings/{offering_id}/academic-info/current", "GET")

            await enforcer.add_policy("role:officer", "/api/organization-units", "GET")
            await enforcer.add_policy("role:officer", "/api/organization-units/tree-with-aggregation", "GET")
            await enforcer.add_policy("role:officer", "/api/programs", "GET")
            await enforcer.add_policy("role:officer", "/api/programs/{program_id}/offerings", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/current", "GET")

            await enforcer.add_policy("role:manager", "/api/organization-units", "GET")
            await enforcer.add_policy("role:manager", "/api/organization-units/tree-with-aggregation", "GET")
            await enforcer.add_policy("role:manager", "/api/programs", "GET")
            await enforcer.add_policy("role:manager", "/api/programs/{program_id}/offerings", "GET")
            await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info", "GET")
            await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
            await enforcer.add_policy("role:manager", "/api/offerings/{offering_id}/academic-info/current", "GET")

            # WRITE operations - admin only (CREATE/UPDATE/DELETE academic info)
            await enforcer.add_policy("role:admin", "/api/offerings/{offering_id}/academic-info", "POST")
            await enforcer.add_policy("role:admin", "/api/academic-info/{academic_info_id}", "PATCH")
            await enforcer.add_policy("role:admin", "/api/academic-info/{academic_info_id}", "DELETE")

            log.warning("⚠️ Fallback default policies added. Please run migrations!")

    except Exception as e:
        log.critical(
            "❌ FAILED TO INITIALIZE OR CONFIGURE CASBIN ENFORCER!",
            error=str(e),
            exc_info=True,
        )

    # (Giữ nguyên logic Rate Limiter)
    if settings.APP_ENV != "test":
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        log.info("SlowAPI rate limiter INITIALIZED for non-test environment.")
    else:
        log.info("APP_ENV is 'test', skipping SlowAPI rate limiter setup.")

    # --- Kiểm tra Redis ---
    try:
        pong = await safe_redis_ping()
        log.info("✅ Redis connection successful", response=pong)

        # ✅ CẢI TIẾN: Vấn đề #1 - Tải LUA script khi khởi động
        await load_rate_limit_script()

    except Exception as e:
        log.error(
            "❌ FAILED TO CONNECT TO REDIS on startup!", error=str(e), exc_info=True
        )

    # --- Ứng dụng chạy ---
    yield

    # === ✅ CẢI TIẾN: Vấn đề #2 - Graceful Shutdown ===
    log.info("--- FastAPI application shutdown ---")

    try:
        # Thông báo cho tất cả client biết server sắp tắt
        await sio.emit(
            "server_shutdown",
            {"message": "Server is restarting. Please refresh in a moment."},
        )
        # Chờ 1 giây
        await asyncio.sleep(1)

        # ✅ SỬA LỖI: Lặp qua và ngắt kết nối từng client

        all_sids = []
        try:
            # SỬA: Lấy SIDs từ server Engine.IO (EIO)
            # `eio.sockets` là dict chứa các socket đang hoạt động
            all_sids = list(sio.eio.sockets.keys())  # <--- ĐÃ SỬA
        except Exception as e_get_sid:
            log.error("Failed to get SIDs for shutdown", error=str(e_get_sid))
            all_sids = []  # Đặt là list rỗng để bỏ qua bước disconnect

        if all_sids:
            log.info(f"Disconnecting {len(all_sids)} active socket clients...")
            for sid in all_sids:
                try:
                    # Ngắt kết nối từng client
                    await sio.disconnect(sid)
                except Exception as e_client:
                    # Log lỗi nếu không ngắt kết nối được 1 client, nhưng vẫn tiếp tục
                    log.warning(
                        f"Error disconnecting client {sid}", error=str(e_client)
                    )
            log.info("Socket.IO server connections closed gracefully")
        else:
            log.info("No active socket clients to disconnect.")

    except Exception as e:
        # Lỗi này giờ đây chỉ bắt các lỗi chung (ví dụ: lỗi khi emit)
        log.error("Error during Socket.IO shutdown", error=str(e))

    try:
        await main_redis_client.aclose()
        log.info("✅ Main Redis client connection closed.")
    except Exception as e:
        log.error(
            "Error closing main Redis client connection during shutdown.", error=str(e)
        )


# === KHỞI TẠO APP ===
app = FastAPI(
    title="QLTS Project API with FastAPI",
    description="API for managing leads, users, and system configurations.",
    version="1.0.0",
    lifespan=lifespan,
)

# === ✅ V5: MOUNT SOCKET.IO APP ===
# Bọc ứng dụng FastAPI BÊN TRONG ứng dụng Socket.IO
app_with_sockets = socketio.ASGIApp(sio, app)


# ===============================================================
# === EXCEPTION HANDLERS (Đã xóa `await` khỏi log) =============
# ===============================================================


@app.exception_handler(InvalidToken)
async def invalid_token_handler(request: Request, exc: InvalidToken):
    log.warning(  # ✅ SỬA LỖI: Xóa `await`
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
    log.warning(  # ✅ SỬA LỖI: Xóa `await`
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
    log.warning(
        "Bad Request", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.detail},
    )


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
    log.warning(
        "Permission Denied", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": exc.detail},
    )


@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError):
    log.warning(
        "Resource Not Found", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": exc.detail},
    )


@app.exception_handler(DuplicateResourceError)
async def duplicate_resource_handler(request: Request, exc: DuplicateResourceError):
    log.warning(
        "Duplicate Resource", detail=exc.detail, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_details = []
    for error in exc.errors():
        field_parts = [str(loc_part) for loc_part in error.get("loc", [])]
        field = " -> ".join(field_parts) if field_parts else "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    log.warning(
        "Request Validation Error", errors=error_details, path=request.url.path
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException):
    log.error(  # ✅ SỬA LỖI: Xóa `await`
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


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    error_details = []
    for error in exc.errors():
        field = " -> ".join(map(str, error.get("loc", []))) or "body"
        message = error.get("msg", "Unknown validation error")
        error_details.append({"field": field, "message": message})

    log.warning(
        "Pydantic Validation Error inside endpoint",
        errors=error_details,
        path=request.url.path,
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Validation Error", "errors": error_details},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.exception(
        "Unhandled Internal Server Error", path=request.url.path, exc_info=True
    )  # ✅ SỬA LỖI: Xóa `await`
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal server error occurred."},
    )


# ===============================================================
# === MIDDLEWARES =============================================
# ===============================================================


@app.middleware("http")
async def request_id_tracking_middleware(request: Request, call_next):
    # (Giữ nguyên logic)
    structlog.contextvars.clear_contextvars()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.clear_contextvars()
    return response


# ===============================================================
# === CORS MIDDLEWARE (✅ SECURITY FIX: Prevent wildcard fallback)
# ===============================================================

# Validate CORS_ORIGINS at startup - fail-fast if misconfigured
_cors_origins = (
    [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
    if settings.CORS_ORIGINS
    else []
)

# 🔒 SECURITY: Fail-fast in production if wildcard or empty
if settings.APP_ENV == "production":
    if "*" in _cors_origins or not _cors_origins:
        log.critical(
            "🚨 CRITICAL SECURITY ERROR: CORS wildcard or empty origins not allowed in production!",
            cors_origins=settings.CORS_ORIGINS or "NOT SET",
            app_env=settings.APP_ENV,
        )
        raise RuntimeError(
            "CRITICAL SECURITY ERROR: CORS_ORIGINS environment variable must be set in production. "
            "Wildcard (*) origins are not allowed with credentials. "
            f"Current CORS_ORIGINS: {settings.CORS_ORIGINS or 'NOT SET'}. "
            "Set CORS_ORIGINS in your .env file (e.g., CORS_ORIGINS=https://app.example.com)"
        )

    # Additional check: Ensure all origins use HTTPS in production
    for origin in _cors_origins:
        if not origin.startswith("https://"):
            log.critical(
                "🚨 SECURITY ERROR: All CORS origins must use HTTPS in production",
                invalid_origin=origin,
            )
            raise RuntimeError(
                f"SECURITY ERROR: All CORS origins must use HTTPS in production. "
                f"Invalid origin: {origin}"
            )

    log.info("✅ CORS configuration validated for production", origins=_cors_origins)

# In development, default to localhost if not set
if settings.APP_ENV == "development" and not _cors_origins:
    _cors_origins = ["http://localhost:5173", "http://localhost:3000"]
    log.warning(
        "⚠️ CORS_ORIGINS not set in development. Using default localhost origins",
        default_origins=_cors_origins,
    )

# In test environment, allow test origins
if settings.APP_ENV == "test" and not _cors_origins:
    _cors_origins = ["http://testserver", "http://localhost"]
    log.info("Test environment: Using test CORS origins", origins=_cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Set-Cookie"],
)


# (Giữ nguyên Security Headers Middleware)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ===============================================================
# === ROUTERS ===================================================
# ===============================================================

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(profile.router, prefix="/api/profile", tags=["Profile"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(sessions.router, prefix="/api", tags=["Sessions"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(notification_preferences.router, prefix="/api/notifications", tags=["Notification Preferences"])
app.include_router(leads.router, prefix="/api/leads", tags=["Leads"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(
    organization.router, prefix="/api", tags=["Organization"]
)
app.include_router(officer.router, prefix="/api", tags=["Officer Dashboard"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
# ===============================================================
# === STATIC FILES ==============================================
# ===============================================================

# Mount static files directory to serve avatars and other static content
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"✅ Static files mounted at /static from {STATIC_DIR}")
else:
    log.warning(f"⚠️ Static directory not found at {STATIC_DIR}")


# === ✅ CẢI TIẾN: Vấn đề #4 - Thêm Metrics Endpoint ===
@app.get("/metrics", tags=["Utilities"])
async def metrics():
    """Endpoint cho Prometheus cào (scrape) metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ===============================================================
# === HEALTH CHECKS (Đã xóa `await` khỏi log) ================
# ===============================================================


@app.get("/health", tags=["Utilities"])
async def health_check():
    """Kiểm tra API cơ bản."""
    log.debug("Health check endpoint was reached.")  # ✅ SỬA LỖI: Xóa `await`
    return {"status": "ok", "detail": "Server is healthy and running!"}


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

    # 1. Kiểm tra Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"]["status"] = "ok"
        checks["database"]["message"] = "Database connection successful"
    except Exception as e:
        is_healthy = False
        checks["database"]["status"] = "error"
        checks["database"][
            "message"
        ] = f"Database connection failed: {type(e).__name__}"
        log.error(
            "Health check failed (Database)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    # 2. Kiểm tra Redis
    try:
        await safe_redis_ping()
        checks["redis_cache"]["status"] = "ok"
        checks["redis_cache"]["message"] = "Redis connection successful"
    except Exception as e:
        is_healthy = False
        checks["redis_cache"]["status"] = "error"
        checks["redis_cache"][
            "message"
        ] = f"Redis connection failed: {type(e).__name__}"
        log.error(
            "Health check failed (Redis Cache)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    # 3. Kiểm tra Celery
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_workers = await run_in_threadpool(inspect.active)

        if active_workers:
            checks["celery_broker"]["status"] = "ok"
            checks["celery_broker"][
                "message"
            ] = f"Found {len(active_workers)} active worker(s)."
        else:
            is_healthy = False
            checks["celery_broker"]["status"] = "error"
            checks["celery_broker"]["message"] = "No active Celery workers found."
    except Exception as e:
        is_healthy = False
        checks["celery_broker"]["status"] = "error"
        checks["celery_broker"][
            "message"
        ] = f"Celery check failed (broker down?): {type(e).__name__}"
        log.error(
            "Health check failed (Celery)", error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`

    status_code = (
        status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=checks)
