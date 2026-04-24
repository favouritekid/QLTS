"""API-level check: `assign_officer` available_action is role-gated (PR #3).

The FE bulk bar derives visibility from `profile.available_actions`. This
test verifies the backend emits `assign_officer` to admins unconditionally
and to managers only when their unit matches the profile's lead unit —
never to officers.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"


@pytest_asyncio.fixture
async def adm_config(seed_lead_dependencies: dict):
    """Copy of the admission-config fixture from test_admission_workflow_api.

    Duplicated inline to keep this test self-contained. If more PR #3
    permission probes are added later, promote to a shared conftest.
    """
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp())}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(code=f"tq_{ts}", name=f"TQ_{ts}", display_order=1)
            s.add(ot); await s.flush()
            dt = models.ConfigDocumentType(code=f"tcc_{ts}", name=f"TCC_{ts}", display_order=1)
            s.add(dt); await s.flush()
            po = models.ProgramOffering(
                offering_type=f"TQ_{ts}", program_id=mpid, offering_type_id=ot.id,
                is_active=True, duration_semesters=6,
            )
            s.add(po); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id, academic_year=2026,
                tuition_fee_per_year=5000000, annual_admission_quota=100, is_published=True,
            )
            s.add(ai); await s.flush()
            am = models.AdmissionMethod(
                code=f"hb_{ts}", name=f"HB_{ts}",
                requires_gpa=True, requires_subject_scores=False, is_active=True,
            )
            s.add(am); await s.flush()
            ac = models.AdmissionCriteria(
                method_id=am.id, code=f"TC_{ts}", name=f"TC_{ts}",
                min_gpa=6.0, scoring_method="average", subject_selection_mode="fixed",
                policy_version="2026.1", is_active=True,
            )
            s.add(ac); await s.flush()
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id, criteria_id=ac.id,
                status="active", display_name="Test", display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
    return {"unit_id": uid, "offering_id": po.id, "method_id": am.id}


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest.mark.asyncio
async def test_assign_officer_action_role_matrix(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    manager_user_in_db: dict,
    adm_config: dict,
):
    """Create a draft admission profile and inspect its available_actions
    as admin / manager (same unit) / officer in sequence.

    Expectations driven by ``_compute_frontend_fields`` rules:
    - admin → ``assign_officer`` present (regardless of unit)
    - manager in the same unit as the lead → ``assign_officer`` present
    - officer (even the assigned one) → ``assign_officer`` absent
    """
    # Arrange — seed a lead + draft profile via admin.
    lead_resp = await client.post(LeadsURLs.LEADS, json={
        "full_name": "PR3 Assign Officer Probe",
        "phone": "0988123450",
        "source": "website",
        "unit_id": adm_config["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"],
        "offering_id": adm_config["offering_id"],
    }, headers=admin_token_headers)
    assert lead_resp.status_code in (200, 201), lead_resp.text
    lead_id = lead_resp.json()["id"]

    # Business rule: a consultation must exist before creating an admission
    # profile. Seed a minimal one using the default-seeded status.
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    await client.post(
        f"{LeadsURLs.LEADS}/{lead_id}/consultations",
        json={
            "status_id": INITIAL_LEAD_STATUS_ID,
            "method": "phone",
            "notes": "Pre-admission consultation",
        },
        headers=admin_token_headers,
    )

    prof = await client.post(ADMISSIONS, json={
        "lead_id": lead_id,
        "admission_method_id": adm_config["method_id"],
    }, headers=admin_token_headers)
    assert prof.status_code in (200, 201), prof.text
    pid = prof.json()["id"]

    # Admin GET → assign_officer must be present.
    admin_detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=admin_token_headers)).json()
    assert "assign_officer" in admin_detail.get("available_actions", []), (
        "Admin should always have assign_officer action; "
        f"got: {admin_detail.get('available_actions')}"
    )
    assert admin_detail.get("permissions", {}).get("assign_officer") is True

    # Manager (same unit as the lead) → assign_officer must be present.
    mh = await _login(client, manager_user_in_db["username"], manager_user_in_db["password"])
    manager_detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=mh)).json()
    assert "assign_officer" in manager_detail.get("available_actions", []), (
        "Manager in the same unit as the lead should have assign_officer; "
        f"got: {manager_detail.get('available_actions')}"
    )
    assert manager_detail.get("permissions", {}).get("assign_officer") is True

    # Officer GET → assign_officer must be absent.
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    officer_detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert "assign_officer" not in officer_detail.get("available_actions", []), (
        "Officer must NOT see assign_officer action; "
        f"got: {officer_detail.get('available_actions')}"
    )
    assert officer_detail.get("permissions", {}).get("assign_officer") is False


@pytest.mark.asyncio
async def test_bulk_assign_rejects_non_officer_target(
    client: AsyncClient,
    admin_token_headers: dict,
    manager_user_in_db: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """bulk_assign must refuse to set lead.assigned_officer_id to a user
    whose role is not OFFICER. Historically the route only checked unit
    membership, which silently allowed a manager or admin to be stored
    as the assigned officer — breaking workload metrics and later
    officer-scoped queries. Mirrors the validation lead_service has
    always enforced on direct/auto assignment.
    """
    # Seed a lead + draft profile so bulk_assign has a target row.
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    lead = (await client.post(LeadsURLs.LEADS, json={
        "full_name": "PR3 Assign Validation",
        "phone": "0988123451",
        "source": "website",
        "unit_id": adm_config["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"],
        "offering_id": adm_config["offering_id"],
    }, headers=admin_token_headers)).json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={
            "status_id": INITIAL_LEAD_STATUS_ID,
            "method": "phone",
            "notes": "Pre-admission consultation",
        },
        headers=admin_token_headers,
    )
    prof = (await client.post(ADMISSIONS, json={
        "lead_id": lead["id"],
        "admission_method_id": adm_config["method_id"],
    }, headers=admin_token_headers)).json()

    # Attempt to assign the manager (not an officer) → 400.
    resp = await client.post(
        f"{ADMISSIONS}/bulk/assign",
        json={"profile_ids": [prof["id"]], "officer_id": manager_user_in_db["id"]},
        headers=admin_token_headers,
    )
    assert resp.status_code == 400, (
        f"Expected 400 for non-officer target; got {resp.status_code}: {resp.text}"
    )
    assert "officer" in resp.text.lower(), resp.text

    # Sanity: the legitimate officer target still succeeds.
    ok = await client.post(
        f"{ADMISSIONS}/bulk/assign",
        json={"profile_ids": [prof["id"]], "officer_id": officer_user_in_db["id"]},
        headers=admin_token_headers,
    )
    assert ok.status_code == 200, f"Officer target should succeed: {ok.text}"
