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
from .database import AsyncSessionLocal  # For auto-sync templates
from .core.rate_limits import limiter  # ✅ MIGRATED: Use new centralized rate limits module
from .utils.redis_lock import init_redis_client, close_redis_client
from .routers import (
    administrative,  # ✅ PHASE 4: Administrative Nodes (Province/District/Ward)
    admission_config,  # ✅ PHASE 3: Admission Config + Scoring API
    admission_paths,  # ✅ PHASE 1: Admission Configuration Console
    admissions,  # ✅ NEW: Admission Profile workflow (replacement for applications)
    applications,
    auth,
    config_data, # ✅ NEW: Dynamic Config Data (Categories, Import)
    document_groups,  # ✅ PHASE A.3: DocumentGroup CRUD
    kpi_config,  # ✅ PHASE 5: KPI Configuration Admin
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
    security,  # ✅ LOGIN SECURITY: Phase 5 - User response flow
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
from .socket_manager import load_rate_limit_script, sio

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

# Tắt log verbose của Socket.IO và Engine.IO (chỉ hiển thị WARNING trở lên)
logging.getLogger("socketio").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)

# Tắt log DEBUG của thư viện user-agents
logging.getLogger("user_agents").setLevel(logging.INFO)

# Tắt log verbose của bcrypt và passlib (chỉ hiển thị WARNING)
logging.getLogger("passlib").setLevel(logging.WARNING)
logging.getLogger("bcrypt").setLevel(logging.WARNING)

# Tắt log verbose của multipart form parser (chỉ hiển thị WARNING)
logging.getLogger("multipart").setLevel(logging.WARNING)
logging.getLogger("python_multipart").setLevel(logging.WARNING)

# Tắt log verbose của Casbin (chỉ hiển thị WARNING)
logging.getLogger("casbin").setLevel(logging.WARNING)

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
        fastapi_app.state.enforcer = enforcer
        log.info("✅ Casbin AsyncEnforcer initialized and policies loaded.")

        # =========================================================================
        # POLICY INITIALIZATION (Phase 4 Fix)
        # Reference: AUTHORIZATION_DECISIONS.md Decision 14
        # =========================================================================
        #
        # ❌ DEPRECATED: Hardcoded fallback policies have been REMOVED
        # Policies are now SINGLE SOURCE OF TRUTH from:
        #   1. policy_templates.py (definition)
        #   2. Alembic migrations (seeding)
        #   3. casbin_rule table (runtime)
        #
        # If no policies exist:
        #   - PRODUCTION: Fail-fast (don't start with broken auth)
        #   - DEV/TEST: Add admin wildcard only (minimal bootstrap)
        #
        if not enforcer.get_policy():
            if settings.APP_ENV == "production":
                log.critical(
                    "🚨 CRITICAL: No Casbin policies found in production! "
                    "This means migrations haven't been run. "
                    "Run: alembic upgrade head"
                )
                raise RuntimeError(
                    "Casbin policies not initialized. Run migrations: alembic upgrade head"
                )
            else:
                # DEV/TEST: Auto-seed from policy_templates.py (Single Source of Truth)
                from app.casbin_config.policy_templates import SYSTEM_ROLES, apply_template
                from app.services.casbin_service import CasbinPolicyService
                
                log.warning(
                    "⚠️ No policies found. Auto-seeding from policy_templates.py..."
                )
                
                # Create CasbinPolicyService for proper tracking column updates
                async with AsyncSessionLocal() as db_session:
                    casbin_service = CasbinPolicyService(db_session, enforcer)
                    
                    total_policies_added = 0
                    for role_config in SYSTEM_ROLES:
                        template_id = role_config.get("template_id")
                        role_name = role_config["name"]
                        
                        if template_id:
                            template_policies = apply_template(template_id, role_name)
                            
                            # Convert to tuples for batch operation
                            policies_tuples = [
                                (p["subject"], p["object"], p["action"])
                                for p in template_policies
                            ]
                            
                            # Use add_policies_batch to properly fill tracking columns
                            batch_result = await casbin_service.add_policies_batch(
                                policies=policies_tuples,
                                validate=False,  # Skip validation for bootstrap
                                template_id=template_id,
                                applied_by=None  # System seed - no user
                            )
                            
                            total_policies_added += batch_result["added"]
                            log.info(
                                f"  ✓ Seeded {role_name} with {batch_result['added']} policies from template '{template_id}'"
                            )
                    
                    log.info(
                        f"✅ Bootstrap complete: Seeded {len(SYSTEM_ROLES)} system roles "
                        f"with {total_policies_added} total policies from policy_templates.py"
                    )

                    # =========================================================================
                    # FIX: SEED ROLE INHERITANCE (g-policies) - Missing in previous versions
                    # =========================================================================
                    # Standard hierarchy: User <- Officer <- Manager <- Admin
                    role_inheritance = [
                        ("g", "role:officer", "role:user"),    # Officer inherits from User
                        ("g", "role:manager", "role:officer"), # Manager inherits from Officer
                        ("g", "role:admin", "role:manager"),   # Admin inherits from Manager
                    ]
                    
                    from sqlalchemy import text
                    
                    # Insert 'g' policies directly to ensure they exist
                    # We mark them with template_id='_system_inheritance' to distinguish from legacy
                    for ptype, child, parent in role_inheritance:
                        await db_session.execute(text("""
                            INSERT INTO casbin_rule (ptype, v0, v1, template_id, applied_at)
                            SELECT CAST(:ptype AS VARCHAR), CAST(:child AS VARCHAR), CAST(:parent AS VARCHAR), '_system_inheritance', NOW()
                            WHERE NOT EXISTS (
                                SELECT 1 FROM casbin_rule 
                                WHERE ptype = CAST(:ptype AS VARCHAR) AND v0 = CAST(:child AS VARCHAR) AND v1 = CAST(:parent AS VARCHAR)
                            )
                        """), {"ptype": ptype, "child": child, "parent": parent})
                        
                    log.info(f"  ✓ Seeded {len(role_inheritance)} role inheritance rules")


                    # Commit tracking column updates to DB
                    # NOTE: Casbin adapter auto-commits policies, but tracking columns
                    # are updated via db_session which needs explicit commit
                    await db_session.commit()
                    log.info("✅ Tracking columns (template_id, applied_at, applied_by) persisted to database")

        # =========================================================================
        # AUTO-SYNC TEMPLATES (Phase 5: Drift Detection & Auto-Sync)
        # Reference: AUTHORIZATION_DECISIONS.md Decision 14
        # =========================================================================
        # After policies are loaded, check for drift from templates
        # DEV mode with AUTO_SYNC_TEMPLATES=True: auto-sync to fix drift
        # Otherwise: just log warnings for manual review
        #
        if settings.AUTO_SYNC_TEMPLATES and settings.APP_ENV == "development":
            from app.services.casbin_service import CasbinPolicyService
            
            # Need a DB session for the service
            async with AsyncSessionLocal() as db_session:
                casbin_service = CasbinPolicyService(db_session, enforcer)
                
                drift_result = await casbin_service.detect_all_drift()
                roles_with_drift = drift_result["summary"]["roles_with_drift"]
                
                if roles_with_drift > 0:
                    log.warning(
                        f"⚠️ Drift detected in {roles_with_drift} roles. "
                        f"AUTO_SYNC_TEMPLATES is enabled, syncing now..."
                    )
                    
                    # Auto-sync in development mode
                    sync_result = await casbin_service.sync_all_roles_from_templates(dry_run=False)
                    
                    # Reload policies after sync
                    await enforcer.load_policy()
                    
                    log.info(
                        f"✅ Auto-sync complete: {sync_result['hint']}"
                    )
                else:
                    log.info("✅ No drift detected - all roles match their templates")
        elif settings.AUTO_SYNC_TEMPLATES and settings.APP_ENV == "production":
            log.warning(
                "⚠️ AUTO_SYNC_TEMPLATES is enabled but ignored in production. "
                "Use POST /api/admin/roles/sync-all-from-templates for manual sync."
            )

    except Exception as e:
        log.critical(
            "❌ FAILED TO INITIALIZE OR CONFIGURE CASBIN ENFORCER!",
            error=str(e),
            exc_info=True,
        )

    # (Giữ nguyên logic Rate Limiter)
    if settings.APP_ENV != "test":
        fastapi_app.state.limiter = limiter
        fastapi_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        log.info("SlowAPI rate limiter INITIALIZED for non-test environment.")
    else:
        log.info("APP_ENV is 'test', skipping SlowAPI rate limiter setup.")

    # --- Kiểm tra Redis ---
    try:
        pong = await safe_redis_ping()
        log.info("✅ Redis connection successful", response=pong)

        # ✅ CẢI TIẾN: Vấn đề #1 - Tải LUA script khi khởi động
        await load_rate_limit_script()

        # ✅ Initialize Redis lock client for distributed locking
        init_redis_client()
        log.info("✅ Redis lock client initialized for student_code generation")

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

    # Close Redis lock client
    try:
        await close_redis_client()
        log.info("✅ Redis lock client connection closed.")
    except Exception as e:
        log.error(
            "Error closing Redis lock client connection during shutdown.", error=str(e)
        )

    # Close main Redis client
    try:
        await main_redis_client.aclose()
        log.info("✅ Main Redis client connection closed.")
    except Exception as e:
        log.error(
            "Error closing main Redis client connection during shutdown.", error=str(e)
        )


# === KHỞI TẠO APP ===
# NOTE: This creates the FastAPI app, but it will be wrapped with Socket.IO at the END of this file
# Do NOT use 'app' directly with uvicorn - it will be reassigned to the wrapped version
fastapi_app = FastAPI(
    title="QLTS Project API with FastAPI",
    description="API for managing leads, users, and system configurations.",
    version="1.0.0",
    lifespan=lifespan,
)


# ===============================================================
# === ✅ PHASE 1: EXCEPTION HANDLERS (Centralized) =============
# ===============================================================

# Register all custom exception handlers from middleware
# This replaces manual exception handler definitions with a centralized system
# See: app/middleware/exception_handlers.py for implementation
register_exception_handlers(fastapi_app)
log.info("✅ Custom exception handlers registered")


# ===============================================================
# === MIDDLEWARES =============================================
# ===============================================================


@fastapi_app.middleware("http")
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

fastapi_app.add_middleware(
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
    fastapi_app.add_middleware(HTTPSRedirectMiddleware)
    log.info("✅ HTTPS redirect enabled for production")


# ===============================================================
# === SECURITY HEADERS MIDDLEWARE (✅ Enhanced with CSP)
# ===============================================================

@fastapi_app.middleware("http")
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
# NOTE: Tags are defined in each router file, not here (to avoid duplicates in Swagger)

fastapi_app.include_router(auth.router, prefix="/api/auth")
fastapi_app.include_router(profile.router, prefix="/api/profile")
fastapi_app.include_router(users.router, prefix="/api/users")
fastapi_app.include_router(sessions.router, prefix="/api")
fastapi_app.include_router(notifications.router, prefix="/api/notifications")
fastapi_app.include_router(notification_preferences.router, prefix="/api/notifications")
fastapi_app.include_router(notification_rules.router, prefix="/api")  # ✅ PHASE 2.2: Admin-only notification rule management
fastapi_app.include_router(notification_templates.router, prefix="/api")  # ✅ PHASE 3.1: Admin-only template management
fastapi_app.include_router(leads.router, prefix="/api/leads")
fastapi_app.include_router(applications.router, prefix="/api")
fastapi_app.include_router(admissions.router, prefix="/api")  # ✅ NEW: Admission Profile workflow
fastapi_app.include_router(admission_config.router, prefix="/api")  # ✅ PHASE 3: Admission Config + Scoring
fastapi_app.include_router(admission_paths.router, prefix="/api")  # ✅ PHASE 1: Admission Configuration Console
fastapi_app.include_router(document_groups.router, prefix="/api")  # ✅ PHASE A.3: DocumentGroup CRUD
fastapi_app.include_router(config_data.router, prefix="/api") # ✅ NEW: Config Data
fastapi_app.include_router(administrative.router, prefix="/api")  # ✅ PHASE 4: Administrative address nodes
fastapi_app.include_router(pipeline.router, prefix="/api/pipeline")
fastapi_app.include_router(organization.router, prefix="/api")
fastapi_app.include_router(officer.router, prefix="/api")
fastapi_app.include_router(kpi_config.router)  # ✅ PHASE 5: KPI Configuration Admin
fastapi_app.include_router(security.router, prefix="/api")  # ✅ LOGIN SECURITY: Phase 5
fastapi_app.include_router(monitoring.router, prefix="/api")

# ===============================================================
# === ADMIN ROUTERS (PHASE 2 COMPLETE) =========================
# ===============================================================

# ✅ SPLIT ADMIN ROUTERS - All 5 specialized routers (70 endpoints)
# Old monolithic admin.py (2,740 lines) has been completely replaced
fastapi_app.include_router(admin_router, prefix="/api")
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
    fastapi_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    log.info(f"✅ Static files mounted at /static from {STATIC_DIR}")
else:
    log.warning(f"⚠️ Static directory not found at {STATIC_DIR}")

# Mount uploads directory to serve uploaded documents (admissions, etc.)
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
if UPLOADS_DIR.exists():
    fastapi_app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
    log.info(f"✅ Uploads files mounted at /uploads from {UPLOADS_DIR}")
else:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    fastapi_app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
    log.info(f"✅ Uploads directory created and mounted at /uploads from {UPLOADS_DIR}")


# === ✅ CẢI TIẾN: Vấn đề #4 - Thêm Metrics Endpoint ===
@fastapi_app.get("/metrics", tags=["Utilities"])
async def metrics():
    """Endpoint cho Prometheus cào (scrape) metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ===============================================================
# === HEALTH CHECKS (Đã xóa `await` khỏi log) ================
# ===============================================================


@fastapi_app.get("/health", tags=["Utilities"])
async def health_check():
    """Kiểm tra API cơ bản."""
    log.debug("Health check endpoint was reached.")  # ✅ SỬA LỖI: Xóa `await`
    return {"status": "ok", "detail": "Server is healthy and running!"}


@fastapi_app.get("/health/detailed", tags=["Utilities"])
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


# ===============================================================
# === ✅ FINAL STEP: WRAP FASTAPI APP WITH SOCKET.IO ===========
# ===============================================================

# IMPORTANT: This MUST be at the END of the file, after all routers and middlewares are registered
# The FastAPI app is wrapped inside Socket.IO ASGI application
# Uvicorn will load 'app', which points to the Socket.IO wrapped application

# Wrap FastAPI inside Socket.IO and export as 'app' for uvicorn
# This ensures 'uvicorn app.main:app' loads the correct ASGI application
app = socketio.ASGIApp(sio, fastapi_app)
