"""ADM-017 — verify create_profile binds to the correct
``OfferingAcademicInfo`` row when client passes ``academic_year``.

Q8=b decision (memory ``project_admission_audit_2026-04-27_wave_status``):
client must pass academic_year on profile creation. Round contract
hardening (plan v4 — F30) FLIPPED the field to strict-required and
REMOVED the "first published" fallback: ``academic_year`` (and
``admission_round_id``) are now mandatory. When passed they are honoured
strictly — lookup the matching ``(offering_id, academic_year)``
``OfferingAcademicInfo`` row, reject if not found / not published, and
validate the round belongs to that year (active, not archived).
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
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_2025_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2025)
            ap_2025 = models.AdmissionPath(
                academic_info_id=ai_2025.id,
                admission_method_id=am.id,
                admission_round_id=round_2025_id,
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
            round_2026_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap_2026 = models.AdmissionPath(
                academic_info_id=ai_2026.id,
                admission_method_id=am.id,
                admission_round_id=round_2026_id,
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
        # Round contract hardening (plan v4): expose the per-year DOT_1
        # rounds so create-profile can pass the now-required admission_round_id.
        "round_2025_id": round_2025_id,
        "round_2026_id": round_2026_id,
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
    admission_round_id: Optional[int] = None,
):
    body: dict = {"lead_id": lead_id, "admission_method_id": method_id}
    if academic_year is not None:
        body["academic_year"] = academic_year
    if admission_round_id is not None:
        body["admission_round_id"] = admission_round_id
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
        admission_round_id=multi_year_offering["round_2025_id"],
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
        # Pass a valid round; the academic_info lookup for year 2099 fails
        # FIRST (Step 6) with a 400 mentioning 2099, before the round
        # validation (Step 6b) is ever reached.
        admission_round_id=multi_year_offering["round_2025_id"],
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
        # Valid round; the published-check on year 2027 (Step 6) fails
        # before round validation (Step 6b).
        admission_round_id=multi_year_offering["round_2025_id"],
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    detail = body.get("detail", "")
    assert "2027" in detail and "công bố" in detail, (
        f"Expected message about year 2027 not published, got: {detail}"
    )


@pytest.mark.asyncio
async def test_create_profile_requires_academic_year_and_round(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    multi_year_offering: dict,
):
    """Round contract hardening (plan v4 — F30): the legacy "omit
    academic_year → first published" fallback is REMOVED. ``academic_year``
    and ``admission_round_id`` are now both REQUIRED; a round whose year
    doesn't match is rejected. The first three probes fail validation (no
    profile written), so the happy path on the same lead still succeeds.
    """
    lead_id = await _seed_lead(
        client, admin_token_headers, officer_user_in_db, multi_year_offering, "strict"
    )

    # Missing academic_year → 422 (Pydantic required field; no fallback).
    resp_no_year = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=None,
        admission_round_id=multi_year_offering["round_2026_id"],
    )
    assert resp_no_year.status_code == 422, resp_no_year.text

    # Missing admission_round_id → 422.
    resp_no_round = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2026,
        admission_round_id=None,
    )
    assert resp_no_round.status_code == 422, resp_no_round.text

    # Round whose year (2025) doesn't match academic_year (2026) → 400.
    resp_mismatch = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2026,
        admission_round_id=multi_year_offering["round_2025_id"],
    )
    assert resp_mismatch.status_code == 400, resp_mismatch.text
    assert "không khớp" in resp_mismatch.json().get("detail", ""), resp_mismatch.text

    # Both present + matching → 201, bound to the explicit (year, round).
    resp_ok = await _create_profile_request(
        client,
        admin_token_headers,
        lead_id,
        multi_year_offering["method_id"],
        academic_year=2026,
        admission_round_id=multi_year_offering["round_2026_id"],
    )
    assert resp_ok.status_code in (200, 201), resp_ok.text
    body = resp_ok.json()
    assert body["academic_year"] == 2026
    applied = body.get("applied_rules") or {}
    assert applied.get("admission_round_id") == multi_year_offering["round_2026_id"], (
        f"applied_rules.admission_round_id mismatch: got "
        f"{applied.get('admission_round_id')}, expected "
        f"{multi_year_offering['round_2026_id']}"
    )
