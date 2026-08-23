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

# --- PATCH REDIS BEFORE APP IMPORT (Track T: delegated to fixtures/redis.py) ---
from tests.fixtures.redis import patch_redis, get_fake_server
patch_redis()
_fake_server = get_fake_server()
print("INFO [conftest.py]: Redis patched via fixtures/redis.py")

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
# Pepper cho selector của backup code v2. Đường backup code FAIL CLOSED khi
# thiếu (mfa_service._get_backup_pepper), nên bộ test phải có một giá trị —
# giống cách MFA_ENCRYPTION_KEY được đặt cho từng module MFA. Giá trị này chỉ
# dùng trong test; production bắt buộc set thật và config.py chặn ở startup.
settings.MFA_BACKUP_CODE_PEPPER = "test-only-backup-code-pepper-do-not-reuse"


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
):
    """Track T: Delegated to fixtures/users.py."""
    from tests.fixtures.users import create_user_with_role
    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data=user_data,
        casbin_role=casbin_role,
        unit_id=unit_id,
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=app,
    )


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
    """Track T: Delegated to fixtures/database.py."""
    from tests.fixtures.database import verify_test_database_safety
    verify_test_database_safety(settings, pytest.fail)


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
    """Track T: Delegated to fixtures/database.py."""
    from tests.fixtures.database import init_schema_once
    await init_schema_once(settings, AppBase, CasbinBase)


async def _truncate_all_tables():
    """Track T: Delegated to fixtures/database.py."""
    from tests.fixtures.database import truncate_all_tables
    await truncate_all_tables(settings, engine)


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
async def seed_other_unit(setup_test_database):
    """Create a SECOND organization unit for cross-unit IDOR scenarios.

    Distinct from ``seed_lead_dependencies['unit_id']`` so a fixture
    user attached here truly sits outside the seeded admission/lead
    tree. ID is picked above the auto-increment range
    (``TestOrgData.UNIT_2 = 9001``) to avoid collision.

    Idempotent: returns the existing row if a previous test already
    inserted UNIT_2 in the same DB session.
    """
    from app import models
    log.info(
        f"--- [FIXTURE] Ensuring second unit (id={TestOrgData.UNIT_2['id']}) ---"
    )
    # Idempotent insert in a single transaction frame: open ``begin()``,
    # check existence, insert if missing. ``session.get(...)`` opens an
    # implicit transaction on its own — calling ``session.begin()``
    # afterwards triggers SQLAlchemy's "transaction already begun"
    # error, so we wrap the whole get-then-insert under one explicit
    # frame.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = await session.get(
                models.OrganizationUnit, TestOrgData.UNIT_2["id"]
            )
            if existing is None:
                unit = models.OrganizationUnit(
                    id=TestOrgData.UNIT_2["id"],
                    name=TestOrgData.UNIT_2["name"],
                    type=TestOrgData.UNIT_2["type"],
                )
                session.add(unit)
    return {"unit_id": TestOrgData.UNIT_2["id"]}


@pytest_asyncio.fixture(scope="function")
async def manager_other_unit_user_in_db(
    setup_test_database,
    seed_other_unit: dict,
):
    """Manager user in a DIFFERENT unit from the default
    ``manager_user_in_db`` fixture.

    Use for cross-unit IDOR tests — pair with
    ``seed_lead_dependencies`` (which seeds the default unit + its
    profiles) and exercise the contract that a manager outside the
    profile's unit gets 404 on ``GET /admissions/{id}``,
    ``available_actions`` lists no `assign_officer`, etc.

    Inline equivalents of this pattern existed in
    ``test_commission_api.py::manager_api_unit2`` and
    ``test_collaborator_api.py::collab_in_unit2`` — lifted to conftest
    so admission tests + future scope can DI rather than re-seed.

    Memory tracker: ``project_admission_audit_followups`` item #5.
    """
    log.info(
        "--- [FIXTURE] Creating manager user in OTHER unit "
        f"({seed_other_unit['unit_id']}) ---"
    )
    user_info = await _create_user_and_role(
        TestUsers.MANAGER_OTHER_UNIT,
        "role:manager",
        unit_id=seed_other_unit["unit_id"],
    )
    log.info(
        f"--- [FIXTURE] Manager-other-unit created (ID: {user_info['id']}) "
        f"in Unit {seed_other_unit['unit_id']} ---"
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
    """Track T: Delegated to fixtures/users.py."""
    from tests.fixtures.users import get_auth_headers
    return await get_auth_headers(client, user_info, AuthURLs.LOGIN)


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
    from tests._lead_status_test_ids import (
        INITIAL_LEAD_STATUS_ID,
        LOST_LEAD_STATUS_ID,
    )
    unit_data = TestOrgData.UNIT_1
    major_data = TestOrgData.MAJOR_1
    initial_status_id = INITIAL_LEAD_STATUS_ID
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

    lost_status_id = LOST_LEAD_STATUS_ID
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
                models.PipelineStage(id="stg01", name="Chua tu van", order=1001),
                models.PipelineStage(id="stg02", name="Dang tu van", order=1002),
                models.PipelineStage(id="stg03", name="Da nop ho so", order=1003),
                models.PipelineStage(id="stg04", name="Ket qua ho so", order=1004),
                models.PipelineStage(id="stg05", name="Xu ly hoc phi", order=1005),
                models.PipelineStage(id="stg06", name="Da nhap hoc", order=1006, is_final_stage=True),
                models.PipelineStage(id="stg07", name="Khong di hoc", order=1007, is_final_stage=True),
            ]
            session.add_all(admission_stages)
            await session.flush()

            admission_statuses = [
                models.ConsultationStatus(id="sts00", name="Chua lien he", color_code="#999999", stage_id="stg01"),
                models.ConsultationStatus(id="sts05", name="Hen lien he lai", color_code="#FFA500", stage_id="stg02"),
                models.ConsultationStatus(id="sts06", name="Dong y tu van", color_code="#00FF00", stage_id="stg02"),
                models.ConsultationStatus(id="sts07", name="Da nop ho so", color_code="#0088FF", stage_id="stg03"),
                models.ConsultationStatus(id="sts09", name="Du dieu kien nhap hoc", color_code="#00CC00", stage_id="stg04"),
                models.ConsultationStatus(id="sts10", name="Da hoan tat hoc phi", color_code="#008800", stage_id="stg05"),
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
