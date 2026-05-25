# tests/api/test_admission_workflow_api.py
"""
API-LEVEL TESTS: Admission Profile Workflow Contract

14 tests covering:
- Happy path: submit → approve → override → finalize → enrolled
- Recovery: submit → reject → resubmit → revision → resubmit → approve
- Invalid transition: approved → finalize blocked (400)
- RBAC: officer cannot approve/request-revision/override/finalize (403)
- Optimistic locking: stale version (400/409)
- Drop: enrolled → drop (is_dropped=True), drop before enrolled (400)

IMPORTANT: Uses _login() re-login pattern before every user context switch
to handle shared httpx cookie jar (see blocker analysis in conversation).

Run: pytest tests/api/test_admission_workflow_api.py -v
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal

try:
    from tests.fixtures.constants import AuthURLs, LeadsURLs, TestUsers
except ImportError:
    pytest.fail("Could not import from tests.fixtures.constants")

pytestmark = pytest.mark.integration

# =============================================================================
# URLs + Helpers
# =============================================================================

ADMISSIONS = "/api/admissions"


def ADM(pid: int) -> str:
    return f"{ADMISSIONS}/{pid}"


def ACT(pid: int, action: str) -> str:
    return f"{ADMISSIONS}/{pid}/{action}"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """Re-login to refresh shared cookie jar. Returns headers."""
    res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return {"Authorization": f"Bearer {res.cookies.get('access_token')}"}


async def _admin(client: AsyncClient) -> dict:
    return await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])


async def _officer(client: AsyncClient, user: dict) -> dict:
    return await _login(client, user["username"], user["password"])


async def _ver(client: AsyncClient, h: dict, pid: int) -> int:
    """Get current profile version."""
    return (await client.get(ADM(pid), headers=h)).json()["version"]


async def _submit(
    client: AsyncClient,
    h: dict,
    lead_id: int,
    method_id: int,
    *,
    admission_round_id: int,
    academic_year: int = 2026,
    school_id: int | None = None,
) -> dict:
    """Add consultation + create profile + fill + upload docs + submit.

    Q9 #07 Phase E.4 contract: caller must pass ``school_id`` (from
    ``adm_config["school_id"]``) so the academic_history entry resolves
    through ``vn_school_kv_assignment`` and submit transitions to
    ``submitted`` rather than aggregating ``KV_UNRESOLVED`` into
    ``validation_errors``. Optional default kept for backward-compat with
    fixtures that haven't been migrated yet.
    """
    # Consultation required before admission (business rule)
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    status_id = INITIAL_LEAD_STATUS_ID
    await client.post(f"{LeadsURLs.LEADS}/{lead_id}/consultations", json={
        "status_id": status_id, "method": "phone", "notes": "Pre-admission consultation",
    }, headers=h)

    r = await client.post(ADMISSIONS, json={
        "lead_id": lead_id,
        "admission_method_id": method_id,
        "admission_round_id": admission_round_id,
        "academic_year": academic_year,
    }, headers=h)
    assert r.status_code in [200, 201], f"Create: {r.text}"
    p = r.json()
    pid, v = p["id"], p["version"]

    cid = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    # Phase E.4: academic_history entry must include ``school_id`` + ``level``
    # so the engine LICH_SU_THPT branch (cultural=graduated_thpt + target=
    # cao_dang) hits a vn_school_kv_assignment row and resolves to a KV code.
    academic_entry: dict = {
        "school_name": "THPT",
        "year_from": 2019,
        "year_to": 2022,
        "gpa": 8.0,
        "graduation_type": "THPT",
        "level": "THPT",
        "grade_to": 12,
    }
    if school_id is not None:
        academic_entry["school_id"] = school_id

    ur = await client.put(ADM(pid), json={
        "version": v, "citizen_id": cid, "gender": "male", "dob": "2001-01-01",
        "nationality": "Viet Nam", "ethnicity": "Kinh", "place_of_birth": "Test",
        "family_info": [{"relationship": "Cha", "full_name": "P", "phone": "0901111111", "is_primary_guardian": True}],
        "academic_history": [academic_entry],
        "admission_scores": {"gpa": 8.0, "subject_scores": {}},
        # Q9 #07 Phase E.4 — submit gate eligibility: CD chính quy yêu cầu
        # THPT knowledge (TN_THPT hoặc HOAN_THANH_THPT). Fixture adm_config
        # seed MAJOR_1.degree_level_id → ConfigDegreeLevel("cao_dang") +
        # ProgramOffering.offering_type_id → ConfigOfferingType("chinh_quy")
        # → engine derive target_level="cao_dang"/admission_type="chinh_quy"
        # → validate_eligibility(profile, "cao_dang", "chinh_quy") cần
        # cultural in {"completed_thpt","graduated_thpt","graduated_gdtx"}.
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
    }, headers=h)
    if ur.status_code == 200:
        v = ur.json()["version"]

    fresh = (await client.get(ADM(pid), headers=h)).json()
    v = fresh.get("version", v)
    for doc in fresh.get("documents_checklist", []):
        if doc.get("is_mandatory") and doc.get("status") == "missing":
            await client.post(
                f"{ADM(pid)}/documents/{doc['code']}/upload", headers=h,
                files={"file": (f"{doc['code']}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
                data={"actual_submission_format": "photo"},
            )

    v = (await client.get(ADM(pid), headers=h)).json()["version"]
    sr = await client.post(ACT(pid, "submit"), json={"version": v}, headers=h)
    sr_body = sr.json()
    if sr.status_code != 200 or sr_body.get("status") != "submitted":
        profile_debug = (await client.get(ADM(pid), headers=h)).json()
        raise AssertionError(
            f"Submit failed ({sr.status_code}): {sr.text[:300]}\n"
            f"  eligibility: {profile_debug.get('eligibility_status')}\n"
            f"  validation_errors: {profile_debug.get('validation_errors', [])[:3]}\n"
            f"  docs: {[(d['code'], d['status']) for d in profile_debug.get('documents_checklist', [])]}"
        )
    # Submit may return {status, message} not full profile — re-fetch
    return (await client.get(ADM(pid), headers=h)).json()


async def _fast_enroll(client: AsyncClient, pid: int):
    """Approve → override → finalize (all as admin, re-login each step)."""
    ah = await _admin(client)
    v = await _ver(client, ah, pid)
    await client.post(ACT(pid, "approve"), json={"notes": "OK", "version": v}, headers=ah)
    ah = await _admin(client)
    v = await _ver(client, ah, pid)
    await client.post(ACT(pid, "override"), json={"reason": "E2E override for enrollment test", "version": v}, headers=ah)
    ah = await _admin(client)
    v = await _ver(client, ah, pid)
    await client.post(ACT(pid, "finalize"), json={"version": v}, headers=ah)


# =============================================================================
# Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def adm_config(seed_lead_dependencies: dict):
    """Seed admission config chain for tests.

    Phase E.4 (Q9 #07) — submit gate (admission_service._validate_eligibility_
    all_choices legacy branch) requires the legacy single-path chain expose:
      profile.offering_admission_config_id
        → config.academic_info → offering → program.degree_level_ref.code
                                          → offering_type_config.code

    The chain must resolve to GDNN-scope codes ({"cao_dang"/"trung_cap"/
    "so_cap"} for degree, any non-null for offering_type) and the profile
    must declare cultural_education_level compatible with the target level,
    or submit fail-closes with CONFIG_GAP_TARGET_LEVEL (yêu cầu nghiệp vụ #5).

    Pre-Phase-E.4 this fixture seeded only ProgramOffering with timestamp-
    suffixed ConfigOfferingType + a MajorProgram (MAJOR_1) with legacy text
    ``degree_level`` and NULL ``degree_level_id``, plus NO OfferingAdmission
    Config row. After Phase E.4 every submit raised CONFIG_GAP_TARGET_LEVEL.

    Fix scope (tests only — no production logic change):
      1. Get-or-create canonical ConfigDegreeLevel("cao_dang") and link
         MAJOR_1 ``degree_level_id`` to it.
      2. Use canonical ConfigOfferingType("chinh_quy") instead of ts-suffix
         so admission_type is well-defined for validate_eligibility().
      3. Seed OfferingAdmissionConfig(academic_info_id, criteria_id) so
         admission_service.create_profile auto-populates
         profile.offering_admission_config_id at step 14b.
      The _submit() helper now sends cultural_education_level=
      "graduated_thpt" + vocational_qualification="none" so submit-time
      eligibility passes for the CD chính quy target.
    """
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp())}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Canonical ConfigDegreeLevel — code MUST be one of GDNN scope
            # ("cao_dang"/"trung_cap"/"so_cap") for Phase E.4 derive helper.
            # Get-or-create to tolerate cross-fixture seeding within the
            # same test (DB truncates between tests, so within one test
            # this row is only inserted once).
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

            # Canonical ConfigOfferingType "chinh_quy" — admission_type code
            # read by derive_target_level_and_type. Get-or-create so that
            # multiple test modules sharing the same DB-truncate cycle can
            # both seed without UNIQUE-constraint collisions.
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

            # Backfill MAJOR_1.degree_level_id (seed_lead_dependencies seeds
            # only the legacy text column). NULL → derive_target_level_and_
            # _type raises CONFIG_GAP_TARGET_LEVEL pointing at MajorProgram.
            major = (await s.execute(
                select(models.MajorProgram).where(
                    models.MajorProgram.id == mpid
                )
            )).scalar_one()
            if major.degree_level_id is None:
                major.degree_level_id = cdl.id
                await s.flush()

            dt = models.ConfigDocumentType(code=f"tcc_{ts}", name=f"TCC_{ts}", display_order=1)
            s.add(dt); await s.flush()
            po = models.ProgramOffering(offering_type=f"TQ_{ts}", program_id=mpid, offering_type_id=cot.id, is_active=True, duration_semesters=6)
            s.add(po); await s.flush()
            ai = models.OfferingAcademicInfo(offering_id=po.id, academic_year=2026, tuition_fee_per_year=5000000, annual_admission_quota=100, is_published=True)
            s.add(ai); await s.flush()
            am = models.AdmissionMethod(code=f"hb_{ts}", name=f"HB_{ts}", requires_gpa=True, requires_subject_scores=False, is_active=True)
            s.add(am); await s.flush()
            ac = models.AdmissionCriteria(method_id=am.id, code=f"TC_{ts}", name=f"TC_{ts}", min_gpa=6.0, scoring_method="average", subject_selection_mode="fixed", policy_version="2026.1", is_active=True)
            s.add(ac); await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(academic_info_id=ai.id, admission_method_id=am.id, admission_round_id=round_id, criteria_id=ac.id, status="active", display_name="Test", display_order=0, visibility="public")
            s.add(ap); await s.flush()

            # OfferingAdmissionConfig — link academic_info + criteria so that
            # admission_service.create_profile step 14b auto-populates
            # profile.offering_admission_config_id (lookup at lines 3294-3306).
            # Without this row, profile.offering_admission_config_id stays
            # NULL → submit gate fail-closed CONFIG_GAP_TARGET_LEVEL.
            oac = models.OfferingAdmissionConfig(
                academic_info_id=ai.id,
                criteria_id=ac.id,
                is_active=True,
            )
            s.add(oac); await s.flush()

            # Phase E.4 KV resolution catalog — submit gate aggregates
            # ``KV_UNRESOLVED`` into validation_errors when academic_history
            # entries don't resolve to a KV via vn_school_kv_assignment OR
            # commune lookup. For cultural="graduated_thpt" + target=cao_dang
            # the engine routes LICH_SU_THPT (multi-school rule), so seed
            # one VnSchool + KV assignment covering the candidate's THPT
            # years and pass ``school_id`` into the academic_history entry
            # via _submit() helper. Without this, submit returns status=
            # "draft" + validation_errors=["KV_UNRESOLVED (insufficient_data)..."]
            # rather than transitioning to "submitted".
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
                school_id=sch.id,
                kv_code="KV3",
                effective_from_year=2019,
                effective_to_year=2022,
                source="manual_admin",
            )
            s.add(kva); await s.flush()
            school_id = sch.id
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "school_id": school_id,
        # Round contract hardening (plan v4): create-profile now requires
        # admission_round_id; expose the seeded DOT_1 round so _submit can
        # thread it into the POST payload.
        "round_id": round_id,
    }


@pytest_asyncio.fixture
async def adm_lead(client: AsyncClient, admin_token_headers: dict, officer_user_in_db: dict, adm_config: dict):
    """Create lead assigned to officer with offering."""
    r = await client.post(LeadsURLs.LEADS, json={
        "full_name": "Adm Lead", "phone": f"099{int(datetime.now().timestamp()) % 10000000:07d}",
        "source": "website", "unit_id": adm_config["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"], "offering_id": adm_config["offering_id"],
    }, headers=admin_token_headers)
    assert r.status_code == 201, f"Lead: {r.text}"
    return r.json()


# =============================================================================
# TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_submit_approve_override_finalize_enrolled(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    assert p["status"] == "submitted"
    pid = p["id"]

    ah = await _admin(client); v = await _ver(client, ah, pid)
    r = await client.post(ACT(pid, "approve"), json={"notes": "OK", "version": v}, headers=ah)
    assert r.status_code == 200, f"Approve failed ({r.status_code}): {r.text[:300]}"
    assert r.json()["status"] == "approved"

    ah = await _admin(client); v = await _ver(client, ah, pid)
    r = await client.post(ACT(pid, "override"), json={"reason": "E2E test override for enrollment flow", "version": v}, headers=ah)
    assert r.status_code == 200, f"Override failed ({r.status_code}): {r.text[:300]}"
    assert r.json()["status"] == "overridden"

    ah = await _admin(client); v = await _ver(client, ah, pid)
    r = await client.post(ACT(pid, "finalize"), json={"version": v}, headers=ah)
    assert r.status_code == 200, f"Finalize failed ({r.status_code}): {r.text[:300]}"
    assert r.json()["status"] == "enrolled"


@pytest.mark.asyncio
async def test_submit_reject_resubmit_revision_resubmit_approve(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    pid = p["id"]

    ah = await _admin(client); v = await _ver(client, ah, pid)
    assert (await client.post(ACT(pid, "reject"), json={"reason": "Documents insufficient for admission", "version": v}, headers=ah)).json()["status"] == "rejected"

    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, pid)
    assert (await client.post(ACT(pid, "resubmit"), json={"notes": "Fixed", "version": v}, headers=oh)).json()["status"] == "resubmitted"

    ah = await _admin(client); v = await _ver(client, ah, pid)
    assert (await client.post(ACT(pid, "request-revision"), json={"reason": "Missing cert add it please", "version": v}, headers=ah)).json()["status"] == "revision_requested"

    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, pid)
    assert (await client.post(ACT(pid, "resubmit"), json={"notes": "Added", "version": v}, headers=oh)).json()["status"] == "resubmitted"

    ah = await _admin(client); v = await _ver(client, ah, pid)
    assert (await client.post(ACT(pid, "approve"), json={"notes": "Good", "version": v}, headers=ah)).json()["status"] == "approved"


@pytest.mark.asyncio
async def test_finalize_from_approved_returns_400(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    pid = p["id"]

    ah = await _admin(client); v = await _ver(client, ah, pid)
    await client.post(ACT(pid, "approve"), json={"notes": "OK", "version": v}, headers=ah)

    ah = await _admin(client); v = await _ver(client, ah, pid)
    r = await client.post(ACT(pid, "finalize"), json={"version": v}, headers=ah)
    assert r.status_code == 400
    d = r.json().get("detail", "").lower()
    assert "transition" in d or "invalid" in d or "chuyển" in d


@pytest.mark.asyncio
async def test_officer_cannot_approve(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    assert (await client.post(ACT(p["id"], "approve"), json={"notes": "No", "version": v}, headers=oh)).status_code == 403


@pytest.mark.asyncio
async def test_officer_cannot_request_revision(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    assert (await client.post(ACT(p["id"], "request-revision"), json={"reason": "Officer trying revision test reason", "version": v}, headers=oh)).status_code == 403


@pytest.mark.asyncio
async def test_officer_cannot_override(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "approve"), json={"notes": "OK", "version": v}, headers=ah)
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    assert (await client.post(ACT(p["id"], "override"), json={"reason": "Officer override attempt denied", "version": v}, headers=oh)).status_code == 403


@pytest.mark.asyncio
async def test_officer_cannot_finalize(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "approve"), json={"notes": "OK", "version": v}, headers=ah)
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "override"), json={"reason": "E2E override for enrollment test", "version": v}, headers=ah)
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    assert (await client.post(ACT(p["id"], "finalize"), json={"version": v}, headers=oh)).status_code == 403


@pytest.mark.asyncio
async def test_approve_stale_version(client, officer_user_in_db, adm_lead, adm_config):
    """Approve with stale version returns 409 (ConflictError)."""
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    ah = await _admin(client); stale = await _ver(client, ah, p["id"])
    # Reject to change version while keeping profile in a state where approve is valid later
    await client.post(ACT(p["id"], "reject"), json={"reason": "Reject to bump version for test", "version": stale}, headers=ah)
    # Resubmit so we're back in a state where approve is valid (resubmitted → approved)
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    await client.post(ACT(p["id"], "resubmit"), json={"notes": "Resubmit for stale test", "version": v}, headers=oh)
    # Approve with stale version from submitted era — transition valid but version wrong
    ah = await _admin(client)
    r = await client.post(ACT(p["id"], "approve"), json={"notes": "Stale approve", "version": stale}, headers=ah)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_request_revision_stale_version(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    # Get stale version at submitted state
    ah = await _admin(client); stale = await _ver(client, ah, p["id"])
    # Reject to change version (submitted → rejected is valid)
    await client.post(ACT(p["id"], "reject"), json={"reason": "Reject to bump version for test", "version": stale}, headers=ah)
    # Resubmit (officer) to get back to a state where request-revision is valid
    oh = await _officer(client, officer_user_in_db); v = await _ver(client, oh, p["id"])
    await client.post(ACT(p["id"], "resubmit"), json={"notes": "Resubmit", "version": v}, headers=oh)
    # Now request-revision with stale version from submitted era
    ah = await _admin(client)
    r = await client.post(ACT(p["id"], "request-revision"), json={"reason": "Stale revision test reason here", "version": stale}, headers=ah)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_resubmit_stale_version(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    # Reject first
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "reject"), json={"reason": "Documents insufficient for admission", "version": v}, headers=ah)
    # Get stale version at rejected state
    oh = await _officer(client, officer_user_in_db); stale = await _ver(client, oh, p["id"])
    # Resubmit with correct version
    await client.post(ACT(p["id"], "resubmit"), json={"notes": "1st", "version": stale}, headers=oh)
    # Reject again to get back to rejectable state
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "reject"), json={"reason": "Reject again for stale test", "version": v}, headers=ah)
    # Resubmit with stale version (from first rejected state)
    oh = await _officer(client, officer_user_in_db)
    r = await client.post(ACT(p["id"], "resubmit"), json={"notes": "Stale attempt", "version": stale}, headers=oh)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_drop_stale_version(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    await _fast_enroll(client, p["id"])
    ah = await _admin(client); stale = await _ver(client, ah, p["id"])
    async with AsyncSessionLocal() as s:
        async with s.begin():
            pr = (await s.execute(select(models.AdmissionProfile).where(models.AdmissionProfile.id == p["id"]))).scalar_one()
            pr.version += 1
    ah = await _admin(client)
    r = await client.post(ACT(p["id"], "drop"), json={"reason": "Stale drop test reason text here", "version": stale}, headers=ah)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
async def test_drop_enrolled_sets_is_dropped(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    await _fast_enroll(client, p["id"])
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    r = await client.post(ACT(p["id"], "drop"), json={"reason": "Student left for personal reasons text", "version": v}, headers=ah)
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "enrolled" and b["is_dropped"] is True
    assert b.get("dropped_reason") is not None and b.get("dropped_by_id") is not None


@pytest.mark.asyncio
async def test_drop_before_enrolled_returns_400(client, officer_user_in_db, adm_lead, adm_config):
    oh = await _officer(client, officer_user_in_db)
    p = await _submit(client, oh, adm_lead["id"], adm_config["method_id"], admission_round_id=adm_config["round_id"], school_id=adm_config["school_id"])
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    await client.post(ACT(p["id"], "approve"), json={"notes": "OK", "version": v}, headers=ah)
    ah = await _admin(client); v = await _ver(client, ah, p["id"])
    assert (await client.post(ACT(p["id"], "drop"), json={"reason": "Should fail not enrolled reason", "version": v}, headers=ah)).status_code == 400
