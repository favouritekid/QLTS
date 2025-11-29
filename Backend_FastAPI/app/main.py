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
    applications,
    auth,
    leads,
    monitoring,
    notification_preferences,
    notification_rules,  # ✅ PHASE 2.2: Notification Rules CRUD
    notification_templates,  # ✅ PHASE 3.1: Notification Templates CRUD
    notifications,
    officer,
    organization,
    pipeline,
    profile,
    sessions,
    users
)

# ✅ PHASE 2 COMPLETE: Import split admin routers
# Includes all 5 specialized routers (70 endpoints total):
# - users.py (16 endpoints)
# - roles.py (23 endpoints)
# - organization.py (12 endpoints) - PHASE 2B
# - config.py (5 endpoints) - PHASE 2B
# - pipeline.py (14 endpoints) - PHASE 2C
from .routers.admin import router as admin_router

# ✅ V5: Import SIO, LUA loader, và Prometheus
from .socket_manager import load_rate_limit_script, sio, OriginLoggingMiddleware

# ✅ PHASE 1: Import centralized exception handler registration
from .middleware import register_exception_handlers

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

# ❗️ TEMPORARY DEBUG: Enable Socket.IO và Engine.IO logging để debug 403 errors
# TODO: Revert to INFO after fixing 403 issue
logging.getLogger("socketio").setLevel(logging.DEBUG)
logging.getLogger("engineio").setLevel(logging.DEBUG)

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

            # ✅ PHASE 2.2: Notification Rules (Admin-only) - Visual notification management
            await enforcer.add_policy("role:admin", "/api/notification-rules", "GET")
            await enforcer.add_policy("role:admin", "/api/notification-rules", "POST")
            await enforcer.add_policy("role:admin", "/api/notification-rules/{rule_id}", "GET")
            await enforcer.add_policy("role:admin", "/api/notification-rules/{rule_id}", "PUT")
            await enforcer.add_policy("role:admin", "/api/notification-rules/{rule_id}", "DELETE")
            await enforcer.add_policy("role:admin", "/api/notification-rules/{rule_id}/toggle", "PATCH")

            # ✅ PHASE 3.1: Notification Templates (Admin-only) - Reusable template management
            await enforcer.add_policy("role:admin", "/api/notification-templates", "GET")
            await enforcer.add_policy("role:admin", "/api/notification-templates", "POST")
            await enforcer.add_policy("role:admin", "/api/notification-templates/{template_id}", "GET")
            await enforcer.add_policy("role:admin", "/api/notification-templates/{template_id}", "PUT")
            await enforcer.add_policy("role:admin", "/api/notification-templates/{template_id}", "DELETE")

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
            await enforcer.add_policy("role:officer", "/api/program-offerings", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/{year}", "GET")
            await enforcer.add_policy("role:officer", "/api/offerings/{offering_id}/academic-info/current", "GET")
            await enforcer.add_policy("role:officer", "/api/leads/import", "POST")

            await enforcer.add_policy("role:manager", "/api/organization-units", "GET")
            await enforcer.add_policy("role:manager", "/api/organization-units/tree-with-aggregation", "GET")
            await enforcer.add_policy("role:manager", "/api/programs", "GET")
            await enforcer.add_policy("role:manager", "/api/programs/{program_id}/offerings", "GET")
            await enforcer.add_policy("role:manager", "/api/program-offerings", "GET")
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
_sio_app = socketio.ASGIApp(sio, app)

# ✅ DEBUG: Wrap with Origin logging middleware to debug CORS 403 errors
app_with_sockets = OriginLoggingMiddleware(_sio_app)


# ===============================================================
# === ✅ PHASE 1: EXCEPTION HANDLERS (Centralized) =============
# ===============================================================

# Register all custom exception handlers from middleware
# This replaces manual exception handler definitions with a centralized system
# See: app/middleware/exception_handlers.py for implementation
register_exception_handlers(app)
log.info("✅ Custom exception handlers registered")


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


# ===============================================================
# === HTTPS REDIRECT MIDDLEWARE (✅ SECURITY FIX: Force HTTPS)
# ===============================================================

if settings.APP_ENV == "production":
    from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
    app.add_middleware(HTTPSRedirectMiddleware)
    log.info("✅ HTTPS redirect enabled for production")


# ===============================================================
# === SECURITY HEADERS MIDDLEWARE (✅ Enhanced with CSP)
# ===============================================================

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add comprehensive security headers to all responses."""
    response = await call_next(request)

    # ✅ HSTS - Force HTTPS for 1 year
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )

    # ✅ Prevent MIME sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # ✅ Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"

    # ✅ XSS Protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # ✅ NEW: Content Security Policy
    # Restrictive CSP for API - adjust based on your frontend needs
    if settings.APP_ENV == "production":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "  # Allow inline styles for admin UI
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

    # ✅ Referrer Policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # ✅ Permissions Policy (restrict browser features)
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=()"
    )

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
app.include_router(notification_rules.router, prefix="/api", tags=["Notification Rules (Admin)"])  # ✅ PHASE 2.2: Admin-only notification rule management
app.include_router(notification_templates.router, prefix="/api", tags=["Notification Templates (Admin)"])  # ✅ PHASE 3.1: Admin-only template management
app.include_router(leads.router, prefix="/api/leads", tags=["Leads"])
app.include_router(applications.router, prefix="/api", tags=["Applications"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
app.include_router(
    organization.router, prefix="/api", tags=["Organization"]
)
app.include_router(officer.router, prefix="/api", tags=["Officer Dashboard"])
app.include_router(monitoring.router, prefix="/api", tags=["System Monitoring"])

# ===============================================================
# === ADMIN ROUTERS (PHASE 2 COMPLETE) =========================
# ===============================================================

# ✅ SPLIT ADMIN ROUTERS - All 5 specialized routers (70 endpoints)
# Old monolithic admin.py (2,740 lines) has been completely replaced
app.include_router(admin_router, prefix="/api")
# This provides:
#   PHASE 2A (39 endpoints):
#   - /api/admin/users/*       (16 endpoints - user management, sync, analytics)
#   - /api/admin/roles/*       (23 endpoints - policy/role management, Casbin)
#
#   PHASE 2B (17 endpoints):
#   - /api/admin/organization-units/* (4 endpoints)
#   - /api/admin/programs/*           (4 endpoints)
#   - /api/admin/offerings/*          (4 endpoints)
#   - /api/admin/assignment-config/*  (2 endpoints)
#   - /api/admin/skill-rules/*        (3 endpoints)
#
#   PHASE 2C (14 endpoints):
#   - /api/admin/pipeline-stages/*      (5 endpoints)
#   - /api/admin/consultation-statuses/* (5 endpoints)
#   - /api/admin/allowed-transitions/*  (3 endpoints)
#   - /api/admin/leads/*/revert-status  (1 endpoint)
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
