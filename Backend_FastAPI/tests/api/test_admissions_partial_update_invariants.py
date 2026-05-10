"""Tests for cross-field date invariants on partial profile updates.

Pre-existing bug fixed in this PR: ``PUT /admissions/{id}`` accepted a
partial payload via ``data.model_dump(exclude_unset=True)``, so
``AdmissionProfileUpdate.validate_logical_dates`` only saw fields the
client sent. A request that updated ONLY ``union_entry_date`` could
leave the row with ``union > party`` because ``party_entry_date``
already in the database was never visible to the validator.

Fix: service builds a candidate state (DB attributes + payload
overlay) and runs the shared
``app.services.admission_invariants.validate_logical_dates`` utility
before the per-field setattr loop.

Lesson reference: feedback memory
``partial-update-loses-cross-field-invariants``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import LeadsURLs


ADMISSIONS = "/api/admissions"


# ---------------------------------------------------------------------------
# Shared fixtures (kept inline to mirror existing admission test files)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def adm_config(seed_lead_dependencies: dict):
    """Seed offering chain + path for each test (same shape as
    test_admissions_minor_correction.adm_config)."""
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(code=f"tq_{ts}", name=f"TQ_{ts}", display_order=1)
            s.add(ot); await s.flush()
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
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id,
                admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name="Test", display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
    }


async def _create_draft_profile(
    client: AsyncClient,
    admin_token_headers: dict,
    adm_config: dict,
    officer_id: int,
    full_name: str,
) -> int:
    """Seed lead + consultation + admission profile under admin token.
    Returns profile_id (status='draft' so PUT is allowed)."""
    lead_resp = await client.post(LeadsURLs.LEADS, json={
        "full_name": full_name,
        "phone": f"098{int(datetime.now().timestamp()) % 10_000_000:07d}",
        "source": "website",
        "unit_id": adm_config["unit_id"],
        "assigned_officer_id": officer_id,
        "offering_id": adm_config["offering_id"],
    }, headers=admin_token_headers)
    assert lead_resp.status_code in (200, 201), lead_resp.text
    lead_id = lead_resp.json()["id"]

    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    cons = await client.post(
        f"{LeadsURLs.LEADS}/{lead_id}/consultations",
        json={
            "status_id": INITIAL_LEAD_STATUS_ID,
            "method": "phone",
            "notes": "Pre-admission consultation",
        },
        headers=admin_token_headers,
    )
    assert cons.status_code in (200, 201), cons.text

    prof = await client.post(ADMISSIONS, json={
        "lead_id": lead_id,
        "admission_method_id": adm_config["method_id"],
    }, headers=admin_token_headers)
    assert prof.status_code in (200, 201), prof.text
    return prof.json()["id"]


async def _set_dates_in_db(
    profile_id: int,
    *,
    dob=None,
    union_entry_date=None,
    party_entry_date=None,
    party_official_entry_date=None,
) -> None:
    """Pre-populate date fields directly via session — bypasses normal
    update_profile flow so the test can stage a state where partial
    update will conflict."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            prof = await s.get(models.AdmissionProfile, profile_id)
            if dob is not None:
                prof.dob = dob
            if union_entry_date is not None:
                prof.union_entry_date = union_entry_date
            if party_entry_date is not None:
                prof.party_entry_date = party_entry_date
            if party_official_entry_date is not None:
                prof.party_official_entry_date = party_official_entry_date


# ---------------------------------------------------------------------------
# Schema-level (regression — make sure refactor didn't break payload-only check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_update_within_payload_union_after_party_rejects(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """When BOTH union and party entry dates are in the payload AND
    union > party, schema's @model_validator catches it (422). Existing
    behavior — guards against schema refactor breaking this."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Schema Within-Payload Probe",
    )
    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "union_entry_date": "2021-09-01T00:00:00",
            "party_entry_date": "2020-06-01T00:00:00",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 422, r.text
    assert "Đoàn" in r.text


# ---------------------------------------------------------------------------
# Candidate-state checks (the new fix — DB + partial payload merged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_update_only_union_after_existing_party_rejects(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """DB has party_entry_date = 2020-06-01. Partial PUT sends ONLY
    union_entry_date = 2021-09-01 (after existing party). Schema-level
    validator on the trimmed payload would NOT see party_entry_date and
    would silently pass. Service candidate-state check must catch this."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Candidate Union After Party",
    )
    await _set_dates_in_db(pid, party_entry_date=datetime(2020, 6, 1))

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "union_entry_date": "2021-09-01T00:00:00",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text
    assert "Đoàn" in r.text


@pytest.mark.asyncio
async def test_partial_update_only_party_after_existing_official_rejects(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """DB has party_official_entry_date = 2020-06-01. Partial PUT sends
    ONLY party_entry_date = 2021-09-01 (after official). Must reject."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Candidate Party After Official",
    )
    await _set_dates_in_db(pid, party_official_entry_date=datetime(2020, 6, 1))

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "party_entry_date": "2021-09-01T00:00:00",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_partial_update_dob_null_does_not_bypass_invariant(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Regression for review finding (P1): payload ``{"dob": null,
    "union_entry_date": "<earlier>"}`` must NOT silently pass.

    The dob setter skips ``None`` (``is not None`` check at the
    per-field setattr block), so the existing DB dob is preserved.
    A naive candidate-state merge that copies payload as-is would set
    candidate dob to None → invariant ``dob ≤ union`` short-circuits →
    validation passes → setter preserves DB dob → row ends up with the
    original (post-union) dob, re-introducing the exact invariant bypass
    the candidate-state merge is supposed to catch.

    The fix: candidate-state merge mirrors setter semantics. For dob
    specifically, ``payload['dob'] is None`` means "preserve DB
    value", so the candidate uses ``profile.dob`` and the invariant
    compares against the real future state.
    """
    from datetime import date as date_cls
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "DOB Null Bypass Probe",
    )
    # Pre-set DB dob AFTER the union entry the client will send. If the
    # candidate-state merge incorrectly applied ``dob: null``, the
    # invariant check would not see the conflict.
    await _set_dates_in_db(pid, dob=date_cls(2020, 1, 1))

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "dob": None,                                # ← payload null
            "union_entry_date": "2015-09-01T00:00:00",  # ← before existing dob
        },
        headers=admin_token_headers,
    )
    # Without the fix this returns 200 silently and persists an invalid
    # state. With the fix candidate dob = DB value 2020-01-01, which is
    # AFTER union 2015-09-01 → invariant raises → 400.
    assert r.status_code == 400, r.text
    assert "sinh" in r.text.lower() or "Ngày sinh" in r.text


@pytest.mark.asyncio
async def test_partial_update_only_dob_after_existing_union_rejects(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """DB has union_entry_date = 2015-09-01. Partial PUT sends ONLY
    dob = 2020-01-01 (after existing union — applicant born after
    joining the youth union, impossible). Must reject."""
    from datetime import date as date_cls
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Candidate DOB After Union",
    )
    await _set_dates_in_db(pid, union_entry_date=datetime(2015, 9, 1))

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "dob": "2020-01-01",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text
    assert "sinh" in r.text.lower() or "Ngày sinh" in r.text


# ---------------------------------------------------------------------------
# Happy paths (must keep working — refactor regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_update_valid_dates_through_against_existing_state(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """DB has party_entry_date = 2020-06-01. Partial PUT with
    union_entry_date = 2019-01-01 (before party) must pass."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Candidate Happy Path",
    )
    await _set_dates_in_db(pid, party_entry_date=datetime(2020, 6, 1))

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "union_entry_date": "2019-01-01T00:00:00",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_partial_update_no_date_fields_skips_invariant_check(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Update unrelated to date fields must not trigger the invariant
    check (perf — avoid building candidate state when not needed)."""
    pid = await _create_draft_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Non-Date Update",
    )

    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": 1,
            "nationality": "Việt Nam",
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Utility unit tests (lightweight, surface contract)
# ---------------------------------------------------------------------------


def test_validate_logical_dates_utility_empty_state_ok():
    from app.services.admission_invariants import validate_logical_dates
    validate_logical_dates({})  # all fields missing → no rule triggered


def test_validate_logical_dates_utility_union_after_party_raises():
    from app.services.admission_invariants import validate_logical_dates
    with pytest.raises(ValueError, match="Đoàn"):
        validate_logical_dates({
            "union_entry_date": datetime(2021, 9, 1),
            "party_entry_date": datetime(2020, 6, 1),
        })


def test_validate_logical_dates_utility_dob_as_date_object_compared():
    from datetime import date as date_cls
    from app.services.admission_invariants import validate_logical_dates
    with pytest.raises(ValueError, match="sinh"):
        validate_logical_dates({
            "dob": date_cls(2020, 1, 1),
            "union_entry_date": datetime(2015, 9, 1),
        })
