"""Officer-scoped POST /api/fees/calculate authorization (PR #7).

Matrix:
* owning officer on approved profile → 201
* officer on same-unit profile they don't own → 404 (IDOR convention)
* officer on draft profile they own → 404 (status gate)
* admin on any profile → 201
* manager on same-unit profile → 201
* accountant on cross-unit profile → 201 (central finance — global scope)

The 4 permission points are asserted via ``available_actions`` on
``GET /admissions/{id}``; the full end-to-end fee creation is
exercised only for the happy-path owning-officer case since the
downstream fee service is unit-tested elsewhere.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs
from tests.fixtures.builders import (
    SUBMITTABLE_PERMANENT_ADDRESS,
    ensure_submittable_ward,
)


ADMISSIONS = "/api/admissions"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def fee_calc_config(seed_lead_dependencies: dict):
    """Seed Phase E.4 submit invariants so PR-7 fee authorization tests
    can actually reach the ``/api/fees/calculate`` gate.

    Mirrors the canonical ``adm_config`` pattern in
    ``tests/api/test_admission_workflow_api.py:177`` — same submit-gate
    requirements (degree_level + offering_type + OAC + VnSchool + KV
    assignment) so this test file does not drift its own bespoke setup.

    Fixture only. No production code change, no manual override.
    """
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp())}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Canonical GDNN degree code (Phase E.4 whitelist) — get-or-create
            # to tolerate parallel-test-module DB collisions.
            cdl = (await s.execute(
                select(models.ConfigDegreeLevel).where(
                    models.ConfigDegreeLevel.code == "cao_dang"
                )
            )).scalar_one_or_none()
            if cdl is None:
                cdl = models.ConfigDegreeLevel(
                    code="cao_dang", name="Cao đẳng", display_order=1,
                )
                s.add(cdl); await s.flush()

            # Canonical chính quy offering type — same get-or-create rationale.
            cot = (await s.execute(
                select(models.ConfigOfferingType).where(
                    models.ConfigOfferingType.code == "chinh_quy"
                )
            )).scalar_one_or_none()
            if cot is None:
                cot = models.ConfigOfferingType(
                    code="chinh_quy", name="Chính quy", display_order=1,
                )
                s.add(cot); await s.flush()

            # Backfill MAJOR_1.degree_level_id (seed_lead_dependencies leaves
            # it NULL for backward compat; submit gate requires the FK).
            major = (await s.execute(
                select(models.MajorProgram).where(models.MajorProgram.id == mpid)
            )).scalar_one()
            if major.degree_level_id is None:
                major.degree_level_id = cdl.id
                await s.flush()

            dt = models.ConfigDocumentType(code=f"tcc_{ts}", name=f"TCC_{ts}", display_order=1)
            s.add(dt); await s.flush()
            po = models.ProgramOffering(
                offering_type=f"TQ_{ts}", program_id=mpid, offering_type_id=cot.id,
                is_active=True, duration_semesters=6,
            )
            s.add(po); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id, academic_year=2026,
                tuition_fee_per_year=5000000, annual_admission_quota=100, is_published=True,
            )
            s.add(ai); await s.flush()
            # C2 happy-path: tuition calculate_fee resolves the canonical
            # amount from offering_semester_tuition (ADR-002), NOT
            # tuition_fee_per_year. Without a HK1 row the service raises
            # BadRequest("Chưa cấu hình học phí cho HK1") → 400. Seed HK1.
            s.add(models.OfferingSemesterTuition(
                academic_info_id=ai.id, semester_no=1, amount=5000000,
            ))
            await s.flush()
            am = models.AdmissionMethod(
                code=f"hb_{ts}", name=f"HB_{ts}",
                requires_gpa=True, requires_subject_scores=False, is_active=True,
            )
            s.add(am); await s.flush()
            ac = models.AdmissionCriteria(
                method_id=am.id, code=f"TC_{ts}", name=f"TC_{ts}",
                min_gpa=0.0, scoring_method="average", subject_selection_mode="fixed",
                policy_version="2026.1", is_active=True,
            )
            s.add(ac); await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id,
                admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name="PR7", display_order=0,
                visibility="public",
                # Keep lax to avoid the PR #6 verified-docs gate for this test.
                allow_unverified_submission=True,
            )
            s.add(ap); await s.flush()
            dg = models.DocumentGroup(
                offering_type_id=cot.id,
                admission_method_id=am.id,
                code=f"dg_{ts}",
                name=f"DG_{ts}",
                is_active=True,
            )
            s.add(dg); await s.flush()

            # OAC link → admission_service.create_profile step 14b
            # auto-writes profile.offering_admission_config_id.
            oac = models.OfferingAdmissionConfig(
                academic_info_id=ai.id, criteria_id=ac.id, is_active=True,
            )
            s.add(oac); await s.flush()

            # Phase E.4 KV resolution catalog — VnSchool + KV assignment
            # covering candidate's THPT years (2019-2022). academic_history
            # entry must carry ``school_id`` (passed via _create_approved_
            # profile PUT body) so the LICH_SU_THPT branch resolves a KV.
            sch = models.VnSchool(
                moet_school_code=f"S{ts[-6:]}",
                moet_province_code="001",
                name=f"THPT Test {ts}",
                province="Hà Nội",
                district="Ba Đình",
                level="THPT",
            )
            s.add(sch); await s.flush()
            kva = models.VnSchoolKvAssignment(
                school_id=sch.id, kv_code="KV3",
                effective_from_year=2019, effective_to_year=2022,
                source="manual_admin",
            )
            s.add(kva); await s.flush()
            school_id = sch.id

            # C2 happy-path needs a real installment plan: the route rejects
            # unknown/inactive codes with 400 before fee creation. "FULL" is
            # the canonical single-payment seed code (schemas/finance.py
            # default) but the test DB uses create_all() (no seed), so
            # get-or-create it here. Tolerates parallel-module collisions.
            full_plan = (await s.execute(
                select(models.InstallmentPlan).where(
                    models.InstallmentPlan.code == "FULL"
                )
            )).scalar_one_or_none()
            if full_plan is None:
                s.add(models.InstallmentPlan(
                    code="FULL",
                    name="Thanh toán 1 lần",
                    installment_count=1,
                    schedule=[{
                        "installment_no": 1,
                        "due_days_offset": 0,
                        "percent": 100.0,
                        "description": "Toàn bộ",
                    }],
                    is_active=True,
                ))
                await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "school_id": school_id,
        # Round contract hardening (plan v4): now-required admission_round_id.
        "round_id": round_id,
    }


async def _create_approved_profile(
    client,
    admin_headers,
    officer_user,
    cfg,
    *,
    lead_name="PR7 Probe",
    approve: bool = True,
):
    """Create lead + admission, officer submits, admin approves.

    ``approve=False`` stops at the ``submitted`` state — used by the C2
    fast-track tests (fee calculation is now allowed at ``submitted``).
    """
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (await client.post(LeadsURLs.LEADS, json={
        "full_name": lead_name,
        "phone": phone,
        "source": "website",
        "unit_id": cfg["unit_id"],
        "assigned_officer_id": officer_user["id"],
        "offering_id": cfg["offering_id"],
        "gpa": 8.5,
    }, headers=admin_headers)).json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "Pre-admission"},
        headers=admin_headers,
    )
    prof = (await client.post(ADMISSIONS, json={
        "lead_id": lead["id"],
        "admission_method_id": cfg["method_id"],
        "admission_round_id": cfg["round_id"],
        "academic_year": 2026,
    }, headers=admin_headers)).json()

    # Minimal fill so submit passes validation (PR #6 lax mode → only docs).
    oh = await _login(client, officer_user["username"], officer_user["password"])
    cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = prof["version"]
    # PR-1.5 Commit 5 (2026-05-24) — Phase E.4 submit invariants. Mirrors
    # the _submit helper in tests/api/test_admission_workflow_api.py:
    #   * cultural_education_level + vocational_qualification → satisfy
    #     CĐ chính quy eligibility gate (priority_service.validate_eligibility)
    #   * academic_history entry carries level + grade_to + school_id so the
    #     LICH_SU_THPT branch resolves a KV via vn_school_kv_assignment
    # Gap #3 submit gate: seed a current-era ward + fill permanent address so
    # submit transitions to 'submitted' (not draft with "Thiếu địa chỉ thường trú").
    await ensure_submittable_ward()
    await client.put(f"{ADMISSIONS}/{prof['id']}", json={
        "version": v,
        **SUBMITTABLE_PERMANENT_ADDRESS,
        "citizen_id": cccd,
        "gender": "male",
        "dob": "2001-01-01",
        "nationality": "Viet Nam",
        "ethnicity": "Kinh",
        "place_of_birth": "Test",
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
        "family_info": [{"relationship": "Cha", "full_name": "P", "phone": "0901111111", "is_primary_guardian": True}],
        "academic_history": [{
            "school_name": "THPT",
            "year_from": 2019,
            "year_to": 2022,
            "gpa": 8.5,
            "graduation_type": "THPT",
            "level": "THPT",
            "grade_to": 12,
            "school_id": cfg["school_id"],
        }],
        "admission_scores": {"gpa": 8.5, "subject_scores": {}},
    }, headers=oh)

    v = (await client.get(f"{ADMISSIONS}/{prof['id']}", headers=oh)).json()["version"]
    submit = await client.post(f"{ADMISSIONS}/{prof['id']}/submit", json={"version": v}, headers=oh)
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "submitted", submit.json()

    if not approve:
        return prof["id"]

    # Re-login as admin since the shared cookie jar was last written by
    # the officer submit; bearer token from the fixture may already be
    # invalidated via rotation.
    fresh_admin = await _login(client, "testadmin", "AdminPassword!123")
    v = (await client.get(f"{ADMISSIONS}/{prof['id']}", headers=fresh_admin)).json()["version"]
    approve_resp = await client.post(
        f"{ADMISSIONS}/{prof['id']}/approve",
        json={"notes": "OK", "version": v},
        headers=fresh_admin,
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["status"] == "approved"

    return prof["id"]


@pytest.mark.asyncio
async def test_officer_can_list_installment_plans(
    client: AsyncClient,
    officer_user_in_db: dict,
):
    """CalculateFeeDialog populates its plan Select from /api/installment-plans.

    Without the PR #7 review policy, the officer token would get 403
    here, the Select would stay empty, and the submit button would be
    permanently disabled — the officer-scoped flow becomes a silent
    dead-end. Test locks the Casbin read access for role:officer.
    """
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    resp = await client.get("/api/installment-plans", headers=oh)
    assert resp.status_code == 200, (
        f"Officer should be able to read installment plans, got {resp.status_code}: {resp.text[:200]}"
    )
    # Don't assert a specific shape — the point is Casbin admits the route.
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_calculate_fee_visible_in_actions_for_owning_officer(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """available_actions carries calculate_fee for officer on their own approved profile."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config
    )
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert "calculate_fee" in detail["available_actions"], detail["available_actions"]
    assert detail["permissions"]["calculate_fee"] is True


@pytest.mark.asyncio
async def test_calculate_fee_hidden_for_officer_on_draft(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Draft profile → calculate_fee is status-gated off."""
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (await client.post(LeadsURLs.LEADS, json={
        "full_name": "PR7 Draft",
        "phone": phone,
        "source": "website",
        "unit_id": fee_calc_config["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"],
        "offering_id": fee_calc_config["offering_id"],
    }, headers=admin_token_headers)).json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "Pre-admission"},
        headers=admin_token_headers,
    )
    prof = (await client.post(ADMISSIONS, json={
        "lead_id": lead["id"],
        "admission_method_id": fee_calc_config["method_id"],
        "admission_round_id": fee_calc_config["round_id"],
        "academic_year": 2026,
    }, headers=admin_token_headers)).json()

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    detail = (await client.get(f"{ADMISSIONS}/{prof['id']}", headers=oh)).json()
    assert "calculate_fee" not in detail["available_actions"]
    assert detail["permissions"]["calculate_fee"] is False


@pytest.mark.asyncio
async def test_calculate_fee_hidden_for_same_unit_unassigned_officer(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Officer in the same unit but NOT assigned to the lead must NOT see
    calculate_fee nor be able to hit the route.

    Catches the regression where the scope formula gets loosened from
    `same-unit AND assigned` to `same-unit`. Approves the profile via
    admin, then un-assigns the officer from the lead (lead.assigned_
    officer_id = NULL) and re-queries both the admission detail and the
    fee-calc route.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="PR7 UnassignedProbe",
    )

    # Un-assign the officer from the lead — officer keeps same unit_id.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import select, update
            prof = (await s.execute(
                select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid)
            )).scalar_one()
            await s.execute(
                update(models.Lead)
                .where(models.Lead.id == prof.lead_id)
                .values(assigned_officer_id=None)
            )

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    # GET: flag removed from available_actions.
    # IDOR on GET for officer requires lead.assigned_officer_id match when
    # unit_id matches — unassigning drops them out of scope entirely, so
    # the profile read itself returns 404.
    detail = await client.get(f"{ADMISSIONS}/{pid}", headers=oh)
    assert detail.status_code == 404, (
        f"Same-unit but unassigned officer should lose profile access entirely; "
        f"got {detail.status_code}: {detail.text[:200]}"
    )

    # POST /fees/calculate: service-layer _fee_calc_authorized rejects
    # even if Casbin admits the route.
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code in (403, 404), (
        f"Same-unit unassigned officer should be denied, got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.asyncio
async def test_calculate_fee_route_404_for_cross_unit_officer(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Officer authenticated in a different unit must get 404 on calculate_fee.

    Exercises _fee_calc_authorized at the route level — the owning officer
    is used to approve the profile (via admin), then we simulate a
    cross-unit officer by creating a new user in a different unit and
    hitting the route with their token.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="PR7 CrossUnit",
    )

    # Approved profile created; simulate a cross-unit officer by creating
    # a second org unit and moving the officer there. Leads stay in the
    # original unit so the lead.unit_id != user.unit_id branch fires.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import select, update
            # Test DB uses create_all() so the id sequence isn't synced
            # after fixture-seeded units; bump the max explicitly so the
            # insert doesn't collide with id=1 from the shared fixture.
            from sqlalchemy import text as sa_text
            max_id = (await s.execute(
                sa_text("SELECT COALESCE(MAX(id), 0) FROM organization_unit")
            )).scalar_one()
            other_unit = models.OrganizationUnit(
                id=max_id + 1,
                name="PR7 Cross-unit probe",
                type="department",
                is_active=True,
            )
            s.add(other_unit)
            await s.flush()

            target = (await s.execute(
                select(models.User).where(models.User.username == officer_user_in_db["username"])
            )).scalar_one()
            await s.execute(
                update(models.User).where(models.User.id == target.id).values(unit_id=other_unit.id)
            )

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    # Either 403 (Casbin) or 404 (service-layer IDOR); both assert the
    # officer can't create fees for a profile outside their unit.
    assert resp.status_code in (403, 404), (
        f"Cross-unit officer should be denied, got {resp.status_code}: {resp.text[:200]}"
    )


# ==============================================================================
# C2 — fee calculation allowed at ``submitted`` (fast-track prepay/hold-spot)
# ==============================================================================
#
# Mirrors the two sites that gate fee creation (must stay in sync):
#   * routers/fees.py::_fee_calc_authorized  (route gate, 404 on fail)
#   * admission_service.py _compute_permissions["calculate_fee"] (FE flag)
# Before C2 both required post-decision status (approved/confirmed/enrolled);
# C2 adds ``submitted`` so officers can collect a tuition prepay before the
# decision. Scope: officer phụ trách + manager cùng unit + accountant/admin
# toàn hệ thống (accountant is a central finance role — unit-agnostic).


@pytest.mark.asyncio
async def test_calculate_fee_visible_in_actions_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Site B mirror: available_actions/permissions carry calculate_fee for the
    owning officer while the profile is still ``submitted`` (not yet approved).
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="C2 Submitted Visible", approve=False,
    )
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert detail["status"] == "submitted", detail.get("status")
    assert "calculate_fee" in detail["available_actions"], detail["available_actions"]
    assert detail["permissions"]["calculate_fee"] is True


@pytest.mark.asyncio
async def test_owning_officer_calculate_tuition_at_submitted_auto_issues(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """C2 + B4 end-to-end at ``submitted``:
    * owning officer → 201 (Site A route gate now admits submitted);
    * tuition invoice is auto-issued (status == "issued", not draft);
    * the captured invoice_cb fires INVOICE_ISSUED (router awaits it).

    INVOICE_ISSUED is asserted by patching the dispatcher used inside the
    invoice post-commit closure (same technique as
    test_fee_calculated_event.py). The closure does a late import of
    ``safe_dispatch`` from notification_dispatcher, so patching the module
    attribute intercepts it regardless of call site.
    """
    from unittest.mock import AsyncMock, patch
    from app.core.events import SystemEvents

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="C2 Submitted AutoIssue", approve=False,
    )
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])

    with patch(
        "app.services.notification_dispatcher.safe_dispatch",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        resp = await client.post(
            "/api/fees/calculate",
            json={
                "admission_profile_id": pid,
                "fee_type": "tuition",
                "installment_plan_code": "FULL",
                "semester_no": 1,
            },
            headers=oh,
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    invoices = body.get("invoices") or []
    assert invoices, f"Expected at least one invoice, got: {body}"
    # Auto-issue: tuition invoice is issued immediately, not left as draft.
    assert all(inv["status"] == "issued" for inv in invoices), invoices

    # B4: the issue callback must have been awaited → INVOICE_ISSUED dispatched.
    events = {c.kwargs.get("event") for c in mock_dispatch.await_args_list}
    assert SystemEvents.INVOICE_ISSUED in events, (
        f"INVOICE_ISSUED not dispatched; events seen: {events}"
    )


@pytest.mark.asyncio
async def test_non_owning_officer_404_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """An officer who does NOT own the lead is denied (404) even at submitted —
    the same-unit AND assigned scope is preserved by C2 (only status loosened).
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="C2 Submitted Unassigned", approve=False,
    )
    # Un-assign the officer from the lead — officer keeps same unit_id.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import update
            prof = (await s.execute(
                select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid)
            )).scalar_one()
            await s.execute(
                update(models.Lead)
                .where(models.Lead.id == prof.lead_id)
                .values(assigned_officer_id=None)
            )

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code in (403, 404), (
        f"Non-owning officer should be denied at submitted, got "
        f"{resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.asyncio
async def test_manager_same_unit_can_calculate_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    manager_user_in_db: dict,
    fee_calc_config: dict,
):
    """Manager in the same unit can calculate fee at submitted (quyền giữ
    nguyên — manager/accountant cùng unit đều tính được)."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="C2 Submitted Manager", approve=False,
    )
    mh = await _login(
        client, manager_user_in_db["username"], manager_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=mh,
    )
    assert resp.status_code == 201, (
        f"Same-unit manager should calculate fee at submitted, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )


@pytest_asyncio.fixture
async def accountant_same_unit(seed_lead_dependencies: dict):
    """Accountant user in the SAME unit as the seeded leads/profiles.

    Built inline (no ACCOUNTANT entry in TestUsers / shared conftest) via
    the canonical _create_user_and_role helper so the C2 same-unit case
    doesn't depend on a fixture local to another module.
    """
    from tests.conftest import _create_user_and_role
    user_data = {
        "username": "c2_accountant_unit1",
        "email": "c2_accountant_unit1@example.com",
        "password": "AccountantPassword!345",
        "role": "accountant",
        "status": "active",
    }
    return await _create_user_and_role(
        user_data, "role:accountant", unit_id=seed_lead_dependencies["unit_id"]
    )


@pytest.mark.asyncio
async def test_accountant_same_unit_can_calculate_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """Accountant in the same unit can calculate fee at submitted."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="C2 Submitted Accountant", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=ah,
    )
    assert resp.status_code == 201, (
        f"Same-unit accountant should calculate fee at submitted, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )


@pytest.mark.asyncio
async def test_accountant_cross_unit_can_calculate_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Accountant in a DIFFERENT unit can STILL calculate fee — accountant is a
    central finance role with global scope (unlike officer/manager which are
    unit-bound). Locks the accountant-global behaviour so a future refactor
    can't silently re-scope accountant back to their own unit — the exact bug
    this guards: a central accountant in 'Phòng Hành chính' must be able to
    raise fees for profiles owned by 'Phòng Tuyển Sinh'.

    Mirror of ``test_calculate_fee_route_404_for_cross_unit_officer`` (which
    asserts 404 for a cross-unit OFFICER) — same setup, opposite expectation
    for the accountant role.
    """
    from sqlalchemy import text as sa_text
    from tests.conftest import _create_user_and_role

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Accountant CrossUnit", approve=False,
    )

    # Brand-new org unit distinct from the profile's unit; bump the id past the
    # fixture-seeded max (test DB uses create_all(), sequence isn't synced).
    async with AsyncSessionLocal() as s:
        async with s.begin():
            max_id = (await s.execute(
                sa_text("SELECT COALESCE(MAX(id), 0) FROM organization_unit")
            )).scalar_one()
            other_unit = models.OrganizationUnit(
                id=max_id + 1,
                name="Accountant cross-unit probe",
                type="department",
                is_active=True,
            )
            s.add(other_unit)
            await s.flush()
            other_unit_id = other_unit.id

    acct = await _create_user_and_role(
        {
            "username": "xunit_accountant",
            "email": "xunit_accountant@example.com",
            "password": "AccountantPassword!345",
            "role": "accountant",
            "status": "active",
        },
        "role:accountant",
        unit_id=other_unit_id,
    )
    ah = await _login(client, acct["username"], acct["password"])
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=ah,
    )
    assert resp.status_code == 201, (
        f"Cross-unit accountant should still calculate fee (global finance), "
        f"got {resp.status_code}: {resp.text[:300]}"
    )


@pytest.mark.asyncio
async def test_accountant_denied_heavy_finance_mutations(
    client: AsyncClient,
    accountant_same_unit: dict,
):
    """Separation of duties: accountant verifies/records cash + reads finance
    org-wide, but is NOT admitted to the 4 'heavy' mutations — waive/recalculate
    fee, cancel/apply-penalty invoice. Those routes gate RequireManager
    (admin + manager only), so accountant must get 403.

    Locks the can_*-vs-route-gate alignment (thin-client contract): the fee/
    invoice builders must NOT expose these actions to accountant, otherwise the
    FE renders a button whose every click 403s. RequireManager rejects before
    any resource load, so arbitrary ids suffice.
    """
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )

    waive = await client.post(
        "/api/fees/1/waive",
        json={"waive_amount": "1000", "reason": "x"},
        headers=ah,
    )
    assert waive.status_code == 403, f"waive: {waive.text[:200]}"

    recalc = await client.post(
        "/api/fees/1/recalculate",
        params={"new_base_amount": "1000", "reason": "x"},
        headers=ah,
    )
    assert recalc.status_code == 403, f"recalc: {recalc.text[:200]}"

    cancel = await client.put(
        "/api/invoices/1/cancel", params={"reason": "x"}, headers=ah
    )
    assert cancel.status_code == 403, f"cancel: {cancel.text[:200]}"

    penalty = await client.post(
        "/api/invoices/1/apply-penalty",
        params={"penalty_amount": "1000", "reason": "trễ hạn"},
        headers=ah,
    )
    assert penalty.status_code == 403, f"penalty: {penalty.text[:200]}"


# ==============================================================================
# L2 — submitted gate for multi-NV is gated on the NV count
# ==============================================================================
#
# C2 opened the ``submitted`` state for fee calculation. A MULTI-NV profile
# (``uses_choice_engine=True``) at ``submitted`` with ≥2 nguyện vọng — or none
# added yet — has not locked its admitted ngành (all choices decision="pending"
# until publish), so pricing tuition now risks the WRONG ngành. BUT a multi-NV
# profile with EXACTLY ONE nguyện vọng has its ngành already determined, so it
# IS eligible (single-choice carve-out — see is_fee_eligible + the multi-NV
# single-choice 201 test in test_phase3_pr3d_b_choice_crud.py). The gate is
# shared across BOTH sites:
#   * routers/fees.py::_fee_calc_authorized               (route gate, 404)
#   * admission_service.py _compute_*["calculate_fee"]    (FE flag)
# The tests below flip ``uses_choice_engine`` WITHOUT adding choices, so they
# exercise the 0-NV case (blocked); a multi-NV profile also becomes eligible
# after publish → admitted-like (covered by ``is_admitted_like``), which these
# tests assert is NOT over-tightened.
#
# ``uses_choice_engine`` is a real Boolean COLUMN on AdmissionProfile (not a
# computed property), so the tests flip it directly in the DB — mirroring how
# the cross-unit / unassigned tests above mutate User.unit_id / Lead.assigned_
# officer_id. This isolates the gate under test from the choice-engine
# evaluation pipeline.


async def _set_choice_engine(pid: int, *, value: bool, status: str | None = None):
    """Flip ``uses_choice_engine`` (and optionally ``status``) on a profile.

    Direct DB mutation keeps the L2 gate tests deterministic without driving the
    full multi-NV publish workflow. ``status`` is constrained by the model
    CheckConstraint — pass an allowed value (e.g. ``approved`` for an
    admitted-like state).
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import update
            values = {"uses_choice_engine": value}
            if status is not None:
                values["status"] = status
            await s.execute(
                update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == pid)
                .values(**values)
            )


@pytest.mark.asyncio
async def test_calculate_fee_hidden_for_multi_nv_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Site B mirror: a MULTI-NV profile (``uses_choice_engine=True``) with no
    nguyện vọng yet (0 choices) at ``submitted`` must NOT expose calculate_fee —
    the ngành is undetermined (only the EXACTLY-ONE-choice case is eligible).

    The owning officer would otherwise see the button and be able to auto-issue
    tuition for an as-yet-undecided ngành.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="L2 MultiNV Submitted Hidden", approve=False,
    )
    await _set_choice_engine(pid, value=True)

    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert detail["status"] == "submitted", detail.get("status")
    assert (
        "calculate_fee" not in detail["available_actions"]
    ), detail["available_actions"]
    assert detail["permissions"]["calculate_fee"] is False


@pytest.mark.asyncio
async def test_calculate_fee_route_404_for_multi_nv_at_submitted(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Site A mirror: the route gate (_fee_calc_authorized) rejects a multi-NV
    profile with no nguyện vọng yet (0 choices) at ``submitted`` with 404 even
    for the owning officer (only the EXACTLY-ONE-choice case is eligible).
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="L2 MultiNV Submitted 404", approve=False,
    )
    await _set_choice_engine(pid, value=True)

    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 404, (
        f"Multi-NV profile at submitted must be blocked by the route gate, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )


@pytest.mark.asyncio
async def test_single_path_calculate_fee_at_submitted_still_ok(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Control for L2: a SINGLE-PATH profile (``uses_choice_engine=False`` — the
    fixture default) at ``submitted`` is still admitted (201). Confirms L2 only
    narrows multi-NV, not the single-path fast-track C2 opened.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="L2 SinglePath Submitted OK", approve=False,
    )
    # Assert the precondition explicitly so the control can't silently pass via
    # a future default flip.
    async with AsyncSessionLocal() as s:
        prof = (await s.execute(
            select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid)
        )).scalar_one()
        assert (
            prof.uses_choice_engine is False
        ), "fixture should default to single-path"

    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 201, (
        f"Single-path profile at submitted should still calculate fee, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )


@pytest.mark.asyncio
async def test_calculate_fee_at_resubmitted_ok(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Regression (prod profile 81, 2026-06-26): a profile the manager returned
    and the officer re-submitted lands in ``resubmitted`` — still pre-decision,
    still fee-eligible exactly like ``submitted`` (C2 fast-track prepay / giữ
    chỗ). Before the fix ``is_fee_eligible`` only matched the literal
    ``submitted`` so a re-submitted profile silently lost the "Tính học phí"
    button. Asserts BOTH gate sites that share ``is_fee_eligible``:
      * Site B — the FE ``calculate_fee`` permission flag,
      * Site A — the ``/api/fees/calculate`` route gate.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Resubmitted Calc OK", approve=False,
    )
    # Flip submitted → resubmitted directly (mirrors how the L2 tests mutate
    # state without driving the full reject → resubmit workflow). Single-path
    # so choices are irrelevant to the gate.
    await _set_choice_engine(pid, value=False, status="resubmitted")

    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert detail["status"] == "resubmitted", detail.get("status")
    assert detail["permissions"]["calculate_fee"] is True, detail["permissions"]
    assert "calculate_fee" in detail["available_actions"], detail["available_actions"]

    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 201, (
        f"Resubmitted profile should be fee-eligible like submitted, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )


@pytest.mark.asyncio
async def test_multi_nv_zero_choice_at_admitted_fails_closed(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """A multi-NV profile in an admitted-like state but with ZERO choices
    (corrupt data / direct flag flip) must FAIL CLOSED at fee creation (400) —
    the resolver refuses to price an undetermined ngành and must NOT silently
    fall back to the profile snapshot (offering_admission_config / applied_rules).

    Note: ``_create_approved_profile`` DOES leave a valid snapshot
    (offering_admission_config_id set at create), so a 201 here would mean the
    resolver used the stale NV-gốc snapshot — exactly the wrong-ngành bug. The
    state gate (is_fee_eligible) is choice-agnostic for admitted-like (a *real*
    admitted multi-NV has an admitted choice and resolves fine — covered by the
    resolver-picks-admitted-choice test in test_phase3_pr3d_b_choice_crud.py);
    the resolver is the safety net for the corrupt 0-choice case.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="L2 MultiNV ZeroChoice FailClosed", approve=False,
    )
    # Flip to multi-NV AND advance to an admitted-like decision state, WITHOUT
    # creating any choice — the corrupt/degenerate shape the resolver guards.
    await _set_choice_engine(pid, value=True, status="approved")

    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 400, (
        f"0-choice admitted multi-NV must fail closed at fee creation (no "
        f"snapshot fallback), got {resp.status_code}: {resp.text[:300]}"
    )


# ==============================================================================
# Follow-up #1/#2 — service-resolved pricing branches (base_amount=None path)
# ==============================================================================
# After the resolve-once refactor the router passes base_amount=None /
# discount_policy_ids=None and the SERVICE derives both under the lock. These
# two branches are prod-reachable but were uncovered (every other test passes an
# explicit base_amount → the legacy elif path).


@pytest.mark.asyncio
async def test_calculate_nontuition_fee_derives_base_from_academic_info(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """A NON-tuition fee via POST /api/fees/calculate exercises the service's
    ``base_amount=None`` → ``academic_info.tuition_fee_per_year`` derive branch
    (the router no longer pre-resolves base/discount). Locks that branch — no
    other test POSTs a non-tuition fee through this route.
    """
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="NonTuition Derive",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "enrollment",
            "installment_plan_code": "FULL",
        },
        headers=oh,
    )
    assert resp.status_code == 201, (
        f"non-tuition fee should derive base from academic_info, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    # academic_info.tuition_fee_per_year (5,000,000); no discount configured.
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("5000000"), body


@pytest.mark.asyncio
async def test_calculate_tuition_auto_derives_discount_from_academic_info(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Tuition via POST (``base_amount=None``) auto-derives ``discount_policy_ids``
    from the resolved academic_info under the lock. Seed a fixed 500k discount +
    link it to the ngành → the created fee must reflect ``total_discount>0``
    (final < base). Guards against the auto-derive silently returning ``[]`` (the
    discount vanishing from a tuition prepay).
    """
    from sqlalchemy import update as sa_update
    from app.models.tuition_discount_policy import TuitionDiscountPolicy

    ts = str(int(datetime.now().timestamp() * 1000) % 10**9)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            policy = TuitionDiscountPolicy(
                code=f"DISC_{ts}"[:50],
                name=f"Follow-up smoke discount {ts}",
                discount_type="amount",
                discount_value=Decimal("500000"),
                is_active=True,
                applicable_scope={},
                target_criteria={},
            )
            s.add(policy)
            await s.flush()
            ai_id = (await s.execute(
                select(models.OfferingAcademicInfo.id).where(
                    models.OfferingAcademicInfo.offering_id
                    == fee_calc_config["offering_id"]
                )
            )).scalar_one()
            await s.execute(
                sa_update(models.OfferingAcademicInfo)
                .where(models.OfferingAcademicInfo.id == ai_id)
                .values(applied_discount_policy_ids=[policy.id])
            )

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Discount Derive",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 201, (
        f"tuition with a linked discount policy should auto-derive it, got "
        f"{resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    # HK1 tuition 5,000,000 − fixed 500,000 = 4,500,000 (discount auto-derived
    # under the lock from the resolved academic_info).
    assert Decimal(str(body["total_discount"])) == Decimal("500000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("4500000"), body


# ==============================================================================
# Lịch thu "đóng trước" (Pha 1, 2026-06-29) — giãn lịch, GIỮ nguyên tổng học phí
# ==============================================================================
#
# collection_schedule_mode="down_payment": chia số PHẢI THU (final − waived)
# thành 2 hóa đơn (đợt đầu + phần còn lại) — KHÔNG đụng base_amount/final_amount.
# Canonical HK1 trong fee_calc_config = 5,000,000.


async def _link_fixed_discount(cfg: dict, amount: str = "500000") -> int:
    """Gắn 1 discount fixed cho academic_info của offering (mirror
    test_calculate_tuition_auto_derives_discount_from_academic_info). Trả policy id."""
    from app.models.tuition_discount_policy import TuitionDiscountPolicy
    from sqlalchemy import update as sa_update

    ts = str(int(datetime.now().timestamp() * 1000) % 10**9)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            policy = TuitionDiscountPolicy(
                code=f"MAN_{ts}"[:50],
                name=f"Manual test discount {ts}",
                discount_type="amount",
                discount_value=Decimal(amount),
                is_active=True,
                applicable_scope={},
                target_criteria={},
            )
            s.add(policy)
            await s.flush()
            pid = policy.id
            ai_id = (await s.execute(
                select(models.OfferingAcademicInfo.id).where(
                    models.OfferingAcademicInfo.offering_id == cfg["offering_id"]
                )
            )).scalar_one()
            await s.execute(
                sa_update(models.OfferingAcademicInfo)
                .where(models.OfferingAcademicInfo.id == ai_id)
                .values(applied_discount_policy_ids=[pid])
            )
    return pid


@pytest.mark.asyncio
async def test_tuition_preview_returns_canonical(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """GET /api/fees/tuition-preview trả giá chuẩn HK1 (5,000,000) cho owning
    officer; ngoài scope → 404."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Preview Canonical",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.get(
        "/api/fees/tuition-preview",
        params={"admission_profile_id": pid, "semester_no": 1},
        headers=oh,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["total_discount"])) == Decimal("0"), body
    assert Decimal(str(body["final_amount"])) == Decimal("5000000"), body
    assert body["semester_no"] == 1, body

    # Ngoài scope → 404 (profile không tồn tại).
    miss = await client.get(
        "/api/fees/tuition-preview",
        params={"admission_profile_id": 999999, "semester_no": 1},
        headers=oh,
    )
    assert miss.status_code == 404, miss.text


@pytest.mark.asyncio
async def test_tuition_preview_reflects_discount(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Preview phản ánh discount hiện hành: base 5,000,000 − 500,000 = 4,500,000."""
    await _link_fixed_discount(fee_calc_config, amount="500000")
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Preview WithDiscount",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.get(
        "/api/fees/tuition-preview",
        params={"admission_profile_id": pid, "semester_no": 1},
        headers=oh,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["total_discount"])) == Decimal("500000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("4500000"), body


@pytest.mark.asyncio
async def test_down_payment_splits_into_two_invoices(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Đóng trước 2,000,000 (canonical 5,000,000) → GIỮ tổng (base/final =
    5,000,000), 2 hóa đơn issued (2,000,000 + 3,000,000), còn nợ 3,000,000."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="DownPay Split",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "collection_schedule_mode": "down_payment",
            "down_payment": "2000000",
            "down_payment_due": "2026-09-01",
            "remainder_due": "2026-11-01",
        },
        headers=oh,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # NGHĨA VỤ không đổi (đóng trước chỉ giãn lịch thu).
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["remaining_amount"])) == Decimal("5000000"), body
    invoices = sorted(
        body.get("invoices") or [], key=lambda i: i["installment_no"]
    )
    assert len(invoices) == 2, invoices
    assert Decimal(str(invoices[0]["amount"])) == Decimal("2000000"), invoices
    assert Decimal(str(invoices[1]["amount"])) == Decimal("3000000"), invoices
    assert sum(Decimal(str(i["amount"])) for i in invoices) == Decimal("5000000")
    # Đợt 2 (phần còn lại = công nợ) có hạn tương lai cụ thể, cả 2 đã phát hành.
    assert invoices[0]["due_date"] == "2026-09-01", invoices
    assert invoices[1]["due_date"] == "2026-11-01", invoices
    assert all(i["status"] == "issued" for i in invoices), invoices


@pytest.mark.asyncio
async def test_down_payment_exceeds_total_rejected(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Đóng trước >= tổng phải thu (canonical 5,000,000) → 400 (remainder <= 0)."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="DownPay TooBig",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "collection_schedule_mode": "down_payment",
            "down_payment": "6000000",
            "down_payment_due": "2026-09-01",
            "remainder_due": "2026-11-01",
        },
        headers=oh,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_down_payment_remainder_due_before_first_422(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Hạn phần còn lại < hạn đợt đầu → schema model_validator → 422."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="DownPay BadDates",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "collection_schedule_mode": "down_payment",
            "down_payment": "2000000",
            "down_payment_due": "2026-11-01",
            "remainder_due": "2026-09-01",
        },
        headers=oh,
    )
    assert resp.status_code == 422, resp.text


# ==============================================================================
# Miễn/giảm học phí THẬT (Pha 2, 2026-06-29) — discount-line, GIẢM nghĩa vụ
# ==============================================================================
#
# "Học phí áp dụng" (target_final_amount) = final SAU MỌI giảm. Backend tính
# manual_discount = canonical − giảm-policy-sẵn-có − target → final == target;
# base_amount GIỮ canonical; ghi 1 FeeAppliedDiscount(policy_id=NULL) + snapshot
# source="manual_discount". Quyền admin/manager/accountant (field-level ở router);
# officer gửi → 403. Canonical HK1 trong fee_calc_config = 5,000,000.


async def _force_invoices_draft(fee_id: int):
    """Đưa hoá đơn của fee về ``draft``.

    ``POST /api/fees/calculate`` AUTO-ISSUE hoá đơn học phí, mà ``recalculate_fee``
    chặn khi có hoá đơn đã phát hành — nên muốn kiểm tra chính luồng tính lại thì
    phải qua cửa đó trước. (Test cũ không làm bước này nên nó "xanh" nhờ đúng
    guard hoá đơn, chứ chưa bao giờ chạm tới guard miễn/giảm mà nó tưởng đang
    kiểm.)"""
    from app.models.finance import Invoice
    from sqlalchemy import update as _update
    async with AsyncSessionLocal() as s:
        await s.execute(
            _update(Invoice)
            .where(Invoice.fee_id == fee_id)
            .values(status="draft", paid_at=None)
        )
        await s.commit()


async def _manual_discount_rows(pid: int):
    """Đọc các FeeAppliedDiscount của hồ sơ (để soát dòng giảm tay + snapshot)."""
    from app.models.finance import FeeAppliedDiscount, Fee
    from sqlalchemy import select as _select
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            _select(FeeAppliedDiscount)
            .join(Fee, Fee.id == FeeAppliedDiscount.fee_id)
            .where(Fee.admission_profile_id == pid)
        )).scalars().all()


@pytest.mark.asyncio
async def test_manual_discount_reduces_final_keeps_base(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """Accountant miễn/giảm (không policy): target 1,000,000 (canonical
    5,000,000) → base GIỮ 5,000,000, total_discount 4,000,000, final = target;
    invoice khớp final; 1 dòng giảm tay policy_id=NULL + snapshot
    source='manual_discount'."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="ManualDiscount Base", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "1000000",
            "manual_discount_reason": "Học bổng đặc biệt theo quyết định khen thưởng",
        },
        headers=ah,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["total_discount"])) == Decimal("4000000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("1000000"), body
    invoices = body.get("invoices") or []
    assert sum(Decimal(str(i["amount"])) for i in invoices) == Decimal("1000000"), invoices

    rows = await _manual_discount_rows(pid)
    manual = [r for r in rows if (r.calculation_snapshot or {}).get("source") == "manual_discount"]
    assert len(manual) == 1, [r.calculation_snapshot for r in rows]
    assert manual[0].policy_id is None
    assert Decimal(str(manual[0].discount_amount)) == Decimal("4000000")
    snap = manual[0].calculation_snapshot
    assert snap.get("approved_by") is not None, snap
    assert Decimal(snap["canonical_amount"]) == Decimal("5000000"), snap
    assert Decimal(snap["target_final_amount"]) == Decimal("1000000"), snap


@pytest.mark.asyncio
async def test_manual_discount_after_existing_policy(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """Có policy discount 500,000 + target 1,000,000 → manual = 5tr − 500k − 1tr
    = 3,500,000 (KHÔNG double-giảm); total_discount = 4,000,000; final = 1,000,000.
    'Học phí áp dụng' là final SAU MỌI giảm."""
    await _link_fixed_discount(fee_calc_config, amount="500000")
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="ManualDiscount Policy", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "1000000",
            "manual_discount_reason": "Giảm học phí theo quyết định nhà trường",
        },
        headers=ah,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(str(body["base_amount"])) == Decimal("5000000"), body
    assert Decimal(str(body["total_discount"])) == Decimal("4000000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("1000000"), body
    rows = await _manual_discount_rows(pid)
    manual = [r for r in rows if (r.calculation_snapshot or {}).get("source") == "manual_discount"]
    assert len(manual) == 1, [r.calculation_snapshot for r in rows]
    # manual = canonical − policy(500k) − target(1tr) = 3,500,000 (không phải 4tr).
    assert Decimal(str(manual[0].discount_amount)) == Decimal("3500000"), manual[0].calculation_snapshot
    assert Decimal(manual[0].calculation_snapshot["existing_policy_discount"]) == Decimal("500000")


@pytest.mark.asyncio
async def test_officer_cannot_manual_discount_403(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Officer gửi target_final_amount → 403 (field-level authz ở router). Officer
    vẫn calculate thường được (test khác)."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Officer NoDiscount",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "1000000",
            "manual_discount_reason": "Officer thử tự miễn giảm học phí",
        },
        headers=oh,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_manual_discount_target_not_below_net_400(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """target >= mức sau giảm hiện hành (no policy → canonical 5tr) → manual <= 0
    → 400 (không 'giảm' lên bằng/cao hơn)."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="ManualDiscount TooHigh", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "5000000",
            "manual_discount_reason": "Đặt bằng giá chuẩn - không hợp lệ",
        },
        headers=ah,
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_recalculate_preserves_manual_discount(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """Tính lại phí có miễn/giảm THỦ CÔNG → BẢO TOÀN nguyên số đã duyệt.

    Owner chốt 26-07 (Hướng A): giảm tay là quyết định của người cho một hoàn
    cảnh cụ thể — trường đổi giá không làm hoàn cảnh đó thay đổi, và máy không
    biết ý định gốc là "giảm 1 triệu" hay "giảm 13,7%". Bản cũ TỪ CHỐI tính lại
    (bắt hủy phí & tạo lại), lệch với luồng đổi giá học kỳ vốn giữ nguyên số.

    Canonical HK1 = 5.000.000 → giảm tay 4.000.000 để final = 1.000.000.
    Tính lại base xuống 4.500.000 ⇒ giảm tay GIỮ 4.000.000 ⇒ final = 500.000.
    (Ca giảm tay vượt base mới ⇒ bị cắt: khoá ở test thuần
    ``test_reprice_giam_tay_bi_cat_khi_vuot_base_moi`` — qua API không dựng được
    vì final=0 vi phạm ràng buộc hoá đơn phải > 0.)"""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="ManualDiscount Recalc", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    created = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "1000000",
            "manual_discount_reason": "Học bổng đặc biệt theo quyết định nhà trường",
        },
        headers=ah,
    )
    assert created.status_code == 201, created.text
    fee_id = created.json()["id"]
    base = Decimal(created.json()["base_amount"])

    # Tầng SERVICE (paid=0 nên không dính M10).
    await _force_invoices_draft(fee_id)
    from app.models.finance import Fee
    from app.services.fee_calculation_service import FeeCalculationService
    async with AsyncSessionLocal() as s:
        svc = FeeCalculationService(s)
        await svc.recalculate_fee(
            fee_id=fee_id,
            new_base_amount=Decimal("4500000"),
            reason="Điều chỉnh base test",
            user_id=1,
        )
        await s.commit()

    # Dòng giảm tay còn nguyên — KHÔNG bị bỏ rơi, KHÔNG rescale.
    rows = await _manual_discount_rows(pid)
    manual = [
        r for r in rows
        if (r.calculation_snapshot or {}).get("source") == "manual_discount"
    ]
    assert len(manual) == 1, "giảm tay phải được giữ, không bị bỏ rơi"
    assert manual[0].discount_amount == base - Decimal("1000000")
    async with AsyncSessionLocal() as s:
        refreshed = await s.get(Fee, fee_id)
        assert refreshed.base_amount == Decimal("4500000")
        assert refreshed.total_discount == base - Decimal("1000000")
        assert refreshed.final_amount == Decimal("500000")


@pytest.mark.asyncio
async def test_recalculate_manual_discount_kept_when_base_rises(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    accountant_same_unit: dict,
    fee_calc_config: dict,
):
    """Base TĂNG → giảm tay giữ NGUYÊN số, phần chênh thí sinh đóng thêm.

    Đây là ca nghiệp vụ chính của Hướng A: giảm 1.000.000 cho em A vẫn là
    1.000.000 sau khi trường tăng giá — không rescale theo tỷ lệ."""
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="ManualDiscount BaseUp", approve=False,
    )
    ah = await _login(
        client, accountant_same_unit["username"], accountant_same_unit["password"]
    )
    created = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "semester_no": 1,
            "target_final_amount": "1000000",
            "manual_discount_reason": "Học bổng đặc biệt theo quyết định nhà trường",
        },
        headers=ah,
    )
    assert created.status_code == 201, created.text
    fee_id = created.json()["id"]
    base = Decimal(created.json()["base_amount"])
    approved_manual = base - Decimal("1000000")

    await _force_invoices_draft(fee_id)
    from app.models.finance import Fee
    from app.services.fee_calculation_service import FeeCalculationService
    new_base = base + Decimal("2000000")
    async with AsyncSessionLocal() as s:
        svc = FeeCalculationService(s)
        await svc.recalculate_fee(
            fee_id=fee_id,
            new_base_amount=new_base,
            reason="Trường tăng học phí học kỳ",
            user_id=1,
        )
        await s.commit()

    rows = await _manual_discount_rows(pid)
    manual = [
        r for r in rows
        if (r.calculation_snapshot or {}).get("source") == "manual_discount"
    ]
    assert len(manual) == 1
    assert manual[0].discount_amount == approved_manual, "giảm tay KHÔNG rescale"
    assert "capped_from" not in (manual[0].calculation_snapshot or {})
    async with AsyncSessionLocal() as s:
        refreshed = await s.get(Fee, fee_id)
        # final = base mới − giảm tay giữ nguyên = 1.000.000 + 2.000.000
        assert refreshed.final_amount == Decimal("3000000")


# ==============================================================================
# QUYỀN CHỌN ƯU ĐÃI khi tính phí (owner chốt 26-07)
# ==============================================================================
# "Officer/kế toán chỉ được chọn TRONG TẬP đã cấu hình cho ngành." Trước đây
# router luôn truyền discount_policy_ids=None nên người dùng không có tiếng nói:
# hoặc áp hết cấu hình, hoặc không có cách nào bỏ một ưu đãi cụ thể.


async def _link_two_discounts(cfg: dict) -> tuple:
    """Gắn 2 chính sách CỘNG DỒN (400k + 600k) cho academic_info. Trả (id1, id2).

    ``is_stackable=True`` tường minh: cột default FALSE, mà engine tôn trọng cờ
    nên để mặc định thì chỉ chính sách ưu tiên cao nhất được áp.
    """
    from app.models.tuition_discount_policy import TuitionDiscountPolicy
    from sqlalchemy import update as sa_update

    ts = str(int(datetime.now().timestamp() * 1000) % 10**9)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            p1 = TuitionDiscountPolicy(
                code=f"SEL1_{ts}"[:50], name=f"Uu dai A {ts}",
                discount_type="amount", discount_value=Decimal("400000"),
                is_active=True, is_stackable=True, priority=2,
                applicable_scope={}, target_criteria={},
            )
            p2 = TuitionDiscountPolicy(
                code=f"SEL2_{ts}"[:50], name=f"Uu dai B {ts}",
                discount_type="amount", discount_value=Decimal("600000"),
                is_active=True, is_stackable=True, priority=1,
                applicable_scope={}, target_criteria={},
            )
            s.add_all([p1, p2])
            await s.flush()
            ids = (p1.id, p2.id)
            ai_id = (await s.execute(
                select(models.OfferingAcademicInfo.id).where(
                    models.OfferingAcademicInfo.offering_id == cfg["offering_id"]
                )
            )).scalar_one()
            await s.execute(
                sa_update(models.OfferingAcademicInfo)
                .where(models.OfferingAcademicInfo.id == ai_id)
                .values(applied_discount_policy_ids=list(ids))
            )
    return ids


@pytest.mark.asyncio
async def test_preview_liet_ke_uu_dai_cua_nganh(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Preview trả DANH SÁCH ưu đãi đã cấu hình + số tiền từng cái, mặc định áp
    hết. Giao diện dựng ô tích từ đây nên danh sách và con số phải cùng một lượt
    gọi — hai nguồn thì sớm muộn cũng lệch."""
    p1, p2 = await _link_two_discounts(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Preview Policy List",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.get(
        "/api/fees/tuition-preview",
        params={"admission_profile_id": pid, "semester_no": 1},
        headers=oh,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(str(body["total_discount"])) == Decimal("1000000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("4000000"), body

    options = {opt["id"]: opt for opt in body["discount_policies"]}
    assert set(options) == {p1, p2}
    assert all(opt["selectable"] for opt in options.values())
    assert all(opt["selected"] for opt in options.values())
    assert Decimal(str(options[p1]["amount"])) == Decimal("400000")
    assert Decimal(str(options[p2]["amount"])) == Decimal("600000")


@pytest.mark.asyncio
async def test_preview_theo_lua_chon_va_bo_tich_het(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Số xem trước bám ĐÚNG ô đang tích — kể cả khi bỏ tích HẾT.

    Query string không phân biệt "không gửi" với "mảng rỗng", nên bỏ tích hết mà
    thiếu cờ tường minh thì server hiểu nhầm là "áp tất cả": người dùng thấy vẫn
    giảm, bấm Tính phí lại ra số khác."""
    p1, _p2 = await _link_two_discounts(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Preview Policy Pick",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    chon_mot = await client.get(
        "/api/fees/tuition-preview",
        params={
            "admission_profile_id": pid,
            "semester_no": 1,
            "discount_policy_ids": [p1],
            "explicit_discount_selection": True,
        },
        headers=oh,
    )
    assert chon_mot.status_code == 200, chon_mot.text
    assert Decimal(str(chon_mot.json()["total_discount"])) == Decimal("400000")

    bo_het = await client.get(
        "/api/fees/tuition-preview",
        params={
            "admission_profile_id": pid,
            "semester_no": 1,
            "explicit_discount_selection": True,
        },
        headers=oh,
    )
    assert bo_het.status_code == 200, bo_het.text
    assert Decimal(str(bo_het.json()["total_discount"])) == Decimal("0")
    assert Decimal(str(bo_het.json()["final_amount"])) == Decimal("5000000")
    # Danh sách VẪN hiện đủ để tích lại, chỉ khác cờ selected.
    assert len(bo_het.json()["discount_policies"]) == 2
    assert not any(o["selected"] for o in bo_het.json()["discount_policies"])


@pytest.mark.asyncio
async def test_calculate_chi_ap_uu_dai_duoc_chon(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Tính phí chỉ áp ưu đãi được tích + đóng dấu ai đã chọn vào snapshot."""
    p1, p2 = await _link_two_discounts(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Policy Pick",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [p2],
        },
        headers=oh,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(str(body["total_discount"])) == Decimal("600000"), body
    assert Decimal(str(body["final_amount"])) == Decimal("4400000"), body

    rows = await _manual_discount_rows(pid)
    assert [r.policy_id for r in rows] == [p2], "chi ghi dong cua uu dai da chon"
    assert (rows[0].calculation_snapshot or {}).get("selected_by") is not None, (
        "phai truy duoc ai quyet dinh ap uu dai nay"
    )
    assert p1 not in [r.policy_id for r in rows]


@pytest.mark.asyncio
async def test_calculate_bo_het_uu_dai_thi_thu_du(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Mảng RỖNG = chọn không áp ưu đãi nào (khác hẳn "không gửi gì")."""
    await _link_two_discounts(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Policy None",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [],
        },
        headers=oh,
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(str(resp.json()["total_discount"])) == Decimal("0")
    assert Decimal(str(resp.json()["final_amount"])) == Decimal("5000000")


@pytest.mark.asyncio
async def test_calculate_tu_choi_uu_dai_ngoai_cau_hinh(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Chọn chính sách NGOÀI cấu hình của ngành → 400 có chữ, KHÔNG lọc im lặng.

    Lọc im lặng nghĩa là người dùng tưởng đã giảm mà hoá đơn thì không — mất
    niềm tin vào con số nhanh hơn bất kỳ lỗi nào khác."""
    ngoai_cau_hinh = await _link_fixed_discount(fee_calc_config, amount="123000")
    p1, _p2 = await _link_two_discounts(fee_calc_config)  # ghi de cau hinh nganh
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Policy Outside",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [p1, ngoai_cau_hinh],
        },
        headers=oh,
    )
    assert resp.status_code == 400, resp.text
    assert "không nằm trong cấu hình" in resp.json()["detail"]


# ==============================================================================
# BLOCKER P1-2 — ô tích KHÔNG được hứa một ưu đãi mà engine sẽ bỏ
# ==============================================================================
# ``is_stackable`` mặc định FALSE ở CSDL. Hai ưu đãi cùng gắn cho ngành mà cái
# ưu tiên cao không cộng dồn ⇒ engine chỉ áp MỘT. Nếu màn hình vẫn hiện hai ô
# tích thì tổng tiền bên dưới trông như tính sai.


async def _link_non_stackable_pair(cfg: dict) -> tuple:
    """Gắn 2 chính sách: A KHÔNG cộng dồn (ưu tiên cao) + B cộng dồn. Trả (A, B)."""
    from app.models.tuition_discount_policy import TuitionDiscountPolicy
    from sqlalchemy import update as sa_update

    ts = str(int(datetime.now().timestamp() * 1000) % 10**9)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            a = TuitionDiscountPolicy(
                code=f"NST_A_{ts}"[:50], name=f"Uu dai doc quyen {ts}",
                discount_type="amount", discount_value=Decimal("400000"),
                is_active=True, is_stackable=False, priority=10,
                applicable_scope={}, target_criteria={},
            )
            b = TuitionDiscountPolicy(
                code=f"NST_B_{ts}"[:50], name=f"Uu dai cong don {ts}",
                discount_type="amount", discount_value=Decimal("600000"),
                is_active=True, is_stackable=True, priority=1,
                applicable_scope={}, target_criteria={},
            )
            s.add_all([a, b])
            await s.flush()
            ids = (a.id, b.id)
            ai_id = (await s.execute(
                select(models.OfferingAcademicInfo.id).where(
                    models.OfferingAcademicInfo.offering_id == cfg["offering_id"]
                )
            )).scalar_one()
            await s.execute(
                sa_update(models.OfferingAcademicInfo)
                .where(models.OfferingAcademicInfo.id == ai_id)
                .values(applied_discount_policy_ids=list(ids))
            )
    return ids


@pytest.mark.asyncio
async def test_preview_phan_biet_da_tich_voi_thuc_su_duoc_ap(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Ưu đãi bị chính sách KHÔNG cộng dồn chặn: vẫn ``selected`` nhưng
    ``applied=False`` + có lý do tiếng Việt. Tổng phải khớp phần THỰC SỰ áp."""
    a, b = await _link_non_stackable_pair(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Preview NonStackable",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.get(
        "/api/fees/tuition-preview",
        params={"admission_profile_id": pid, "semester_no": 1},
        headers=oh,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Chỉ A được áp ⇒ tổng đúng 400k, KHÔNG phải 1tr.
    assert Decimal(str(body["total_discount"])) == Decimal("400000"), body

    options = {o["id"]: o for o in body["discount_policies"]}
    assert options[a]["selected"] is True and options[a]["applied"] is True
    assert options[b]["selected"] is True, "người dùng vẫn đang tích B"
    assert options[b]["applied"] is False, (
        "B không được engine áp — cờ hiển thị phải nói đúng sự thật"
    )
    assert options[b]["reason"] == "bi_chan_boi_chinh_sach_khong_cong_don"
    assert "cộng dồn" in (options[b]["reason_text"] or "")


@pytest.mark.asyncio
async def test_calculate_khop_so_preview_khi_co_chinh_sach_khong_cong_don(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Số thật khi tạo phí phải bằng số xem trước (chỉ áp A)."""
    a, b = await _link_non_stackable_pair(fee_calc_config)
    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc NonStackable",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [a, b],
        },
        headers=oh,
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(str(resp.json()["total_discount"])) == Decimal("400000")
    rows = await _manual_discount_rows(pid)
    assert [r.policy_id for r in rows] == [a]


# ==============================================================================
# BLOCKER P1-3 — lựa chọn TƯỜNG MINH phải fail-closed khi ưu đãi hết hiệu lực
# ==============================================================================
# Người dùng chọn dựa trên màn hình xem trước; giữa lúc xem với lúc bấm có thể có
# người tắt chính sách. Im lặng bỏ qua ⇒ phí VẪN tạo thành công nhưng CAO HƠN số
# họ vừa nhìn thấy — sai lệch tiền im lặng, khó phát hiện nhất.


async def _set_policy(policy_id: int, **values) -> None:
    from app.models.tuition_discount_policy import TuitionDiscountPolicy
    from sqlalchemy import update as sa_update

    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                sa_update(TuitionDiscountPolicy)
                .where(TuitionDiscountPolicy.id == policy_id)
                .values(**values)
            )


@pytest.mark.asyncio
async def test_calculate_tu_choi_uu_dai_vua_bi_TAT(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Preview cũ + chính sách vừa bị tắt ⇒ 400, KHÔNG tạo phí với số cao hơn."""
    p1, _p2 = await _link_two_discounts(fee_calc_config)
    await _set_policy(p1, is_active=False)

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Stale Disabled",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [p1],
        },
        headers=oh,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "ngừng hoạt động" in detail, detail
    assert "tải lại" in detail, "phải chỉ đường cho người dùng"


@pytest.mark.asyncio
async def test_calculate_tu_choi_uu_dai_da_HET_HAN(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Chính sách còn ``is_active`` nhưng đã quá ``valid_to`` ⇒ 400 với đúng lý do."""
    from datetime import date as _date, timedelta as _timedelta

    p1, _p2 = await _link_two_discounts(fee_calc_config)
    await _set_policy(p1, valid_to=_date.today() - _timedelta(days=1))

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Stale Expired",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
            "discount_policy_ids": [p1],
        },
        headers=oh,
    )
    assert resp.status_code == 400, resp.text
    assert "hết hạn" in resp.json()["detail"], resp.json()["detail"]


@pytest.mark.asyncio
async def test_khong_chon_gi_thi_uu_dai_het_han_chi_bi_BO_QUA_khong_chan(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    fee_calc_config: dict,
):
    """Không nêu ý kiến (áp theo cấu hình) thì ưu đãi hết hạn chỉ bị bỏ qua.

    Fail-closed chỉ dành cho lựa chọn TƯỜNG MINH — nếu chặn cả đường mặc định thì
    một chính sách hết hạn trong cấu hình sẽ khoá luôn việc tạo phí của cả ngành."""
    from datetime import date as _date, timedelta as _timedelta

    p1, p2 = await _link_two_discounts(fee_calc_config)
    await _set_policy(p1, valid_to=_date.today() - _timedelta(days=1))

    pid = await _create_approved_profile(
        client, admin_token_headers, officer_user_in_db, fee_calc_config,
        lead_name="Calc Default Expired",
    )
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=oh,
    )
    assert resp.status_code == 201, resp.text
    # Chỉ p2 (600k) được áp; p1 hết hạn bị bỏ qua.
    assert Decimal(str(resp.json()["total_discount"])) == Decimal("600000")
    rows = await _manual_discount_rows(pid)
    assert [r.policy_id for r in rows] == [p2]
