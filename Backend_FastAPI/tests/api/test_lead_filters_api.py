# tests/api/test_lead_filters_api.py
"""API-level tests for the new lead filters (LEAD_FILTER_UX_PLAN §4-§5).

Focus on the things that can only break above the repository layer:

- **Export parity (blocker P0):** ``/api/leads/export`` is a SEPARATE endpoint
  with its own query-param cluster; it must apply the new filters exactly like
  the list endpoint, or CSV/XLSX exports the wrong rows.
- **RBAC through deps:** an officer applying ``unassigned=true`` must get 0 rows
  (deps forces ``effective_officer_id=self`` → ``self AND IS NULL`` is empty).
- **Search unaccent e2e:** router → service → repo → ``f_unaccent`` in DB.

Self-contained seeding (own unit + consultation statuses) so it does not depend
on fixtures private to ``test_leads_crud.py``.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

LEADS_URL = "/api/leads"
EXPORT_URL = "/api/leads/export"

UNIT_ID = 9100
INIT_STATUS = "fltinit"
GIVEUP_STATUS = "fltgiveup"


@pytest_asyncio.fixture
async def filter_env(setup_test_database) -> dict:
    """Seed a dedicated unit + two consultation statuses for these tests."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(models.OrganizationUnit(
                id=UNIT_ID, name="Filter API Unit", type="department",
            ))
            s.add(models.ConsultationStatus(
                id=INIT_STATUS, name="Filter Init",
                color_code="#0000FF", stage_id=None, is_final=False,
            ))
            s.add(models.ConsultationStatus(
                id=GIVEUP_STATUS, name="Filter Giveup",
                color_code="#FF0000", stage_id=None, is_final=True,
            ))
    return {"unit_id": UNIT_ID, "init": INIT_STATUS, "giveup": GIVEUP_STATUS}


async def _seed_lead(unit_id, status_id, full_name, phone, **kw):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=full_name, phone=phone, source="Website",
                unit_id=unit_id, status="new",
                consultation_status_id=status_id, **kw,
            )
            s.add(lead)
            await s.flush()
            return lead.id


@pytest.mark.asyncio
async def test_list_and_export_apply_is_hot_filter(
    client: AsyncClient, admin_token_headers: dict, filter_env: dict
):
    """is_hot filter behaves identically on the list and export endpoints."""
    u = filter_env
    await _seed_lead(u["unit_id"], u["init"], "HotFilterLeadXYZ",
                     "0911000001", is_hot_lead=True)
    await _seed_lead(u["unit_id"], u["init"], "ColdFilterLeadXYZ",
                     "0911000002", is_hot_lead=False)

    # --- list ---
    r = await client.get(f"{LEADS_URL}?is_hot=1", headers=admin_token_headers)
    assert r.status_code == 200, r.text
    names = [lead["full_name"] for lead in r.json()["leads"]]
    assert "HotFilterLeadXYZ" in names
    assert "ColdFilterLeadXYZ" not in names

    # --- export parity (CSV body must reflect the same filter) ---
    e = await client.get(
        f"{EXPORT_URL}?is_hot=1&format=csv", headers=admin_token_headers
    )
    assert e.status_code == 200, e.text
    assert "HotFilterLeadXYZ" in e.text
    assert "ColdFilterLeadXYZ" not in e.text


@pytest.mark.asyncio
async def test_export_applies_consultation_status_filter(
    client: AsyncClient, admin_token_headers: dict, filter_env: dict
):
    """consultation_status_id must be honored by the export endpoint."""
    u = filter_env
    await _seed_lead(u["unit_id"], u["giveup"], "GiveupExportLeadXYZ",
                     "0911000003")
    await _seed_lead(u["unit_id"], u["init"], "OtherExportLeadXYZ",
                     "0911000004")

    e = await client.get(
        f"{EXPORT_URL}?consultation_status_id={u['giveup']}&format=csv",
        headers=admin_token_headers,
    )
    assert e.status_code == 200, e.text
    assert "GiveupExportLeadXYZ" in e.text
    assert "OtherExportLeadXYZ" not in e.text


@pytest.mark.asyncio
async def test_officer_unassigned_filter_returns_empty(
    client: AsyncClient, officer_token_headers: dict, filter_env: dict
):
    """RBAC scope anchor: officer + unassigned=true → 0 rows (deps forces
    self → empty AND). This proves scope hides others' leads; the predicate
    itself is proven by test_admin_unassigned_filter_shows_only_unassigned
    (API) and test_unassigned_only_null_officer (repo)."""
    u = filter_env
    await _seed_lead(u["unit_id"], u["init"], "UnassignedInUnit",
                     "0911000005", assigned_officer_id=None)

    r = await client.get(
        f"{LEADS_URL}?unassigned=1", headers=officer_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["total_count"] == 0


@pytest.mark.asyncio
async def test_admin_unassigned_filter_shows_only_unassigned(
    client: AsyncClient, admin_token_headers: dict,
    officer_user_in_db: dict, filter_env: dict
):
    """unassigned=true returns ONLY leads with no officer, for an unscoped
    admin — proves the predicate filters (not vacuously empty like the officer
    case). Seeds one unassigned + one assigned lead and asserts the assigned
    one is excluded."""
    u = filter_env
    await _seed_lead(u["unit_id"], u["init"], "UnassignedAdminXYZ",
                     "0911000008", assigned_officer_id=None)
    await _seed_lead(u["unit_id"], u["init"], "AssignedAdminXYZ",
                     "0911000009", assigned_officer_id=officer_user_in_db["id"])

    r = await client.get(
        f"{LEADS_URL}?unassigned=1", headers=admin_token_headers
    )
    assert r.status_code == 200, r.text
    names = [lead["full_name"] for lead in r.json()["leads"]]
    assert "UnassignedAdminXYZ" in names
    assert "AssignedAdminXYZ" not in names


@pytest.mark.asyncio
async def test_search_unaccent_via_api(
    client: AsyncClient, admin_token_headers: dict, filter_env: dict
):
    """End-to-end diacritic-insensitive name search through the API.

    Seeds a matching AND a non-matching lead so the assertions prove the search
    actually FILTERS (a no-op search returning everything would fail the
    'not in' checks), not merely that the matching row is returned.
    """
    u = filter_env
    await _seed_lead(u["unit_id"], u["init"], "Nguyễn Văn Hùng", "0911000006")
    await _seed_lead(u["unit_id"], u["init"], "Trần Thị Bình", "0911000007")

    r = await client.get(
        f"{LEADS_URL}?search=nguyen van", headers=admin_token_headers
    )
    assert r.status_code == 200, r.text
    names = [lead["full_name"] for lead in r.json()["leads"]]
    assert "Nguyễn Văn Hùng" in names       # diacritic-insensitive match
    assert "Trần Thị Bình" not in names      # proves search actually filters

    # Negative control: a term matching neither name returns neither.
    r2 = await client.get(
        f"{LEADS_URL}?search=khongtontai999", headers=admin_token_headers
    )
    assert r2.status_code == 200, r2.text
    names2 = [lead["full_name"] for lead in r2.json()["leads"]]
    assert "Nguyễn Văn Hùng" not in names2
    assert "Trần Thị Bình" not in names2
