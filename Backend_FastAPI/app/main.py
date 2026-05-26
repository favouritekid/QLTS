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
from .middleware.admission_freeze import AdmissionFreezeMiddleware  # ✅ T0-2 cold cutover freeze
from .middleware.csrf import CSRFMiddleware  # ✅ CSRF Protection
from .utils.redis_lock import init_redis_client, close_redis_client
from .routers import (
    accounting,  # ✅ FINANCE MODULE: Accounting Period Management
    administrative,  # ✅ PHASE 4: Administrative Nodes (Province/District/Ward)
    admission_config,  # ✅ PHASE 3: Admission Config + Scoring API
    admission_paths,  # ✅ PHASE 1: Admission Configuration Console
    admin_v2_casbin,  # ✅ T0-5 cold cutover: admin-only Casbin reload endpoint
    admin_v2_admission_round,  # ✅ #184 Phase 2 v8.2 PR-2A v2: year-level rounds CRUD + bulk-create + extend
    admin_v2_path_subject_group,  # ✅ #184 Phase 2 v8.2 PR-2D: path-level subject group config + clone endpoint
    admin_priority_config,  # ✅ Q9 #07 PR3: priority KV/UT bonus configs per year + clone + seed TT 05/2021
    admin_vn_locality,  # ✅ Q9 #07 PR4: commune + high school CSV import + dropdown search
    vn_school,  # ✅ Q9 #07 Phase D.0b: public school search (candidate FE)
    admin_v2_system_config,  # ✅ #184 PR-1D / phase1_13: admin runtime config
    admin_backfill,  # ✅ #184 Phase 3 PR-3D-B BE-2: admin backfill exception queue (Q-P3-09)
    admissions,  # ✅ NEW: Admission Profile workflow
    admissions_magic_link,  # ✅ PR-CO-2-BE / PR-3E: multi-action magic-link consume (4 actions)
    admissions_v2,  # ✅ #184 Phase 3 PR-3C Sub-3.3: multi-NV choice-engine endpoints (publish-result T6)
    auth,
    collaborators,  # ✅ CTV SYSTEM: Collaborator management + CTV self-service
    commissions,  # ✅ CTV PHASE 2: Commission management
    config_data, # ✅ NEW: Dynamic Config Data (Categories, Import)
    document_groups,  # ✅ PHASE A.3: DocumentGroup CRUD
    fees,  # ✅ FINANCE MODULE: Fee Calculation & Management
    finance_dashboard,  # ✅ FINANCE MODULE: Dashboard Statistics
    installment_plans,  # ✅ FINANCE MODULE: Installment Plans
    invoices,  # ✅ FINANCE MODULE: Invoice Lifecycle
    kpi_config,  # ✅ PHASE 5: KPI Configuration Admin
    kpi_planning,  # ✅ PHASE A6: KPI Planning Engine
    kpi_setup,  # ✅ KPI Setup: Coverage Dashboard
    leads,
    meta,  # ✅ Public metadata (KPI catalog)
    monitoring,
    notification_consents,  # ✅ PHASE B7: Notification Consent management
    notification_delivery_ops,  # ✅ PHASE B8: Delivery ops admin API
    notification_preferences,
    notification_rules,  # ✅ PHASE 2.2: Notification Rules CRUD
    notification_templates,  # ✅ PHASE 3.1: Notification Templates CRUD
    notifications,
    officer,
    organization,
    payments,  # ✅ FINANCE MODULE: Payment Processing
    pipeline,
    profile,
    public_admissions,  # ✅ Public admissions portal API
    security,  # ✅ LOGIN SECURITY: Phase 5 - User response flow
    sessions,
    users,
    zalo_webhooks,  # ✅ PHASE C1: Zalo webhook receiver
    zalo_bot_link,  # ✅ v5 Step 19: staff Zalo Bot link API
    zalo_bot_webhooks,  # ✅ v5 Step 18: Zalo Bot webhook receiver
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

# === ✅ H12+M10: Sentry Error Tracking (auto-activates when SENTRY_DSN is set) ===
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,  # GDPR: don't send PII by default
        )
        print(f"INFO [main.py]: ✅ Sentry initialized (env={settings.APP_ENV}, sample_rate={settings.SENTRY_TRACES_SAMPLE_RATE})")
    except ImportError:
        print("WARNING [main.py]: SENTRY_DSN is set but sentry-sdk is not installed. Run: pip install sentry-sdk[fastapi]")
    except Exception as e:
        print(f"WARNING [main.py]: Failed to initialize Sentry: {e}")

# === ✅ H3: Log Sanitization - Redact sensitive fields from log output ===
_SENSITIVE_FIELDS = frozenset({
    "password", "token", "secret", "payload", "authorization",
    "csrf", "access_token", "refresh_token", "mfa_token",
    "api_key", "credit_card", "ssn",
})

def _sanitize_sensitive_data(logger, method_name, event_dict):
    """Structlog processor that redacts sensitive fields from log output."""
    for key in list(event_dict.keys()):
        if any(sensitive in key.lower() for sensitive in _SENSITIVE_FIELDS):
            event_dict[key] = "[REDACTED]"
    return event_dict

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
        _sanitize_sensitive_data,  # ✅ H3: Redact sensitive fields before rendering
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

# ✅ L2: Optional file logging with rotation (set LOG_FILE in .env to enable)
if settings.LOG_FILE:
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=settings.LOG_FILE_MAX_BYTES,     # Default: 10 MB
        backupCount=settings.LOG_FILE_BACKUP_COUNT,  # Default: 5 files
        encoding="utf-8",
    )
    file_handler.setLevel(settings.LOG_LEVEL.upper())
    root_logger.addHandler(file_handler)
    print(f"INFO [main.py]: ✅ File logging enabled: {settings.LOG_FILE} (max={settings.LOG_FILE_MAX_BYTES//1024//1024}MB, backups={settings.LOG_FILE_BACKUP_COUNT})")

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
        # ✅ FIX: Use absolute path to avoid working directory issues
        auth_model_path = Path(__file__).parent.parent / "auth_model.conf"
        log.info(f"Loading Casbin model from: {auth_model_path}")
        enforcer = casbin.AsyncEnforcer(str(auth_model_path), adapter)

        # B1 cold cutover gate: skip the initial load_policy() call when
        # RUN_CASBIN_LOAD_ON_STARTUP=false. Mirrors the two existing gates
        # in docker-entrypoint.sh (RUN_MIGRATIONS_ON_STARTUP +
        # RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP). Defensive default
        # (only the exact lowercase "false" skips; any other value runs
        # the load) preserves routine-deploy behavior. Use case:
        # cutover deploys the new 4-field auth_model.conf BEFORE the
        # manual backfill that sets `casbin_rule.v3='allow'` on the
        # 210 legacy rows; loading the enforcer against the un-backfilled
        # state would crash with `RuntimeError: invalid policy size`.
        # The cutover restart at T+3:15 unsets the flag and lifespan
        # re-runs load_policy() against the backfilled DB.
        casbin_load_flag = os.getenv("RUN_CASBIN_LOAD_ON_STARTUP", "true")
        if casbin_load_flag == "false":
            log.warning(
                "⏭️  Skipping enforcer.load_policy() — "
                "RUN_CASBIN_LOAD_ON_STARTUP=false (cold cutover). "
                "Casbin in-memory policy table is empty until a later "
                "restart with the flag unset / set to true."
            )
        else:
            await enforcer.load_policy()
            log.info("✅ Casbin AsyncEnforcer initialized and policies loaded.")
        fastapi_app.state.enforcer = enforcer

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
        # B1 cold-cutover safety: when the load was skipped above
        # (RUN_CASBIN_LOAD_ON_STARTUP=false), `enforcer.get_policy()`
        # legitimately returns []. Without this guard, the production
        # fail-fast below would always fire on the cutover deploy at
        # T+1:00 and crash-loop the backend container — instead of
        # ``uvicorn ready`` (RUNBOOK §7.2 line 332-333). The
        # auto-seed / fail-fast block runs only when load was
        # attempted; if the gate skipped, defer empty-policy decisions
        # to the next restart at T+3:15 when the flag is flipped back.
        if casbin_load_flag != "false" and not enforcer.get_policy():
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

                            # Convert to 4-tuples (subject, object, action, eft) for
                            # the batch operation. ``apply_template`` since B1 always
                            # populates ``eft`` (default "allow", explicit "deny" for
                            # accountant admission state-machine guards).
                            policies_tuples = [
                                (p["subject"], p["object"], p["action"], p["eft"])
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
                    # SEED ROLE INHERITANCE (g-policies) - Tree Hierarchy
                    # =========================================================================
                    # Tree Hierarchy (Separation of Duties):
                    #
                    #                    ┌─────────┐
                    #                    │  Admin  │
                    #                    └────┬────┘
                    #                         │
                    #                    ┌────┴─────┐
                    #                    │ Manager  │
                    #                    └────┬─────┘
                    #                         │
                    #     ┌──────────────┬────┴────┐
                    #     │              │         │
                    # ┌───┴────┐  ┌──────┴────┐ (other officer-derived roles)
                    # │Officer │  │Accountant │
                    # └───┬────┘  └──────┬────┘
                    #     │              │
                    #     └──────┬───────┘
                    #            │
                    #       ┌────┴────┐
                    #       │  User   │
                    #       └─────────┘
                    #
                    # FIX 2026-05-15: removed `g, admin → accountant` diamond edge.
                    # Reason: admin already has wildcard ALLOW `/*.*` so the redundant
                    # inheritance only causes admin to inherit accountant DENY entries
                    # (admin-rollback, claim, request-revision, waitlist-promote) →
                    # admin gets unintended 403s on those endpoints. Tree shape preserves
                    # separation-of-duties (admin ≠ accountant in audit trail) while
                    # eliminating the inherited-DENY bug.
                    #
                    # Benefits:
                    # - Manager: User/Lead management (admission workflow)
                    # - Accountant: Finance operations (payments, invoices)
                    # - Manager does NOT inherit Accountant (separation of duties)
                    # - Admin inherits from Manager only; accountant DENYs no longer leak
                    #
                    role_inheritance = [
                        ("g", "role:officer", "role:user"),       # Officer inherits from User
                        ("g", "role:accountant", "role:officer"), # Accountant inherits from Officer
                        ("g", "role:manager", "role:officer"),    # Manager inherits from Officer (NOT from Accountant!)
                        ("g", "role:admin", "role:manager"),      # Admin inherits from Manager
                    ]
                    
                    from sqlalchemy import text
                    
                    # Ensure tracking columns exist (may be missing on clean schema
                    # where casbin_rule was created by the adapter, not Alembic)
                    await db_session.execute(text("""
                        DO $$ BEGIN
                            ALTER TABLE casbin_rule
                            ADD COLUMN IF NOT EXISTS template_id VARCHAR(50),
                            ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP,
                            ADD COLUMN IF NOT EXISTS applied_by INTEGER;
                        EXCEPTION WHEN undefined_table THEN NULL;
                        END $$;
                    """))
                    await db_session.commit()

                    # Insert 'g' policies directly to ensure they exist
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
        # Extended 2026-05-26: include APP_ENV=test so CI nightly-regression
        # gets the same drift auto-correction as local dev. Without this, a
        # fresh CI DB only has casbin_rule rows seeded by alembic migrations
        # (which lag policy_templates.py); officer hit 403 on
        # /api/pipeline/all + /api/notifications/preferences even though the
        # template grants them, because the alembic seed predates those
        # entries. Production explicitly stays opt-out per safety branch
        # below (line 458-462) — manual POST /api/admin/roles/sync-all-from-
        # templates is the prod path.
        if settings.AUTO_SYNC_TEMPLATES and settings.APP_ENV in {"development", "test"}:
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
        elif settings.AUTO_SYNC_TEMPLATES:
            # APP_ENV is some non-canonical value (e.g., 'staging', 'qa'). Auto-sync
            # is gated to {"development", "test"} only (see line 437 above) so
            # nothing fires here — log INFO so ops can diagnose why drift remains
            # uncorrected in this env.
            log.info(
                "AUTO_SYNC_TEMPLATES enabled but APP_ENV=%s is outside the "
                "auto-sync allowlist {development, test}; skipping. Use the "
                "manual admin endpoint if drift correction is desired.",
                settings.APP_ENV,
            )

    except Exception as e:
        log.critical(
            "❌ FAILED TO INITIALIZE OR CONFIGURE CASBIN ENFORCER!",
            error=str(e),
            exc_info=True,
        )
        # ✅ FIX: Re-raise to prevent app from starting without authorization
        raise

    # (Giữ nguyên logic Rate Limiter)
    if settings.APP_ENV != "test":
        fastapi_app.state.limiter = limiter
        async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Quá nhiều yêu cầu. Vui lòng thử lại sau.",
                },
            )
            # Inject Retry-After header via slowapi limiter (accurate remaining time)
            response = request.app.state.limiter._inject_headers(
                response, request.state.view_rate_limit
            )
            return response

        fastapi_app.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)
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
    # ✅ SECURITY: Disable API docs in production to prevent information disclosure
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
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

# ===============================================================
# === MIDDLEWARE STACK (Order matters! Last added = outermost = runs first)
# ===
# === Request flow: CORS → HTTPS Redirect → CSRF → App
# === Response flow: App → CSRF → HTTPS Redirect → CORS
# ===
# === CORS must be outermost so error responses from inner middleware
# === (e.g., CSRF 403) always include CORS headers.
# ===============================================================

# --- Layer 3 (innermost): CSRF Protection ---
# Validates X-CSRF-Token header for state-changing requests (POST/PUT/DELETE/PATCH)
# Token is set as a readable cookie on login, frontend sends it in headers
if settings.APP_ENV != "test":  # Disabled in tests by default
    fastapi_app.add_middleware(CSRFMiddleware)
    log.info("✅ CSRF protection middleware enabled")

# --- Layer 2.5: Admission cold-cutover freeze (T0-2) ---
# Sits inside CORS so 503 responses still carry CORS headers; outside CSRF so
# a frozen request short-circuits before CSRF state machine runs. Reads
# settings.ADMISSION_FROZEN per request (Settings itself is module-level).
fastapi_app.add_middleware(AdmissionFreezeMiddleware)
log.info("✅ Admission freeze middleware registered (T0-2 cold cutover)")

# --- Layer 2: HTTPS Redirect ---
# Removed: Nginx handles HTTPS redirect (301) at the edge.
# HTTPSRedirectMiddleware caused 307 loops for internal Docker traffic
# (frontend SSR, healthchecks) which doesn't go through Nginx.

# --- Layer 1 (outermost): CORS - MUST be last added ---
# Ensures ALL responses (including middleware errors) have CORS headers
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Set-Cookie"],
)


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
    # Restrictive CSP for production, permissive for development
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
    else:
        # Development/test: permissive CSP that still prevents major attacks
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' http://localhost:* http://127.0.0.1:*; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: http://localhost:* http://127.0.0.1:*; "
            "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*; "
            "frame-ancestors 'none'"
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
fastapi_app.include_router(notification_consents.router, prefix="/api")  # ✅ PHASE B7: Consent management
fastapi_app.include_router(notification_delivery_ops.router, prefix="/api")  # ✅ PHASE B8: Delivery ops
fastapi_app.include_router(zalo_webhooks.router)  # ✅ PHASE C1: Zalo webhooks (no auth, HMAC-verified)
fastapi_app.include_router(zalo_bot_webhooks.router)  # ✅ v5 Step 18: Zalo Bot webhook (shared-secret header)
fastapi_app.include_router(zalo_bot_link.router)  # ✅ v5 Step 19: Staff Zalo Bot link API
fastapi_app.include_router(leads.router, prefix="/api/leads")
fastapi_app.include_router(collaborators.admin_router, prefix="/api")  # ✅ CTV: Admin/Manager CTV management
fastapi_app.include_router(collaborators.ctv_router, prefix="/api")  # ✅ CTV: Self-service endpoints
fastapi_app.include_router(collaborators.public_router, prefix="/api")  # ✅ CTV P2: Public self-registration (no auth)
fastapi_app.include_router(commissions.policy_router, prefix="/api")  # ✅ CTV P2: Commission policies (Admin)
fastapi_app.include_router(commissions.record_router, prefix="/api")  # ✅ CTV P2: Commission records (Admin)
fastapi_app.include_router(commissions.ctv_commission_router, prefix="/api")  # ✅ CTV P2: CTV commission view
fastapi_app.include_router(admissions.router, prefix="/api")  # ✅ Admission Profile workflow
fastapi_app.include_router(admissions_magic_link.router)  # ✅ PR-CO-2-BE / PR-3E: multi-action magic-link (router declares /api/v2/admissions/magic-link prefix)
fastapi_app.include_router(admissions_v2.router)  # ✅ #184 Phase 3 PR-3C: multi-NV choice-engine v2 (router declares /api/v2 prefix)
fastapi_app.include_router(admin_backfill.router)  # ✅ #184 Phase 3 PR-3D-B BE-2: admin backfill exception queue (router declares /api/v2/admin prefix)
fastapi_app.include_router(admission_config.router, prefix="/api")  # ✅ PHASE 3: Admission Config + Scoring
fastapi_app.include_router(admission_paths.router, prefix="/api")  # ✅ PHASE 1: Admission Configuration Console
fastapi_app.include_router(admin_v2_casbin.router)  # ✅ T0-5: POST /api/v2/admin/casbin/reload (router declares full prefix)
fastapi_app.include_router(admin_v2_system_config.router)  # ✅ #184 PR-1D: GET/PATCH /api/v2/admin/system-config (router declares full prefix)
fastapi_app.include_router(admin_v2_admission_round.router)  # ✅ #184 Phase 2 v8.2 PR-2A v2: year-level rounds (router declares full prefix)
fastapi_app.include_router(admin_v2_path_subject_group.router)  # ✅ #184 Phase 2 v8.2 PR-2D: path-level subject group config + clone
fastapi_app.include_router(admin_priority_config.router)  # ✅ Q9 #07 PR3: priority KV/UT configs (router declares full prefix)
fastapi_app.include_router(admin_vn_locality.admin_router)  # ✅ Q9 #07 PR4: admin commune CSV import
fastapi_app.include_router(vn_school.router)  # ✅ Q9 #07 Phase D.0b: public search (candidate FE dropdown)
fastapi_app.include_router(document_groups.router, prefix="/api")  # ✅ PHASE A.3: DocumentGroup CRUD
fastapi_app.include_router(config_data.router, prefix="/api") # ✅ NEW: Config Data
fastapi_app.include_router(administrative.router, prefix="/api")  # ✅ PHASE 4: Administrative address nodes
fastapi_app.include_router(pipeline.router, prefix="/api/pipeline")
fastapi_app.include_router(organization.router, prefix="/api")
fastapi_app.include_router(officer.router, prefix="/api")
fastapi_app.include_router(kpi_config.router)  # ✅ PHASE 5: KPI Configuration Admin
fastapi_app.include_router(kpi_planning.router)  # ✅ PHASE A6: KPI Planning Engine
fastapi_app.include_router(kpi_setup.router)  # ✅ KPI Setup: Coverage Dashboard
fastapi_app.include_router(meta.router)  # ✅ Public metadata (KPI catalog, no auth)
fastapi_app.include_router(public_admissions.router)  # ✅ Public admissions portal (no auth)
fastapi_app.include_router(security.router, prefix="/api")  # ✅ LOGIN SECURITY: Phase 5
fastapi_app.include_router(monitoring.router, prefix="/api")
# ✅ FINANCE MODULE: Phase 4 - API Layer
fastapi_app.include_router(fees.router, prefix="/api")
fastapi_app.include_router(invoices.router, prefix="/api")
fastapi_app.include_router(payments.router, prefix="/api")
fastapi_app.include_router(accounting.router, prefix="/api")
fastapi_app.include_router(finance_dashboard.router, prefix="/api")
fastapi_app.include_router(installment_plans.router, prefix="/api")

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
