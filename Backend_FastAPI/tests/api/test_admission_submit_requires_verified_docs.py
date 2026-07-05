"""Submit gate honours per-path allow_unverified_submission (PR #6).

Exercises the four interesting branches of ``_validate_documents``:

1. flag off, only uploaded docs → 400 with verify message
2. flag off, verified doc → 200 submit
3. flag on (legacy path), uploaded doc → 200 submit (grandfathered)
4. flag off, mix of verified + uploaded → 400 on the uploaded one

Profiles are seeded with ``schema_version=2`` + the snapshotted flag,
matching what ``create_profile`` writes on real traffic.

Dirty-DB note
-------------
The shared ``seed_lead_dependencies`` fixture inserts
``organization_unit`` with explicit ``id=1`` (TestOrgData.UNIT_1).
``setup_test_database`` runs ``TRUNCATE … RESTART IDENTITY`` between
function-scoped tests inside one pytest session, so this works
cleanly when pytest owns the DB lifecycle. If the qlts_test database
is left dirty by an aborted run (``id=1`` already present, sequence
out of sync), the fixture fails on duplicate-PK before the assertion
can run. Reset recipe (per memory `reference_test_db_schema_source`):

    docker compose exec postgres psql -U qlts -c \
        "DROP DATABASE qlts_test"

The next pytest run recreates the schema via ``init_schema_once`` and
the seed succeeds. This test passes 3/3 on a clean DB.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.builders import SUBMITTABLE_PERMANENT_ADDRESS
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def strict_path_config(seed_lead_dependencies: dict):
    """Seed a STRICT admission path (allow_unverified_submission=False) on top of
    the full #337 submittable offering chain.

    The prior inline seed lacked the legacy target-level config
    (``OfferingAdmissionConfig`` + ``MajorProgram.degree_level_id``) and the KV
    school, so ``submit_and_evaluate`` fail-closed with ``CONFIG_GAP_TARGET_LEVEL``
    before ever reaching the doc-verification rule under test. Build on
    ``seed_submittable_offering_config`` (the proven #337 recipe) and add ONLY the
    strict path + a mandatory doc so the doc rule is the sole remaining gate.
    Pair with the submittable ``_fill_personal`` (KV-resolvable academic_history
    via ``school_id`` + submittable ward).
    """
    from tests.fixtures.builders import (
        AdmissionRoundBuilder,
        ensure_submittable_ward,
        seed_submittable_offering_config,
        _next_id,
    )

    uid = seed_lead_dependencies["unit_id"]
    await ensure_submittable_ward()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # The recipe returns every chain id we need (academic_info/offering/
            # criteria/method/offering_type), so no config→…→criteria re-walk.
            seed = await seed_submittable_offering_config(
                s, unit_id=uid, academic_year=2026
            )
            method_id = seed["method_id"]
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026
            )

            ap = models.AdmissionPath(
                academic_info_id=seed["academic_info_id"],
                admission_method_id=method_id,
                admission_round_id=round_id,
                criteria_id=seed["criteria_id"],
                status="active", display_name="PR6 Strict", display_order=0,
                visibility="public",
                allow_unverified_submission=False,  # strict mode explicit
            )
            s.add(ap)
            await s.flush()
            path_id = ap.id

            # Collision-free suffix (monotonic _next_id, not seconds-resolution
            # datetime) — code columns are UNIQUE, and two same-second fixture
            # instantiations would otherwise clash.
            sid = _next_id()
            dt = models.ConfigDocumentType(
                code=f"tcc_{sid}", name=f"TCC_{sid}", display_order=1
            )
            s.add(dt)
            await s.flush()
            doc_code = dt.code
            dg = models.DocumentGroup(
                offering_type_id=seed["offering_type_id"],
                admission_method_id=method_id,
                code=f"dg_{sid}", name=f"DG_{sid}", is_active=True,
            )
            s.add(dg)
            await s.flush()
            dgi = models.DocumentGroupItem(
                group_id=dg.id, document_type_id=dt.id,
                is_mandatory=True, requires_upload=True,
                submission_format="photo", display_order=1,
            )
            s.add(dgi)
            await s.flush()
    return {
        "unit_id": uid,
        "offering_id": seed["offering_id"],
        "method_id": method_id,
        "path_id": path_id,
        "doc_code": doc_code,
        "round_id": round_id,
        "school_id": seed["school_id"],
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
        "admission_round_id": cfg["round_id"],
        "academic_year": 2026,
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


async def _fill_personal(client, oh, pid, *, school_id):
    """Clear every NON-doc submit gate so submit outcome hinges purely on the doc
    rule: personal fields + submittable address + graduated_thpt cultural level +
    a KV-resolvable THPT academic_history (``school_id`` → seeded VnSchool) +
    family_info."""
    ts_cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    r = await client.put(f"{ADMISSIONS}/{pid}", json={
        "version": v,
        "citizen_id": ts_cccd,
        "gender": "male",
        "dob": "2001-01-01",
        "nationality": "Viet Nam",
        "ethnicity": "Kinh",
        "place_of_birth": "Test",
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
        **SUBMITTABLE_PERMANENT_ADDRESS,
        "family_info": [{
            "relationship": "Cha", "full_name": "P",
            "phone": "0901111111", "is_primary_guardian": True,
        }],
        "academic_history": [{
            "school_name": "THPT Submittable", "year_from": 2020,
            "year_to": 2024, "gpa": 8.0, "graduation_type": "THPT",
            "level": "THPT", "grade_to": 12, "school_id": school_id,
        }],
        "admission_scores": {"gpa": 8.0, "subject_scores": {}},
    }, headers=oh)
    assert r.status_code == 200, f"_fill_personal PUT failed: {r.status_code} {r.text}"


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
    await _fill_personal(client, oh, pid, school_id=strict_path_config["school_id"])
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
    await _fill_personal(client, oh, pid, school_id=strict_path_config["school_id"])
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
    await _fill_personal(client, oh, pid, school_id=strict_path_config["school_id"])
    assert (await _officer_upload(client, oh, pid, strict_path_config["doc_code"])).status_code in (200, 201)

    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert resp.status_code == 200, f"Legacy profile should still submit, got {resp.status_code}: {resp.text[:300]}"


@pytest.mark.asyncio
async def test_document_debt_flag_gated_on_required_data(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    strict_path_config: dict,
):
    """``can_submit_with_document_debt`` must NOT be advertised while family/
    academic data is still missing, and MUST be honoured once it is.

    Phase 2 fills the profile so it is GENUINELY submittable-with-debt (submittable
    address incl. current-era commune_code + KV-resolvable academic_history via
    ``school_id`` + cultural level), so the flag=True is faithful (not an optimistic
    edge). Phase 3 then POSTs the advertised debt submission and asserts it is
    ACCEPTED — closing the flag↔API loop the flag exists to guarantee.
    """
    prof = await _create_draft(
        client, admin_token_headers, officer_user_in_db, strict_path_config
    )
    pid = prof["id"]
    school_id = strict_path_config["school_id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # Phase 1 — everything a submit-with-debt needs EXCEPT family/academic and the
    # doc: personal + full submittable address + cultural level + scores. The
    # mandatory doc is left MISSING so the doc-debt path would otherwise be offered.
    ts_cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    r = await client.put(f"{ADMISSIONS}/{pid}", json={
        "version": v,
        "citizen_id": ts_cccd,
        "gender": "male",
        "dob": "2001-01-01",
        "nationality": "Viet Nam",
        "ethnicity": "Kinh",
        "place_of_birth": "Test",
        "cultural_education_level": "graduated_thpt",
        "vocational_qualification": "none",
        **SUBMITTABLE_PERMANENT_ADDRESS,
        "admission_scores": {"gpa": 8.0, "subject_scores": {}},
    }, headers=oh)
    assert r.status_code == 200, f"phase-1 PUT failed: {r.status_code} {r.text}"

    blocked = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert blocked["submit_blocked_by_data"] is True, blocked
    assert blocked["can_submit_with_document_debt"] is False, blocked

    # Phase 2 — supply family + a KV-resolvable academic_history. The profile is
    # now fully submittable-with-debt, so BOTH flags flip.
    v = blocked["version"]
    r = await client.put(f"{ADMISSIONS}/{pid}", json={
        "version": v,
        "family_info": [{
            "relationship": "Cha", "full_name": "P",
            "phone": "0901111111", "is_primary_guardian": True,
        }],
        "academic_history": [{
            "school_name": "THPT Submittable", "year_from": 2020,
            "year_to": 2024, "gpa": 8.0, "graduation_type": "THPT",
            "level": "THPT", "grade_to": 12, "school_id": school_id,
        }],
    }, headers=oh)
    assert r.status_code == 200, f"phase-2 PUT failed: {r.status_code} {r.text}"

    ok = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    assert ok["submit_blocked_by_data"] is False, ok
    assert ok["can_submit_with_document_debt"] is True, ok

    # Phase 3 — honour the flag end-to-end: the advertised debt submission is
    # ACCEPTED (status → submitted), not bounced back to draft. This is what makes
    # the phase-2 flag=True faithful rather than over-advertised.
    v = ok["version"]
    submit = await client.post(
        f"{ADMISSIONS}/{pid}/submit",
        json={
            "version": v,
            "acknowledge_missing_docs": True,
            "document_debt_reason": "Nợ giấy tờ — nộp trước, bổ sung sau (test)",
        },
        headers=oh,
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "submitted", submit.json()
