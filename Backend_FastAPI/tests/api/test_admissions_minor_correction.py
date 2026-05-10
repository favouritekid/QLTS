"""API + service tests for the post-approval minor correction flow.

Coverage organized around the security gates the service enforces:
- Status whitelist (approved/confirmed only)
- Optimistic version match
- Per-path effective allowlist (SAFE catalog ∩ admin config)
- HARD_DENY blocklist (citizen_id, dob, status, etc.)
- Reason validation (≥10 chars after strip)
- Empty diff (no-op submit) rejection
- Audit log emission
- ``permissions.minor_correction`` + ``minor_correction_fields`` in list + detail responses

Builds the AdmissionPath inline so each test owns its own allowlist
config — admin flips fields per-test without polluting other suites.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.core.admission_correction_constants import (
    HARD_DENY_FIELDS,
    SAFE_MINOR_CORRECTION_FIELDS,
)
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"


# ---------------------------------------------------------------------------
# Fixtures — copied inline (as per other admission test files in this dir)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def adm_config(seed_lead_dependencies: dict):
    """Seed a fresh AdmissionPath + offering chain for each test.

    Returned dict carries IDs the tests need: unit, offering, method, path.
    Each test receives its own path so we can flip allowlist freely.
    """
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
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
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id,
                admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name="Test", display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
            path_id = ap.id
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "path_id": path_id,
    }


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


async def _set_path_allowlist(path_id: int, fields: list[str]) -> None:
    """Write allowlist directly via session — bypasses admin guard so the
    fixture can prep state without minting an admin token."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path = await s.get(models.AdmissionPath, path_id)
            path.minor_correction_allowed_fields = list(fields)


async def _force_profile_status(profile_id: int, new_status: str) -> int:
    """Force a profile into approved/confirmed for the test scenario.

    Bypasses the workflow because building a full lead → consultation →
    submit → approve chain inflates each test ~5x. Returns the new
    version number for use with optimistic-lock payloads.
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            prof = await s.get(models.AdmissionProfile, profile_id)
            prof.status = new_status
            prof.version = (prof.version or 1) + 1
            # Ensure applied_rules carries the path_id snapshot the
            # service reads — depending on creation flow the seed may
            # have left it empty.
            applied = dict(prof.applied_rules or {})
            if "admission_path_id" not in applied:
                # Pull the path_id from the lead's offering chain via
                # a query — same way create_profile builds it.
                row = await s.execute(
                    select(models.AdmissionPath.id)
                    .join(
                        models.OfferingAcademicInfo,
                        models.AdmissionPath.academic_info_id == models.OfferingAcademicInfo.id,
                    )
                    .where(models.OfferingAcademicInfo.offering_id == prof.offering_id)
                    .limit(1)
                )
                pid = row.scalar_one_or_none()
                if pid is not None:
                    applied["admission_path_id"] = pid
                    prof.applied_rules = applied
            return prof.version


async def _create_seed_profile(
    client: AsyncClient,
    admin_token_headers: dict,
    adm_config: dict,
    officer_id: int,
    full_name: str,
) -> tuple[int, int]:
    """Seed lead + consultation + admission profile under admin token.

    Returns ``(profile_id, lead_id)``.
    """
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
    return prof.json()["id"], lead_id


# ---------------------------------------------------------------------------
# Module-level invariants (run at import time)
# ---------------------------------------------------------------------------


def test_field_adapters_match_safe_catalog():
    """FIELD_ADAPTERS keys must equal the SAFE catalog exactly. The
    helper module asserts the same on import; this test surfaces the
    contract in CI output if someone later replaces the assert with a
    silent fallback."""
    from app.services.admission_correction_helpers import FIELD_ADAPTERS

    assert set(FIELD_ADAPTERS.keys()) == SAFE_MINOR_CORRECTION_FIELDS


def test_safe_and_hard_deny_disjoint():
    """Renaming a SAFE field by accident would create a column where
    minor correction can edit AND a HARD_DENY entry rejects — leading
    to confusing 400s. Asserts the contract holds."""
    assert SAFE_MINOR_CORRECTION_FIELDS.isdisjoint(HARD_DENY_FIELDS)


# ---------------------------------------------------------------------------
# Status whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_correction_rejects_draft_status(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Profile in draft must reject — flow only accepts approved/confirmed."""
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Draft Probe",
    )
    # Don't promote — leave at draft.
    payload = {
        "version": 1,
        "reason": "test correction reason ten chars",
        "changes": {"nationality": "Việt Nam"},
    }
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json=payload,
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text
    assert "approved" in r.text.lower() or "confirmed" in r.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_status", ["approved", "confirmed"])
async def test_minor_correction_accepts_approved_and_confirmed(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
    target_status: str,
):
    """approved + confirmed both pass status check."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], f"Status Probe {target_status}",
    )
    new_version = await _force_profile_status(pid, target_status)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nationality"] == "Việt Nam"
    assert body["version"] == new_version + 1


# ---------------------------------------------------------------------------
# Hard-deny + allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_key", [
    "citizen_id", "dob", "phone", "email", "status",
    "admission_scores", "academic_history",
    "documents", "fees", "applied_rules", "admission_path_id",
])
async def test_minor_correction_rejects_hard_deny_keys(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
    denied_key: str,
):
    """Hard-deny rejects regardless of path config — defense in depth."""
    # Bend the path config to claim it allows everything (it can't
    # because Pydantic refuses non-SAFE keys, but the denied keys are
    # never in SAFE so we're testing the post-allowlist HARD_DENY gate
    # against fields a malicious client invents in `changes`).
    await _set_path_allowlist(adm_config["path_id"], list(SAFE_MINOR_CORRECTION_FIELDS))
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], f"Deny Probe {denied_key}",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {denied_key: "anything"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_minor_correction_empty_path_allowlist_rejects(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Path with empty allowlist (default) rejects every field — admin
    must explicitly opt in."""
    # Leave allowlist empty (migration default).
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Empty Allow Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_minor_correction_path_allows_only_specific_field(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Path allows ``nationality`` only — sending ``ethnicity`` rejects."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Per-Field Allow Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"ethnicity": "Kinh"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Optimistic lock + reason validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_correction_version_mismatch_returns_409(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Version Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version + 99,
            "reason": "test correction reason ten chars",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_minor_correction_reason_too_short_after_strip(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """A reason of "          a" (9 spaces + 1 char, length 10) must
    fail because StringConstraints strips before checking — bytes-on-the-
    wire passing length 10 would be a sneaky bypass."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Reason Strip Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "          a",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_minor_correction_empty_changes_rejected_by_pydantic(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Pydantic validator rejects empty ``changes`` dict (422)."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Empty Changes Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_minor_correction_no_op_diff_rejected(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Resending the same value the profile already holds = no diff =
    400 ("Không có thay đổi nào")."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "No-op Probe",
    )
    # Pre-set the field to a known value.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            prof = await s.get(models.AdmissionProfile, pid)
            prof.nationality = "Việt Nam"
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Adapter normalization + business-rule check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_correction_normalizes_iso_date_string(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Sending union_entry_date as ISO string parses to naive UTC datetime."""
    await _set_path_allowlist(adm_config["path_id"], ["union_entry_date"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Date Normalize Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"union_entry_date": "2020-09-01"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        prof = await s.get(models.AdmissionProfile, pid)
        assert prof.union_entry_date is not None
        assert prof.union_entry_date.year == 2020
        assert prof.union_entry_date.month == 9
        assert prof.union_entry_date.day == 1
        # Naive UTC — no tzinfo
        assert prof.union_entry_date.tzinfo is None


@pytest.mark.asyncio
async def test_minor_correction_future_date_rejected_by_business_rule(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Đoàn / Đảng entry dates in the future must reject."""
    await _set_path_allowlist(adm_config["path_id"], ["party_entry_date"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Future Date Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"party_entry_date": "2999-01-01"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_minor_correction_invalid_gender_rejected(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """gender outside Nam/Nữ/Khác must reject."""
    await _set_path_allowlist(adm_config["path_id"], ["gender"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Bad Gender Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"gender": "Male"},  # not in whitelist
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_minor_correction_invalid_social_insurance_format(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """social_insurance_number must match ``^\\d{10}$``."""
    await _set_path_allowlist(adm_config["path_id"], ["social_insurance_number"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "BHXH Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"social_insurance_number": "abc-not-digits"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_correction_writes_audit_row(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Successful correction creates an EntityAuditLog row with reason +
    diff containing old/new values per field."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Audit Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "Sửa lại quốc tịch theo yêu cầu",
            "changes": {"nationality": "Việt Nam"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        rows = await s.execute(
            select(models.EntityAuditLog)
            .where(models.EntityAuditLog.entity_type == "AdmissionProfile")
            .where(models.EntityAuditLog.entity_id == pid)
            .where(models.EntityAuditLog.action == "minor_corrected")
        )
        log_rows = rows.scalars().all()
        assert len(log_rows) == 1
        log = log_rows[0]
        assert log.reason == "Sửa lại quốc tịch theo yêu cầu"
        # changes JSONB has {field: {old, new}}
        changes = log.changes or {}
        assert "nationality" in changes
        assert changes["nationality"]["new"] == "Việt Nam"


# ---------------------------------------------------------------------------
# Detail / list response wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_correction_detail_response_shape(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """GET detail returns ``minor_correction_fields`` populated and
    ``permissions.minor_correction = true`` when path has allowlist
    configured + status is approved."""
    await _set_path_allowlist(adm_config["path_id"], ["nationality", "ethnicity"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Detail Shape Probe",
    )
    await _force_profile_status(pid, "approved")
    r = await client.get(f"{ADMISSIONS}/{pid}", headers=admin_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["minor_correction_fields"]) == ["ethnicity", "nationality"]
    assert body["permissions"]["minor_correction"] is True
    assert "minor_correction" in body["available_actions"]


@pytest.mark.asyncio
async def test_minor_correction_rejects_union_after_party(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Cross-field invariant: union_entry_date must precede
    party_entry_date — service merges candidate state and applies the
    same rule as AdmissionProfileUpdate.validate_logical_dates."""
    await _set_path_allowlist(adm_config["path_id"], ["union_entry_date"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Cross-Field Date Probe",
    )
    # Pre-set party_entry_date so the candidate state has a baseline.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            prof = await s.get(models.AdmissionProfile, pid)
            prof.party_entry_date = datetime(2020, 6, 1, 0, 0, 0)
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            # Set union date AFTER existing party date — must reject.
            "changes": {"union_entry_date": "2021-09-01"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text
    assert "Đoàn" in r.text  # message references Vietnamese label


@pytest.mark.asyncio
async def test_minor_correction_rejects_party_after_party_official(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """party_entry_date must precede party_official_entry_date."""
    await _set_path_allowlist(adm_config["path_id"], ["party_entry_date"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Party Order Probe",
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            prof = await s.get(models.AdmissionProfile, pid)
            prof.party_official_entry_date = datetime(2020, 6, 1, 0, 0, 0)
    new_version = await _force_profile_status(pid, "approved")
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"party_entry_date": "2021-09-01"},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_minor_correction_family_info_max_10_enforced(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """family_info adapter retains the max_length=10 cap from
    AdmissionProfileUpdate so minor correction can't bypass the array
    cap and persist 11+ guardian rows."""
    await _set_path_allowlist(adm_config["path_id"], ["family_info"])
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Family Cap Probe",
    )
    new_version = await _force_profile_status(pid, "approved")
    big = [
        {
            "relationship": "father",
            "full_name": f"Nguyen Van Test {i}",
            "occupation": "engineer",
            "phone": f"098{i:07d}",
            "is_primary_guardian": False,
        }
        for i in range(11)  # one over the cap
    ]
    r = await client.post(
        f"{ADMISSIONS}/{pid}/minor-correction",
        json={
            "version": new_version,
            "reason": "test correction reason ten chars",
            "changes": {"family_info": big},
        },
        headers=admin_token_headers,
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_admission_path_create_persists_allowlist_for_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Admin creating a path can seed the minor-correction allowlist;
    the service must forward the field to the repository instead of
    silently dropping it."""
    # Build the supporting offering chain inline (mirrors adm_config but
    # we need to drive the create endpoint, not the AdmissionPath model).
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
            ai_id = ai.id
            am_id = am.id

    r = await client.post(
        "/api/admission-config/paths",
        json={
            "academic_info_id": ai_id,
            "admission_method_id": am_id,
            "display_name": "AllowlistOnCreate",
            "display_order": 1,
            "visibility": "internal",
            "allow_unverified_submission": False,
            "minor_correction_allowed_fields": ["nationality", "ethnicity"],
        },
        headers=admin_token_headers,
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert sorted(body["minor_correction_allowed_fields"]) == ["ethnicity", "nationality"]


@pytest.mark.asyncio
async def test_minor_correction_detail_hides_when_allowlist_empty(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm_config: dict,
):
    """Path with empty allowlist (default) → permission False, fields []."""
    pid, _ = await _create_seed_profile(
        client, admin_token_headers, adm_config,
        officer_user_in_db["id"], "Detail Empty Probe",
    )
    await _force_profile_status(pid, "approved")
    r = await client.get(f"{ADMISSIONS}/{pid}", headers=admin_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["minor_correction_fields"] == []
    assert body["permissions"]["minor_correction"] is False
    assert "minor_correction" not in body["available_actions"]
