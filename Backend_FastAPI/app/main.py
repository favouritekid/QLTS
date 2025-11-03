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
from .routers import admin, auth, leads, organization, pipeline, profile, users
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
# (Gỡ bỏ formatter cũ nếu bạn dùng processor của structlog)
root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(log_handler)
root_logger.setLevel(settings.LOG_LEVEL.upper())

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")] if settings.CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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