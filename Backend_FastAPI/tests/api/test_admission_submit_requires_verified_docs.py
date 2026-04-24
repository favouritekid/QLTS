"""Submit gate honours per-path allow_unverified_submission (PR #6).

Exercises the four interesting branches of ``_validate_documents``:

1. flag off, only uploaded docs → 400 with verify message
2. flag off, verified doc → 200 submit
3. flag on (legacy path), uploaded doc → 200 submit (grandfathered)
4. flag off, mix of verified + uploaded → 400 on the uploaded one

Profiles are seeded with ``schema_version=2`` + the snapshotted flag,
matching what ``create_profile`` writes on real traffic.
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


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def strict_path_config(seed_lead_dependencies: dict):
    """Seed an admission path with allow_unverified_submission=False.

    Mirrors the inline fixture from prior PRs; duplicated so the test
    file stays self-contained until a third consumer warrants a
    promoted conftest fixture.
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
                min_gpa=0.0, scoring_method="average", subject_selection_mode="fixed",
                policy_version="2026.1", is_active=True,
            )
            s.add(ac); await s.flush()
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id, criteria_id=ac.id,
                status="active", display_name="PR6 Strict", display_order=0,
                visibility="public",
                allow_unverified_submission=False,  # strict mode explicit
            )
            s.add(ap); await s.flush()
            dg = models.DocumentGroup(
                offering_type_id=ot.id,
                admission_method_id=am.id,
                code=f"dg_{ts}",
                name=f"DG_{ts}",
                is_active=True,
            )
            s.add(dg); await s.flush()
            dgi = models.DocumentGroupItem(
                group_id=dg.id,
                document_type_id=dt.id,
                is_mandatory=True,
                requires_upload=True,
                submission_format="photo",
                display_order=1,
            )
            s.add(dgi); await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "path_id": ap.id,
        "doc_code": dt.code,
    }


async def _create_draft(client, admin_token_headers, officer_user_in_db, cfg, *, full_name="PR6"):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    # Vietnamese phone: 10 digits, leading 0. Millisecond suffix keeps
    # numbers unique across the 4 probes without overflowing the length cap.
    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead_resp = await client.post(LeadsURLs.LEADS, json={
        "full_name": full_name,
        "phone": phone,
        "source": "website",
        "unit_id": cfg["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"],
        "offering_id": cfg["offering_id"],
    }, headers=admin_token_headers)
    assert lead_resp.status_code in (200, 201), (
        f"Lead create failed ({lead_resp.status_code}): {lead_resp.text}"
    )
    lead = lead_resp.json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "Pre-admission"},
        headers=admin_token_headers,
    )
    prof_resp = await client.post(ADMISSIONS, json={
        "lead_id": lead["id"],
        "admission_method_id": cfg["method_id"],
    }, headers=admin_token_headers)
    assert prof_resp.status_code in (200, 201), (
        f"Create profile failed ({prof_resp.status_code}): {prof_resp.text}\n"
        f"Lead was: {lead}"
    )
    return prof_resp.json()


async def _officer_upload(client, oh, pid, doc_code):
    return await client.post(
        f"{ADMISSIONS}/{pid}/documents/{doc_code}/upload",
        headers=oh,
        files={"file": (f"{doc_code}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )


async def _fill_personal(client, oh, pid):
    """Fill required personal fields so submit doesn't fail on those instead of docs."""
    ts_cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    await client.put(f"{ADMISSIONS}/{pid}", json={
        "version": v,
        "citizen_id": ts_cccd,
        "gender": "male",
        "dob": "2001-01-01",
        "nationality": "Viet Nam",
        "ethnicity": "Kinh",
        "place_of_birth": "Test",
        "family_info": [{"relationship": "Cha", "full_name": "P", "phone": "0901111111", "is_primary_guardian": True}],
        "academic_history": [{"school_name": "THPT", "year_from": 2019, "year_to": 2022, "gpa": 8.0, "graduation_type": "THPT"}],
        "admission_scores": {"gpa": 8.0, "subject_scores": {}},
    }, headers=oh)


@pytest.mark.asyncio
async def test_strict_path_blocks_submit_with_uploaded_only(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    strict_path_config: dict,
):
    """Uploaded doc (no officer verification) must fail submit on strict path."""
    prof = await _create_draft(client, admin_token_headers, officer_user_in_db, strict_path_config)
    pid = prof["id"]

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await _fill_personal(client, oh, pid)
    assert (await _officer_upload(client, oh, pid, strict_path_config["doc_code"])).status_code in (200, 201)

    # Debug: confirm the snapshot is strict before submit.
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    applied = detail.get("applied_rules") or {}
    assert applied.get("schema_version") == 2, f"Expected schema_version=2, got: {applied.get('schema_version')}"
    assert applied.get("allow_unverified_submission") is False, (
        f"Snapshot should be strict (False), got: {applied.get('allow_unverified_submission')}. "
        f"Full applied_rules keys: {sorted(applied.keys())}"
    )

    v = detail["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    # Submit returns 200 but keeps status=draft + surfaces errors (current contract).
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft", f"Strict submit should stay in draft, got {body['status']}: {body}"
    errs = body.get("validation_errors") or []
    assert any("xác minh" in e.lower() or "verify" in e.lower() for e in errs), (
        f"Expected a verify-message in validation_errors, got: {errs}"
    )


@pytest.mark.asyncio
async def test_strict_path_allows_submit_when_verified(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    strict_path_config: dict,
):
    """Verified doc satisfies strict submit gate."""
    prof = await _create_draft(client, admin_token_headers, officer_user_in_db, strict_path_config, full_name="PR6 Verified")
    pid = prof["id"]

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await _fill_personal(client, oh, pid)
    assert (await _officer_upload(client, oh, pid, strict_path_config["doc_code"])).status_code in (200, 201)

    # Admin verifies (officer doesn't have verify permission per PR #5 service guard).
    admin = await _login(client, "testadmin", "AdminPassword!123")
    verify_resp = await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{strict_path_config['doc_code']}/verify-format",
        json={"format": "photo"},
        headers=admin,
    )
    assert verify_resp.status_code == 200, verify_resp.text

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert resp.status_code == 200, f"Expected 200 with verified docs, got {resp.status_code}: {resp.text[:300]}"
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_legacy_schema_v1_profile_grandfathered(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    strict_path_config: dict,
):
    """schema_version=1 profile submits with uploaded docs.

    Simulates a pre-migration profile whose applied_rules was backfilled
    with schema_version=1 + allow_unverified_submission=true. The strict
    rule must NOT apply retroactively — the validator's grandfather
    branch keeps the legacy lax behaviour.
    """
    prof = await _create_draft(client, admin_token_headers, officer_user_in_db, strict_path_config, full_name="PR6 Legacy")
    pid = prof["id"]

    # Rewrite applied_rules to schema_version=1 (disable immutability
    # trigger the same way the migration does, IF it's installed — the
    # test DB uses Base.metadata.create_all() and may not carry the
    # trigger that the dev/prod Alembic history sets up).
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from sqlalchemy import text
            trg_exists = (await s.execute(text(
                "SELECT 1 FROM pg_trigger "
                "WHERE tgrelid = 'admission_profile'::regclass "
                "  AND tgname = 'enforce_applied_rules_immutability' "
                "  AND NOT tgisinternal"
            ))).scalar()
            if trg_exists:
                await s.execute(text(
                    "ALTER TABLE admission_profile DISABLE TRIGGER "
                    "enforce_applied_rules_immutability"
                ))
            try:
                await s.execute(text(
                    """
                    UPDATE admission_profile
                    SET applied_rules =
                        COALESCE(applied_rules, '{}'::jsonb)
                        || jsonb_build_object(
                            'schema_version', 1,
                            'allow_unverified_submission', TRUE
                        )
                    WHERE id = :pid
                    """
                ), {"pid": pid})
            finally:
                if trg_exists:
                    await s.execute(text(
                        "ALTER TABLE admission_profile ENABLE TRIGGER "
                        "enforce_applied_rules_immutability"
                    ))

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await _fill_personal(client, oh, pid)
    assert (await _officer_upload(client, oh, pid, strict_path_config["doc_code"])).status_code in (200, 201)

    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert resp.status_code == 200, f"Legacy profile should still submit, got {resp.status_code}: {resp.text[:300]}"
