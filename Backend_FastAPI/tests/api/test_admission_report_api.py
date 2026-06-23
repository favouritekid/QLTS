# tests/api/test_admission_report_api.py
"""
API-LEVEL TESTS: Weekly Admission Report endpoint.

Endpoint under test:
    GET /api/v2/admin/reports/admission-weekly
    Router:  app/routers/admission_reports.py
    Schema:  app/schemas/admission_report.py  (AdmissionWeeklyReportResponse)
    Service: app/services/admission_report_service.py  (scope/week/cohort contract)
    Gate:    require_admin_or_manager

Coverage (HTTP contract only — the service scope/week math has its own unit
tests in tests/services/ / tests/unit/):

  422  - group_by regex fail / academic_year ge fail / academic_year missing
  200  - admin, isolated empty year (2099): full response shape + week meta +
         attribution=="recomputed-current" + timezone, group_by=major & officer
  200  - money fields (FinanceMetrics Decimal) serialize as JSON *string*
  403  - manager WITHOUT a unit (PermissionDeniedError → 403)
  404  - manager WITH a unit requesting a DIFFERENT unit_id (ResourceNotFoundError
         → 404, no existence leak)

Auth pattern (mirrors tests/api/test_admission_workflow_api.py):
  Real DB users (conftest fixtures) + per-context ``_login()`` that re-reads the
  ``access_token`` cookie into an ``Authorization: Bearer`` header. We re-login
  immediately before each request to defeat shared httpx cookie-jar
  contamination when several users authenticate against the same ``client``
  (memory: ``test-httpx-cookie-jar-contamination``).

Run: pytest tests/api/test_admission_report_api.py -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.database import AsyncSessionLocal

try:
    from tests.fixtures.constants import AuthURLs, TestOrgData, TestUsers
except ImportError:
    pytest.fail("Could not import from tests.fixtures.constants")

pytestmark = pytest.mark.integration


# =============================================================================
# URL + helpers
# =============================================================================

REPORT_URL = "/api/v2/admin/reports/admission-weekly"

# Isolated academic year with no offerings/rounds/profiles in the test DB, so
# the 200 path is deterministic (empty rows, all-zero totals) and never depends
# on seeded data drifting under it.
EMPTY_YEAR = 2099


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """Re-login to refresh the shared cookie jar. Returns Bearer headers."""
    res = await client.post(
        AuthURLs.LOGIN, data={"username": username, "password": password}
    )
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    token = res.cookies.get("access_token")
    assert token, f"Login for {username} returned no access_token cookie"
    return {"Authorization": f"Bearer {token}"}


def _assert_report_shape(body: dict, *, group_by: str) -> None:
    """Assert the AdmissionWeeklyReportResponse contract surface."""
    # top-level keys
    for key in ("academic_year", "group_by", "week", "attribution", "rows", "totals"):
        assert key in body, f"missing top-level key '{key}': {body}"

    assert body["group_by"] == group_by
    assert body["attribution"] == "recomputed-current"
    assert isinstance(body["rows"], list)
    assert isinstance(body["totals"], dict)

    # week meta (BE owns the ISO-week contract; FE never derives it)
    week = body["week"]
    for key in ("iso_year", "iso_week", "week_start", "week_end", "timezone"):
        assert key in week, f"missing week key '{key}': {week}"
    assert week["timezone"] == "Asia/Ho_Chi_Minh"
    assert isinstance(week["iso_year"], int)
    assert isinstance(week["iso_week"], int)
    # week_start / week_end are ISO date strings (YYYY-MM-DD)
    assert isinstance(week["week_start"], str)
    assert isinstance(week["week_end"], str)


# =============================================================================
# Local fixture: manager WITHOUT a unit
# =============================================================================
#
# The shared ``manager_user_in_db`` fixture ALWAYS attaches a unit (pulled from
# ``seed_lead_dependencies``), so it cannot exercise the "manager without unit
# → 403" branch. Build a distinct unitless manager here via the same
# ``create_user_with_role`` helper conftest uses (unit_id=None), reusing the
# Casbin reload + idempotent-insert behavior. Separate username/email so it can
# coexist with the other manager fixtures in one DB.


@pytest_asyncio.fixture(scope="function")
async def manager_no_unit_user_in_db(setup_test_database):
    from app import models
    from app.main import fastapi_app
    from app.security import get_password_hash
    from tests.fixtures.users import create_user_with_role

    try:
        from casbin_async_sqlalchemy_adapter.adapter import CasbinRule
    except ImportError:  # pragma: no cover - adapter always present in test env
        CasbinRule = None

    user_data = {
        "username": "testmanager_nounit",
        "email": "manager_nounit@example.com",
        "password": "ManagerPassword!789",
        "role": "manager",
        "status": "active",
    }
    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data=user_data,
        casbin_role="role:manager",
        unit_id=None,  # the point of this fixture
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )


# =============================================================================
# 422 — query-param validation (no auth needed; FastAPI validates before deps,
# but we still send a valid admin token so a 401/403 can't mask a 422)
# =============================================================================


@pytest.mark.asyncio
async def test_group_by_invalid_regex_returns_422(
    client: AsyncClient, admin_user_in_db
):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR, "group_by": "foo"},
        headers=h,
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_academic_year_below_min_returns_422(
    client: AsyncClient, admin_user_in_db
):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(
        REPORT_URL,
        params={"academic_year": 1900},  # ge=2020
        headers=h,
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_academic_year_missing_returns_422(client: AsyncClient, admin_user_in_db):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(REPORT_URL, headers=h)  # academic_year required
    assert res.status_code == 422, res.text


# =============================================================================
# 200 — admin happy path (isolated empty year → empty rows, zero totals)
# =============================================================================


@pytest.mark.asyncio
async def test_admin_empty_year_returns_200_with_shape(
    client: AsyncClient, admin_user_in_db
):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR},  # group_by defaults to "major"
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    _assert_report_shape(body, group_by="major")

    assert body["academic_year"] == EMPTY_YEAR
    # round_code omitted → all rounds of the year; admin no unit → toàn trường.
    assert body["round_code"] is None
    assert body["scope_unit_id"] is None
    # Isolated year: nothing to report.
    assert body["rows"] == []


@pytest.mark.asyncio
async def test_admin_group_by_officer_returns_200_with_shape(
    client: AsyncClient, admin_user_in_db
):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR, "group_by": "officer"},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    _assert_report_shape(body, group_by="officer")
    assert body["rows"] == []


@pytest.mark.asyncio
async def test_finance_metrics_serialize_as_string(
    client: AsyncClient, admin_user_in_db
):
    """FinanceMetrics are Decimal → JSON string (Pydantic v2 default), even at
    zero on the empty path. FE ``formatVND`` expects strings; a regression to
    float/int here would silently break precision."""
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR},
        headers=h,
    )
    assert res.status_code == 200, res.text
    finance = res.json()["totals"]["finance"]
    for field in (
        "gross_in_week",
        "refund_in_week",
        "net_in_week",
        "application_net_in_week",
        "tuition_net_in_week",
        "net_cumulative",
    ):
        assert field in finance, f"missing finance field '{field}'"
        assert isinstance(
            finance[field], str
        ), f"finance.{field} should serialize as str, got {type(finance[field])}"


# =============================================================================
# 403 — manager without a unit (PermissionDeniedError)
# =============================================================================


@pytest.mark.asyncio
async def test_manager_without_unit_returns_403(
    client: AsyncClient, manager_no_unit_user_in_db
):
    h = await _login(
        client,
        manager_no_unit_user_in_db["username"],
        manager_no_unit_user_in_db["password"],
    )
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR},
        headers=h,
    )
    assert res.status_code == 403, res.text


# =============================================================================
# 404 — manager requesting a unit that is not their own (no existence leak)
# =============================================================================


@pytest.mark.asyncio
async def test_manager_foreign_unit_returns_404(
    client: AsyncClient,
    manager_user_in_db,  # attached to seed_lead_dependencies unit (UNIT_1 = 1)
    seed_other_unit,  # ensures UNIT_2 (9001) exists as a real, different unit
):
    h = await _login(
        client, TestUsers.MANAGER["username"], TestUsers.MANAGER["password"]
    )
    foreign_unit_id = TestOrgData.UNIT_2["id"]
    assert foreign_unit_id != TestOrgData.UNIT_1["id"]
    res = await client.get(
        REPORT_URL,
        params={"academic_year": EMPTY_YEAR, "unit_id": foreign_unit_id},
        headers=h,
    )
    assert res.status_code == 404, res.text


# =============================================================================
# Filter options — /admission-weekly/filters (admin + manager)
# =============================================================================

FILTERS_URL = "/api/v2/admin/reports/admission-weekly/filters"


@pytest.mark.asyncio
async def test_filters_manager_can_load_returns_200(
    client: AsyncClient, manager_user_in_db
):
    """Manager (a report user) MUST be able to load filter options. The old
    per-year rounds endpoint was admin-only, so managers got an empty Đợt
    dropdown; this endpoint shares the report's admin_or_manager gate."""
    h = await _login(
        client, TestUsers.MANAGER["username"], TestUsers.MANAGER["password"]
    )
    res = await client.get(FILTERS_URL, params={"academic_year": EMPTY_YEAR}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["academic_years"], list)
    assert isinstance(body["rounds"], list)
    # EMPTY_YEAR has no configured rounds → empty list (not an error).
    assert body["rounds"] == []


@pytest.mark.asyncio
async def test_filters_without_year_omits_rounds(client: AsyncClient, admin_user_in_db):
    h = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    res = await client.get(FILTERS_URL, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rounds"] == []  # no academic_year → rounds omitted
    assert isinstance(body["academic_years"], list)
