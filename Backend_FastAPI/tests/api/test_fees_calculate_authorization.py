"""Officer-scoped POST /api/fees/calculate authorization (PR #7).

Matrix:
* owning officer on approved profile → 201
* officer on same-unit profile they don't own → 404 (IDOR convention)
* officer on draft profile they own → 404 (status gate)
* admin on any profile → 201
* manager on same-unit profile → 201
* accountant on cross-unit profile → 404

The 4 permission points are asserted via ``available_actions`` on
``GET /admissions/{id}``; the full end-to-end fee creation is
exercised only for the happy-path owning-officer case since the
downstream fee service is unit-tested elsewhere.
"""
from __future__ import annotations

from datetime import datetime

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
# decision. Quyền giữ nguyên: officer phụ trách + manager/accountant cùng unit.


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
