"""ADM-017 — verify create_profile binds to the correct
``OfferingAcademicInfo`` row when client passes ``academic_year``.

Q8=b decision (memory ``project_admission_audit_2026-04-27_wave_status``):
client must pass academic_year on profile creation. This BE phase
makes the field optional for backward compat — strict-required will
flip in a follow-up after FE catches up — but **when passed it must
be honoured strictly**: lookup the matching
``(offering_id, academic_year)`` ``OfferingAcademicInfo`` row, reject
if not found, reject if not published.

When ``academic_year`` is omitted, fall back to "first published" so
legacy FE callers don't break mid-rollout.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(
        AuthURLs.LOGIN, data={"username": username, "password": password}
    )
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def multi_year_offering(seed_lead_dependencies: dict):
    """Seed an offering that has TWO academic years: 2025 (published)
    + 2026 (published). The default-pick-first-published logic could
    silently bind to either; this test forces the contract by passing
    academic_year explicitly.

    Plus a third year 2027 that is NOT published — so we can exercise
    the "year exists but not published" rejection path.
    """
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(
                code=f"tq_{ts}", name=f"TQ_{ts}", display_order=1
            )
            s.add(ot)
            await s.flush()
            po = models.ProgramOffering(
                offering_type=f"TQ_{ts}",
                program_id=mpid,
                offering_type_id=ot.id,
                is_active=True,
                duration_semesters=6,
            )
            s.add(po)
            await s.flush()
            ai_2025 = models.OfferingAcademicInfo(
                offering_id=po.id,
                academic_year=2025,
                tuition_fee_per_year=5000000,
                annual_admission_quota=100,
                is_published=True,
            )
            ai_2026 = models.OfferingAcademicInfo(
                offering_id=po.id,
                academic_year=2026,
                tuition_fee_per_year=5500000,
                annual_admission_quota=100,
                is_published=True,
            )
            ai_2027 = models.OfferingAcademicInfo(
                offering_id=po.id,
                academic_year=2027,
                tuition_fee_per_year=6000000,
                annual_admission_quota=100,
                is_published=False,
            )
            s.add_all([ai_2025, ai_2026, ai_2027])
            await s.flush()
            am = models.AdmissionMethod(
                code=f"hb_{ts}",
                name=f"HB_{ts}",
                requires_gpa=True,
                requires_subject_scores=False,
                is_active=True,
            )
            s.add(am)
            await s.flush()
            ac = models.AdmissionCriteria(
                method_id=am.id,
                code=f"TC_{ts}",
                name=f"TC_{ts}",
                min_gpa=0.0,
                scoring_method="average",
                subject_selection_mode="fixed",
                policy_version="2026.1",
                is_active=True,
            )
            s.add(ac)
            await s.flush()
            # Two paths — one per published year — so each path resolves
            # for its own academic_info. (Without this, only the year
            # whose path exists is creatable.)
            ap_2025 = models.AdmissionPath(
                academic_info_id=ai_2025.id,
                admission_method_id=am.id,
                criteria_id=ac.id,
                status="active",
                display_name=f"Path 2025 {ts}",
                display_order=0,
                visibility="public",
            )
            # Use a clone criteria for 2026 to satisfy uniqueness
            # constraint on admission_path.criteria_id (one path per
            # criteria). The ADM-003 invariant doesn't allow sharing.
            ac_2026 = models.AdmissionCriteria(
                method_id=am.id,
                code=f"TC_{ts}_2026",
                name=f"TC_{ts}_2026",
                min_gpa=0.0,
                scoring_method="average",
                subject_selection_mode="fixed",
                policy_version="2026.1",
                is_active=True,
            )
            s.add(ac_2026)
            await s.flush()
            ap_2026 = models.AdmissionPath(
                academic_info_id=ai_2026.id,
                admission_method_id=am.id,
                criteria_id=ac_2026.id,
                status="active",
                display_name=f"Path 2026 {ts}",
                display_order=0,
                visibility="public",
            )
            s.add_all([ap_2025, ap_2026])
            await s.flush()

    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "academic_info_2025_id": ai_2025.id,
        "academic_info_2026_id": ai_2026.id,
        "academic_info_2027_id": ai_2027.id,
    }


async def _seed_lead(client, admin_token_headers, officer_user_in_db, cfg, suffix):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (
        await client.post(
            LeadsURLs.LEADS,
            json={
                "full_name": f"ADM017 {suffix}",
                "phone": phone,
                "source": "website",
                "unit_id": cfg["unit_id"],
                "assigned_officer_id": officer_user_in_db["id"],
                "offering_id": cfg["offering_id"],
            },
            headers=admin_token_headers,
        )
    ).json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={
            "status_id": INITIAL_LEAD_STATUS_ID,
            "method": "phone",
            "notes": "Pre-admission",
        },
        headers=admin_token_headers,
    )
    return lead["id"]


async def _create_profile_request(
    client: AsyncClient,
    headers: dict,
    lead_id: int,
    method_id: int,
    academic_year: Optional[int] = None,
):
    body: dict = {"lead_id": lead_id, "admission_method_id": method_id}
    if academic_year is not None:
        body["academic_year"] = academic_year
    return await client.post(ADMISSIONS, json=body, headers=headers)


@pytest.mark.asyncio
async def test_create_profile_binds_to_explicit_academic_year(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    multi_year_offering: dict,
):
    """When client passes ``academic_year=2025``, the resulting
    profile is bound to the 2025 OfferingAcademicInfo, not the
    "first published" (which could be either 2025 or 2026 depending
    on history ordering).
    """
    lead_id = await _seed_lead(
        client, admin_token_headers, officer_user_in_db, multi_year_offering, "y2025"
    )

    resp = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2025,
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["academic_year"] == 2025, (
        f"Profile bound to year {body['academic_year']}, expected 2025"
    )
    applied = body.get("applied_rules") or {}
    assert applied.get("academic_info_id") == multi_year_offering[
        "academic_info_2025_id"
    ], (
        f"applied_rules.academic_info_id mismatch: got {applied.get('academic_info_id')}, "
        f"expected {multi_year_offering['academic_info_2025_id']}"
    )


@pytest.mark.asyncio
async def test_create_profile_rejects_unknown_academic_year(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    multi_year_offering: dict,
):
    """``academic_year=2099`` doesn't exist for this offering →
    ``BadRequest`` with a Vietnamese message. (Use 2099 not 1999
    to stay within the schema's ``ge=2000, le=2100`` range — that
    range is enforced by Pydantic before the service runs, so a
    truly out-of-range year would 422 not 400.)"""
    lead_id = await _seed_lead(
        client, admin_token_headers, officer_user_in_db, multi_year_offering, "y2099"
    )

    resp = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2099,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "2099" in body.get("detail", ""), body


@pytest.mark.asyncio
async def test_create_profile_rejects_unpublished_academic_year(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    multi_year_offering: dict,
):
    """Year 2027 exists for the offering but ``is_published=False`` →
    ``BadRequest`` (must opt the year into "đã công bố tuyển sinh"
    before profiles can bind to it)."""
    lead_id = await _seed_lead(
        client, admin_token_headers, officer_user_in_db, multi_year_offering, "y2027"
    )

    resp = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2027,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    detail = body.get("detail", "")
    assert "2027" in detail and "công bố" in detail, (
        f"Expected message about year 2027 not published, got: {detail}"
    )


@pytest.mark.asyncio
async def test_create_profile_legacy_callers_still_work_without_year(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    multi_year_offering: dict,
):
    """Backward compat: omitting ``academic_year`` falls back to the
    first published OfferingAcademicInfo. FE callers that haven't
    been updated yet must keep working — the strict-required flip
    happens in a follow-up after FE catches up.
    """
    lead_id = await _seed_lead(
        client, admin_token_headers, officer_user_in_db, multi_year_offering, "legacy"
    )

    resp = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=None,  # omitted
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    # First published academic_info — order from get_academic_info_history
    # is implementation-defined; we just assert the result is one of the
    # two published years (2025 / 2026), NOT the unpublished 2027.
    assert body["academic_year"] in (2025, 2026), (
        f"Legacy fallback bound to unexpected year {body['academic_year']}"
    )
