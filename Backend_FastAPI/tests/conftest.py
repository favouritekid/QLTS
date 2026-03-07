# tests/conftest.py
# -*- coding: utf-8 -*-
import asyncio
import io
import logging
import os
import sys
from typing import Any, Dict, List

try:
    import pandas as pd
except ImportError:
    # pandas not required for refactoring/unit tests
    pd = None

import pytest
import pytest_asyncio
import fakeredis.aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, text

# --- PATH SETUP ---
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# --- SET APP_ENV ---
print("\nINFO [conftest.py]: Setting os.environ['APP_ENV'] = 'test'")
os.environ["APP_ENV"] = "test"
app_env_check = os.getenv("APP_ENV")
print(f"INFO [conftest.py]: Verified os.getenv('APP_ENV') = {app_env_check}")
if app_env_check != "test":
    pytest.fail("Failed to set APP_ENV=test in os.environ early in conftest.py")

# --- LOAD .env.test WITH OVERRIDE ---
# In Docker, environment variables from docker-compose.override.yml (e.g. DATABASE_URL=qlts_dev)
# take precedence over Pydantic-settings env_file values. We need to force-load .env.test
# with override=True so that test DATABASE_URL (qlts_test) wins over Docker's DATABASE_URL.
from dotenv import load_dotenv
_env_test_path = os.path.join(project_root, ".env.test")
if os.path.exists(_env_test_path):
    load_dotenv(_env_test_path, override=True)
    print(f"INFO [conftest.py]: Loaded .env.test with override=True from {_env_test_path}")
    print(f"INFO [conftest.py]: DATABASE_URL after override = {os.getenv('DATABASE_URL', 'NOT SET')[:60]}...")
else:
    print(f"WARNING [conftest.py]: .env.test not found at {_env_test_path}")

# --- PATCH REDIS BEFORE APP IMPORT ---
print("INFO [conftest.py]: Patching Redis with FakeRedis before app import...")
import redis
import redis.asyncio
import fakeredis

# Create a shared FakeServer to enable LUA script support
_fake_server = fakeredis.FakeServer()
print(f"INFO [conftest.py]: Created shared FakeServer for LUA script support")

# Save originals
_original_from_url_async = redis.asyncio.from_url
_original_from_url_sync = redis.from_url

# Create patch functions
def _fake_redis_from_url_async(*args, **kwargs):
    print(f"INFO [conftest.py]: FakeRedis (async) intercepted from_url call")
    decode_responses = kwargs.get('decode_responses', True)
    return fakeredis.aioredis.FakeRedis(server=_fake_server, decode_responses=decode_responses)

def _fake_redis_from_url_sync(*args, **kwargs):
    print(f"INFO [conftest.py]: FakeRedis (sync) intercepted from_url call")
    decode_responses = kwargs.get('decode_responses', True)
    # Use shared server for LUA script support
    return fakeredis.FakeStrictRedis(server=_fake_server, decode_responses=decode_responses)

# Patch them globally
redis.asyncio.from_url = _fake_redis_from_url_async
redis.from_url = _fake_redis_from_url_sync
print("INFO [conftest.py]: Redis patched with FakeRedis successfully")

# --- IMPORT APP COMPONENTS ---
print("INFO [conftest.py]: Importing app components...")
try:
    from app.database import AsyncSessionLocal, engine
    # ✅ FIX: Import fastapi_app (not 'app' which is Socket.IO wrapper)
    from app.main import fastapi_app as app
    from app.models.base import Base as AppBase

    try:
        from casbin_async_sqlalchemy_adapter import Base as CasbinBase
        from casbin_async_sqlalchemy_adapter.adapter import CasbinRule
    except ImportError:
        print(
            "WARNING: Could not import CasbinBase or CasbinRule. Casbin setup might fail."
        )
        CasbinBase = None
        CasbinRule = None
    # <<< THÊM: Import models trực tiếp nếu helper dùng >>>
    from app import models
    from app.config import settings
    from app.security import (
        get_password_hash,  # get_password_hash được dùng trong helper
    )
except ImportError as e:
    print(f"ERROR [conftest.py]: Failed during app import: {e}")
    pytest.fail(f"ImportError during app import: {e}")
print("INFO [conftest.py]: App components imported successfully.")

# --- DISABLE MFA ENFORCEMENT IN TESTS ---
# Tests don't have MFA enabled for admin/manager fixtures by default.
# Individual tests can re-enable via monkeypatch if needed.
settings.MFA_ENFORCE_ROLES = []


# --- IMPORT CONSTANTS ---
try:
    # <<< CHỈNH SỬA: Import AuthURLs rõ ràng hơn >>>
    from .fixtures.constants import AuthURLs  # Giữ lại AuthURLs
    from .fixtures.constants import (
        SecurityConstants,
        TestOrgData,
        TestPipelineData,
        TestUsers,
    )
except ImportError:
    pytest.fail(
        "Could not import constants from tests.fixtures.constants. Please create the file."
    )

# --- LOGGING & SAFETY CHECK ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
log = logging.getLogger(__name__)

if settings.APP_ENV != "test":
    pytest.fail(
        f"CRITICAL: settings.APP_ENV is not 'test' (value: {settings.APP_ENV}). Aborting tests.",
        pytrace=False,
    )
if "test" not in settings.DATABASE_URL.lower():
    log.warning(
        f"WARNING: settings.DATABASE_URL ({settings.DATABASE_URL}) might not contain 'test'."
    )
print(
    f"INFO [conftest.py]: Safety check passed. settings.APP_ENV={settings.APP_ENV}. Using test database: {settings.DATABASE_URL[:30]}..."
)


def create_mock_lead_file(
    data: List[Dict[str, Any]], file_format: str = "csv", include_header: bool = True
) -> tuple[str, io.BytesIO, str]:
    """Tạo file CSV hoặc Excel giả lập trong memory."""
    df = pd.DataFrame(data)
    output = io.BytesIO()
    filename = f"test_leads.{file_format}"
    content_type = ""

    if file_format == "csv":
        df.to_csv(output, index=False, header=include_header, encoding="utf-8")
        content_type = "text/csv"
    elif file_format == "xlsx":
        df.to_excel(output, index=False, header=include_header, engine="openpyxl")
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        raise ValueError("Unsupported file format")

    output.seek(0)  # Đưa con trỏ về đầu file
    # Trả về tuple (filename, file_object, content_type) phù hợp với httpx files=
    return (filename, output, content_type)


# ===============================================================
# === HELPER FUNCTION (Tạo User + Role) ===
# ===============================================================


async def _create_user_and_role(
    user_data: dict, casbin_role: str, unit_id: int = None
):  # ✅ Thêm tham số unit_id
    """Creates a user in DB and assigns Casbin role."""
    user_info = {}
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=user_data["username"],
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                role=user_data["role"],
                status=user_data["status"],
                unit_id=unit_id,  # ✅ Gán unit_id
            )
            session.add(user)
            await session.flush()
            db_user_id = user.id
            if not db_user_id:
                raise Exception(
                    f"Failed to get auto-generated ID for user {user_data['username']}"
                )

            if CasbinRule:
                casbin_policy = insert(CasbinRule).values(
                    ptype="g", v0=f"user:{db_user_id}", v1=casbin_role
                )
                await session.execute(casbin_policy)
            else:
                log.warning(
                    f"CasbinRule not available, skipping role assignment for {user_data['username']}."
                )

            user_info = {
                "id": db_user_id,
                "username": user_data["username"],
                "email": user_data["email"],  # ✅ ADDED: Include email
                "password": user_data["password"],
            }
    # Reload Casbin policies sau khi thay đổi (nên làm ở đây HOẶC trong client fixture)
    if hasattr(app.state, "enforcer") and app.state.enforcer:
        try:
            await app.state.enforcer.load_policy()
            log.info(
                f"Casbin policies reloaded after creating user {user_data['username']}"
            )
        except Exception as e:
            log.error(
                f"Failed to reload Casbin policies after creating user {user_data['username']}: {e}"
            )
    return user_info


# ===============================================================
# === CORE FIXTURES (Event Loop, DB, Redis, Client) ===
# ===============================================================
@pytest.fixture(scope="function")
def app_instance():
    """Trả về instance app FastAPI đã import."""
    # 'app' đã được import ở đầu conftest.py
    return app


# Note: event_loop fixture is handled by pytest-asyncio with asyncio_mode=auto
# The asyncio_default_fixture_loop_scope=function setting in pytest.ini ensures
# function-scoped fixtures work correctly with async tests.


@pytest_asyncio.fixture(scope="function", autouse=True)
async def manage_engine():
    yield
    log.info("\n--- [FUNCTION TEARDOWN] Disposing test engine ---")
    import app.database as _db_mod
    await _db_mod.engine.dispose()
    log.info("--- [FUNCTION TEARDOWN] Test engine disposed ---")


def _verify_test_database_safety():
    """
    🚨 CRITICAL SAFETY CHECK 🚨

    Verify we're using a safe test database before allowing DROP operations.
    This prevents accidentally dropping production database tables.

    Safety criteria:
    1. APP_ENV must be "test"
    2. DATABASE_URL must meet ONE of these conditions:
       - Contains ":memory:" (SQLite in-memory)
       - Database name contains "test" (case-insensitive)
       - Database name ends with "_test"

    Production database indicators (BLOCKED):
    - Database names: production, prod, main, qlts_dev, qlts (without _test)
    """
    # Check 1: APP_ENV must be "test"
    current_env = settings.APP_ENV
    if current_env != "test":
        pytest.fail(
            f"🚨 SAFETY CHECK FAILED! 🚨\n"
            f"APP_ENV is '{current_env}', not 'test'.\n"
            f"Tests will NOT run to prevent production database deletion!\n"
            f"Set APP_ENV=test before running tests."
        )

    # Check 2: DATABASE_URL must be safe
    db_url = settings.DATABASE_URL
    db_url_lower = db_url.lower()

    # Safe patterns
    is_memory = ":memory:" in db_url_lower
    has_test_in_name = "test" in db_url_lower or "_test" in db_url_lower

    # Dangerous patterns (production database indicators)
    dangerous_patterns = [
        "/qlts_dev",        # Development database
        "/qlts_prod",       # Production database
        "/qlts_production", # Production database
        "/qlts/",           # Production database (without suffix)
        "/qlts ",           # Production database (space after)
        "/production",      # Generic production
        "/prod/",           # Generic production
        "/main/",           # Main database
    ]

    is_dangerous = any(pattern in db_url_lower for pattern in dangerous_patterns)

    # Final decision
    if is_dangerous and not has_test_in_name:
        pytest.fail(
            f"🚨 SAFETY CHECK FAILED! 🚨\n"
            f"DATABASE_URL appears to be a PRODUCTION database:\n"
            f"  {db_url}\n\n"
            f"Dangerous patterns detected: {[p for p in dangerous_patterns if p in db_url_lower]}\n\n"
            f"Tests will NOT run to prevent production database deletion!\n\n"
            f"For safe testing, use:\n"
            f"  - ':memory:' for SQLite in-memory\n"
            f"  - Database name containing 'test' (e.g., qlts_test, your_test_db_name)\n"
        )

    if not (is_memory or has_test_in_name):
        pytest.fail(
            f"🚨 SAFETY CHECK FAILED! 🚨\n"
            f"DATABASE_URL does not appear to be a test database:\n"
            f"  {db_url}\n\n"
            f"Tests will NOT run to prevent production database deletion!\n\n"
            f"For safe testing, use:\n"
            f"  - ':memory:' for SQLite in-memory\n"
            f"  - Database name containing 'test' (e.g., qlts_test, your_test_db_name)\n"
        )

    log.info(f"✅ Safety check passed: APP_ENV={current_env}, DB_URL={db_url[:60]}...")


# ===============================================================
# === SCHEMA MANAGEMENT: Create once, truncate per test ===
# ===============================================================
#
# Strategy:
#   1. First test in session: DROP SCHEMA CASCADE + CREATE all (clean slate)
#   2. Subsequent tests: TRUNCATE all tables (fast, no DDL, no asyncpg cache issues)
#
# Why not DROP/CREATE per test?
#   - asyncpg caches prepared statements keyed by SQL text. DDL operations
#     (CREATE/DROP TYPE) on different connections cause stale cache entries,
#     leading to "enum already exists" or "table does not exist" errors.
#   - TRUNCATE is DML, not DDL — it never touches pg_type or pg_class,
#     so asyncpg's cache stays valid.
# ===============================================================

_schema_initialized = False


async def _init_schema_once():
    """Create the full schema from scratch. Called once per pytest session."""
    from sqlalchemy.ext.asyncio import create_async_engine as _create_engine

    # Use a SEPARATE short-lived engine for schema DDL.
    # This avoids polluting the main engine's asyncpg connection cache
    # with DDL operations that would become stale after DROP/CREATE.
    setup_engine = _create_engine(
        settings.DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        connect_args={"command_timeout": 60},
    )

    try:
        # Step 1: Nuke everything via DROP SCHEMA CASCADE (clean slate).
        # Safe because this is a short-lived engine — no other code holds
        # connections from it. The main engine gets fresh connections after.
        async with setup_engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        log.info("[Schema Init] Step 1: DROP SCHEMA CASCADE complete")

        # Must dispose to clear asyncpg cache of the old schema
        await setup_engine.dispose()

        # Step 2: Recreate with a fresh engine (new connections, no stale cache)
        setup_engine = _create_engine(
            settings.DATABASE_URL,
            pool_size=2,
            max_overflow=0,
            connect_args={"command_timeout": 60},
        )
        async with setup_engine.begin() as conn:
            await conn.run_sync(AppBase.metadata.create_all)

            # Create sequences not tracked by SQLAlchemy metadata
            # (created via raw SQL in Alembic migrations)
            await conn.execute(text(
                "CREATE SEQUENCE IF NOT EXISTS collaborator_code_seq "
                "START WITH 1 INCREMENT BY 1"
            ))

            if CasbinBase:
                await conn.run_sync(CasbinBase.metadata.create_all)
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE casbin_rule
                        ADD COLUMN IF NOT EXISTS template_id VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP,
                        ADD COLUMN IF NOT EXISTS applied_by INTEGER;
                        CREATE INDEX IF NOT EXISTS ix_casbin_rule_template_id
                        ON casbin_rule(template_id);
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                """))

            tc = await conn.execute(text(
                "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"
            ))
            table_count = tc.scalar()
            log.info(f"[Schema Init] Step 2: Created {table_count} tables")
            if table_count == 0:
                raise RuntimeError(
                    "Schema init produced 0 tables! "
                    "Fix: DROP DATABASE qlts_test; CREATE DATABASE qlts_test;"
                )
    finally:
        await setup_engine.dispose()

    log.info("[Schema Init] Schema initialization complete")


async def _truncate_all_tables():
    """Truncate all data from all tables in a single statement.

    Uses a single TRUNCATE for all tables (much faster than one-by-one)
    and temporarily disables statement_timeout to avoid 30s cutoff.
    """
    async with engine.begin() as conn:
        # Disable statement_timeout for bulk truncate (default 30s is too short)
        await conn.execute(text("SET LOCAL statement_timeout = 0"))
        result = await conn.execute(text(
            "SELECT string_agg(quote_ident(tablename), ', ') "
            "FROM pg_tables WHERE schemaname = 'public'"
        ))
        tables = result.scalar()
        if tables:
            await conn.execute(
                text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
            )
            # Reset standalone sequences not owned by any table column
            # (RESTART IDENTITY only resets column-owned sequences)
            await conn.execute(text(
                "SELECT setval('collaborator_code_seq', 1, false)"
            ))


@pytest_asyncio.fixture(scope="function", autouse=False)
async def setup_test_database(manage_engine):
    global _schema_initialized

    # 🚨 CRITICAL: Verify safety before ANY database operations!
    _verify_test_database_safety()

    if not _schema_initialized:
        log.info("--- [FUNCTION SETUP] First test: initializing schema (DROP + CREATE) ---")
        # Dispose main engine so it gets fresh connections after schema change
        await engine.dispose()
        await _init_schema_once()
        # Dispose again so main engine connects to the new schema
        await engine.dispose()
        _schema_initialized = True
        log.info("--- [FUNCTION SETUP] Schema ready ---")
    else:
        log.info("--- [FUNCTION SETUP] Truncating all tables ---")
        await _truncate_all_tables()
        log.info("--- [FUNCTION SETUP] Truncate complete ---")

    yield

    # No teardown needed — next test's setup will truncate.
    # Final cleanup happens via manage_engine's engine.dispose().


@pytest_asyncio.fixture(scope="function")
async def test_redis_client():
    log.info("--- [FUNCTION SETUP] Creating FakeRedis client for testing ---")
    # IMPORTANT: Use the same _fake_server as the app so data is shared!
    # This allows tests to set data that the app can read
    client = fakeredis.aioredis.FakeRedis(server=_fake_server, decode_responses=True)
    try:
        await client.ping()
        log.info("--- [FUNCTION SETUP] FakeRedis client created successfully ---")
        yield client
    finally:
        log.info("--- [FUNCTION TEARDOWN] Closing FakeRedis connection ---")
        await client.aclose()


@pytest_asyncio.fixture(scope="function", autouse=False)
async def clear_redis_keys(
    test_redis_client,
):  # Bỏ dependency setup_test_database ở đây
    log.info("--- [FUNCTION SETUP] Flushing Test Redis DB ---")
    await test_redis_client.flushdb()
    log.info("--- [FUNCTION SETUP] Redis DB flushed ---")
    yield
    log.info("--- [FUNCTION TEARDOWN] Flushing Test Redis DB ---")
    await test_redis_client.flushdb()
    log.info("--- [FUNCTION TEARDOWN] Redis DB flushed ---")


@pytest_asyncio.fixture(scope="function")
async def client(setup_test_database) -> AsyncClient:  # Giữ dependency này
    log.info("--- [FUNCTION SETUP] Running app lifespan startup... ---")
    # ✅ FIX: Use lifespan directly instead of app.router.lifespan_context
    from app.main import lifespan
    async with lifespan(app):
        log.info(
            "--- [FUNCTION SETUP] Lifespan startup complete. Creating HTTP Client. ---"
        )
        # <<< THÊM RELOAD CASBIN SAU LIFESPAN >>>
        if hasattr(app.state, "enforcer") and app.state.enforcer:
            try:
                await app.state.enforcer.load_policy()
                log.info(
                    "--- [FIXTURE Client] Casbin policies reloaded after lifespan startup ---"
                )
            except Exception as e:
                log.error(
                    f"--- [FIXTURE Client] Failed to reload Casbin policies after lifespan: {e}"
                )
        # <<< KẾT THÚC THÊM RELOAD >>>
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    log.info(
        "--- [FUNCTION TEARDOWN] HTTP Client closed, Lifespan shutdown complete. ---"
    )


# ===============================================================
# === USER FIXTURES (Function Scope) ===
# ===============================================================


@pytest_asyncio.fixture(scope="function")
async def admin_user_in_db(setup_test_database):
    log.info("--- [FIXTURE] Creating admin user & role (Function Scope, Auto ID) ---")
    # Admin không cần unit_id, giữ nguyên
    user_info = await _create_user_and_role(TestUsers.ADMIN, "role:admin")
    log.info(f"--- [FIXTURE] Admin user created (ID: {user_info['id']}) ---")
    return user_info


@pytest_asyncio.fixture(scope="function")
async def manager_user_in_db(
    setup_test_database, seed_lead_dependencies: dict
):  # ✅ NHẬN fixture làm tham số
    log.info("--- [FIXTURE] Creating manager user & role (Function Scope, Auto ID) ---")

    # ✅ TRUY CẬP KẾT QUẢ fixture một cách chính xác
    unit_id = seed_lead_dependencies.get("unit_id")
    if not unit_id:
        # Fallback nếu fixture seed_lead_dependencies bị lỗi (dù không nên)
        unit_id = TestOrgData.UNIT_1["id"]

    user_info = await _create_user_and_role(
        TestUsers.MANAGER, "role:manager", unit_id=unit_id
    )
    log.info(
        f"--- [FIXTURE] Manager user created (ID: {user_info['id']}) in Unit {unit_id} ---"
    )
    return user_info


@pytest_asyncio.fixture(scope="function")
async def officer_user_in_db(
    setup_test_database, seed_lead_dependencies: dict
):  # ✅ NHẬN fixture làm tham số
    log.info("--- [FIXTURE] Creating officer user & role (Function Scope, Auto ID) ---")

    # ✅ TRUY CẬP KẾT QUẢ fixture một cách chính xác
    unit_id = seed_lead_dependencies.get("unit_id")
    if not unit_id:
        unit_id = TestOrgData.UNIT_1["id"]

    user_info = await _create_user_and_role(
        TestUsers.OFFICER, "role:officer", unit_id=unit_id
    )
    log.info(
        f"--- [FIXTURE] Officer user created (ID: {user_info['id']}) in Unit {unit_id} ---"
    )
    return user_info


@pytest_asyncio.fixture(scope="function")
async def regular_user_in_db(setup_test_database):
    log.info("--- [FIXTURE] Creating regular user & role (Function Scope, Auto ID) ---")
    user_info = await _create_user_and_role(TestUsers.REGULAR, "role:user")
    log.info(f"--- [FIXTURE] Regular user created (ID: {user_info['id']}) ---")
    return user_info


# Fixture user mặc định (có thể cần cho các test khác)
@pytest_asyncio.fixture(scope="function")
async def test_user_in_db(setup_test_database):
    log.info(
        "--- [FIXTURE] Creating default test user in DB (No Casbin Role by default) ---"
    )
    user_data = TestUsers.DEFAULT
    user_info = {}
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Tạo user với HASH THẬT đã biết, KHÔNG gán ID
                # ✅ FIX: Use models.User instead of bare User
                user = models.User(
                    username=user_data["username"],
                    email=user_data["email"],
                    password_hash=user_data["real_hash"],  # Dùng hash thật
                    role=user_data["role"],
                    status=user_data["status"],
                )
                session.add(user)
                await session.flush()  # Lấy ID tự động
                db_user_id = user.id
                if not db_user_id:
                    raise Exception("Failed to retrieve user ID after commit.")
                user_info = {
                    "id": db_user_id,
                    "username": user_data["username"],
                    "email": user_data["email"],
                    "password": user_data["password"],  # Trả về password gốc
                }
        log.info(f"--- [FIXTURE] Default test user created (ID: {user_info['id']}) ---")
        return user_info
    except Exception as e:
        log.error(
            f"--- [FIXTURE] Failed to create default test user: {e}", exc_info=True
        )
        pytest.fail(f"Fixture failed: {e}")


# ===============================================================
# === TOKEN FIXTURES (Function Scope) ===
# ===============================================================


async def _get_token_headers(client: AsyncClient, user_info: dict) -> dict:
    """
    Helper to login and get auth headers.

    ✅ FIX-5: Auth now uses httpOnly cookies. The httpx AsyncClient automatically
    manages cookies, so we don't need to manually pass Authorization headers.
    However, for backward compatibility with tests that use headers parameter,
    we extract the token from the cookie and return it as an Authorization header.
    """
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post(
        AuthURLs.LOGIN, data=login_data
    )
    if res.status_code != 200:
        pytest.fail(
            f"{user_info['username']} login failed: Status {res.status_code} - {res.text}"
        )

    # ✅ FIX: Extract access_token from cookie (not JSON response)
    access_token = res.cookies.get("access_token")
    if not access_token:
        pytest.fail(
            f"{user_info['username']} login succeeded but access_token cookie not found"
        )

    # Return as Authorization header for backward compatibility
    # (Backend supports both cookie and header auth)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture(scope="function")
async def admin_token_headers(client: AsyncClient, admin_user_in_db: dict) -> dict:
    log.info("--- [FIXTURE] Getting admin token ---")
    headers = await _get_token_headers(client, admin_user_in_db)
    log.info("--- [FIXTURE] Admin token obtained ---")
    return headers


@pytest_asyncio.fixture(scope="function")
async def manager_token_headers(client: AsyncClient, manager_user_in_db: dict) -> dict:
    log.info("--- [FIXTURE] Getting manager token ---")
    headers = await _get_token_headers(client, manager_user_in_db)
    log.info("--- [FIXTURE] Manager token obtained ---")
    return headers


@pytest_asyncio.fixture(scope="function")
async def officer_token_headers(client: AsyncClient, officer_user_in_db: dict) -> dict:
    log.info("--- [FIXTURE] Getting officer token ---")
    headers = await _get_token_headers(client, officer_user_in_db)
    log.info("--- [FIXTURE] Officer token obtained ---")
    return headers


@pytest_asyncio.fixture(scope="function")
async def regular_user_token_headers(
    client: AsyncClient, regular_user_in_db: dict
) -> dict:
    log.info("--- [FIXTURE] Getting regular user token ---")
    headers = await _get_token_headers(
        client, regular_user_in_db
    )  # <<< HOÀN THIỆN DÒNG NÀY
    log.info("--- [FIXTURE] Regular user token obtained ---")
    return headers


@pytest_asyncio.fixture(scope="function")
async def seed_lead_dependencies(setup_test_database):
    """
    Tạo Unit, Major, Stage, và các Status mặc định cần thiết cho Lead CRUD.
    Fixture này giờ nằm trong conftest.py để dễ dàng được pytest tìm thấy.
    """
    unit_data = TestOrgData.UNIT_1
    major_data = TestOrgData.MAJOR_1
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
    stage_a_id = "STAGE_A"
    stage_data = {"id": stage_a_id, "name": "Initial Stage", "order": 10}
    initial_status_data = {
        "id": initial_status_id,
        "name": "New Lead (Default)",
        "color_code": "#0000FF",
        "stage_id": stage_a_id,
    }
    # Lấy data gốc từ constants và ghi đè stage_id
    status_a1_data = TestPipelineData.STATUS_A1.copy()  # Tạo bản sao để sửa đổi
    status_a1_data["stage_id"] = stage_a_id

    lost_status_id = settings.DEFAULT_LOST_LEAD_STATUS_ID
    lost_stage_id = "STAGE_LOST"
    lost_stage_data = {"id": lost_stage_id, "name": "Lost Stage", "order": 999}
    lost_status_data = {
        "id": lost_status_id,
        "name": "Lost Status",
        "color_code": "#FF0000",
        "stage_id": lost_stage_id,
    }

    log.info("--- [FIXTURE conftest.py] Seeding lead dependencies ---")  # Cập nhật log
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit1 = models.OrganizationUnit(**unit_data)
            # ✅ FIX: Use MajorProgram instead of removed Major model
            major1 = models.MajorProgram(**major_data)
            stage_a = models.PipelineStage(**stage_data)
            stage_lost = models.PipelineStage(**lost_stage_data)
            status_tthv000 = models.ConsultationStatus(**initial_status_data)
            status_a1 = models.ConsultationStatus(**status_a1_data)
            status_lost = models.ConsultationStatus(**lost_status_data)
            session.add_all(
                [
                    unit1,
                    major1,
                    stage_a,
                    stage_lost,
                    status_tthv000,
                    status_a1,
                    status_lost,
                ]
            )
            await session.flush()

            # Admission pipeline stages + statuses (required by admission events)
            admission_stages = [
                models.PipelineStage(id="stg01", name="Moi", order=1001),
                models.PipelineStage(id="stg02", name="Dang tu van", order=1002),
                models.PipelineStage(id="stg03", name="Da nop ho so", order=1003),
                models.PipelineStage(id="stg04", name="Cho nhap hoc", order=1004),
                models.PipelineStage(id="stg05", name="Da nop hoc phi", order=1005),
                models.PipelineStage(id="stg06", name="Da nhap hoc", order=1006),
                models.PipelineStage(id="stg07", name="Khong di hoc", order=1007),
            ]
            session.add_all(admission_stages)
            await session.flush()

            admission_statuses = [
                models.ConsultationStatus(id="sts00", name="Chua lien he", color_code="#999999", stage_id="stg01"),
                models.ConsultationStatus(id="sts05", name="Hen lien he lai", color_code="#FFA500", stage_id="stg02"),
                models.ConsultationStatus(id="sts06", name="Dong y tu van", color_code="#00FF00", stage_id="stg02"),
                models.ConsultationStatus(id="sts07", name="Da nop ho so", color_code="#0088FF", stage_id="stg03"),
                models.ConsultationStatus(id="sts09", name="Du dieu kien nhap hoc", color_code="#00CC00", stage_id="stg04"),
                models.ConsultationStatus(id="sts10", name="Da nop hoc phi", color_code="#008800", stage_id="stg05"),
                models.ConsultationStatus(id="sts11", name="Da nhap hoc", color_code="#006600", stage_id="stg06"),
                models.ConsultationStatus(id="sts12", name="Khong di hoc", color_code="#CC0000", stage_id="stg07"),
                models.ConsultationStatus(id="sts13", name="Dang xu ly", color_code="#FFCC00", stage_id="stg03"),
                models.ConsultationStatus(id="sts14", name="Xac nhan nhap hoc", color_code="#009900", stage_id="stg05"),
                models.ConsultationStatus(id="sts16", name="Ho so khong dat", color_code="#FF0000", stage_id="stg04"),
                models.ConsultationStatus(id="sts17", name="Yeu cau bo sung ho so", color_code="#FF8800", stage_id="stg03"),
                models.ConsultationStatus(id="sts18", name="Da hoan hoc phi", color_code="#008888", stage_id="stg05"),
            ]
            session.add_all(admission_statuses)
    log.info("--- [FIXTURE conftest.py] Lead dependencies seeded ---")
    return {
        "unit_id": unit_data["id"],
        "major_program_id": TestOrgData.MAJOR_1["id"],  # ✅ FIX: Renamed from major_id
        "initial_status_id": initial_status_id,
        "status_a1_id": status_a1_data["id"],
        "stage_id": stage_a_id,
    }
