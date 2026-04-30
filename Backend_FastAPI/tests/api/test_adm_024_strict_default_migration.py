"""ADM-024: validate the path-level strict-default migration.

The migration ``admstrict01_pr6_flip_paths_to_strict.py`` flips
``allow_unverified_submission`` from TRUE to FALSE on every existing
``admission_path`` row, realising PR #6's strict default. This test
file pins three behaviours that matter post-deploy:

1. The migration's UPDATE flips legacy rows but leaves
   already-strict rows alone (idempotent / non-destructive).
2. In-flight profiles created before the migration retain their
   snapshotted ``allow_unverified_submission = true`` and continue
   to submit with uploaded-only docs (snapshot immutability).
3. New profiles created on a flipped path snapshot
   ``allow_unverified_submission = false``; submit blocks on
   uploaded-only docs and unblocks once docs are verified.

Test DB note
------------
Per memory ``reference_test_db_schema_source``, the test DB uses
``Base.metadata.create_all()`` rather than alembic. We don't invoke
alembic from pytest — we execute the migration's SQL directly via
``MIGRATION_UPGRADE_SQL`` (kept in sync by hand). If the migration's
SQL ever changes, update both files together.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"

# Mirror of admstrict01_pr6_flip_paths_to_strict.upgrade(). Kept inline
# so tests don't import the alembic module (which expects op.execute
# context). If the migration SQL changes, update this string too.
MIGRATION_UPGRADE_SQL = """
    UPDATE admission_path
    SET allow_unverified_submission = FALSE
    WHERE allow_unverified_submission = TRUE
"""


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


async def _seed_path(session, *, allow_unverified: bool, mpid: int, ts_suffix: str) -> dict:
    """Seed a self-contained admission path with one mandatory document.

    Returns the ids/codes the test needs to drive the API. Mirrors the
    minimal scaffolding from ``test_admission_submit_requires_verified_docs``
    so tests stay self-contained.
    """
    ot = models.ConfigOfferingType(code=f"tq_{ts_suffix}", name=f"TQ_{ts_suffix}", display_order=1)
    session.add(ot)
    await session.flush()
    dt = models.ConfigDocumentType(code=f"tcc_{ts_suffix}", name=f"TCC_{ts_suffix}", display_order=1)
    session.add(dt)
    await session.flush()
    po = models.ProgramOffering(
        offering_type=f"TQ_{ts_suffix}",
        program_id=mpid,
        offering_type_id=ot.id,
        is_active=True,
        duration_semesters=6,
    )
    session.add(po)
    await session.flush()
    ai = models.OfferingAcademicInfo(
        offering_id=po.id,
        academic_year=2026,
        tuition_fee_per_year=5000000,
        annual_admission_quota=100,
        is_published=True,
    )
    session.add(ai)
    await session.flush()
    am = models.AdmissionMethod(
        code=f"hb_{ts_suffix}",
        name=f"HB_{ts_suffix}",
        requires_gpa=True,
        requires_subject_scores=False,
        is_active=True,
    )
    session.add(am)
    await session.flush()
    ac = models.AdmissionCriteria(
        method_id=am.id,
        code=f"TC_{ts_suffix}",
        name=f"TC_{ts_suffix}",
        min_gpa=0.0,
        scoring_method="average",
        subject_selection_mode="fixed",
        policy_version="2026.1",
        is_active=True,
    )
    session.add(ac)
    await session.flush()
    ap = models.AdmissionPath(
        academic_info_id=ai.id,
        admission_method_id=am.id,
        criteria_id=ac.id,
        status="active",
        display_name=f"ADM024 {ts_suffix}",
        display_order=0,
        visibility="public",
        allow_unverified_submission=allow_unverified,
    )
    session.add(ap)
    await session.flush()
    dg = models.DocumentGroup(
        offering_type_id=ot.id,
        admission_method_id=am.id,
        code=f"dg_{ts_suffix}",
        name=f"DG_{ts_suffix}",
        is_active=True,
    )
    session.add(dg)
    await session.flush()
    dgi = models.DocumentGroupItem(
        group_id=dg.id,
        document_type_id=dt.id,
        is_mandatory=True,
        requires_upload=True,
        submission_format="photo",
        display_order=1,
    )
    session.add(dgi)
    await session.flush()
    return {
        "offering_id": po.id,
        "method_id": am.id,
        "path_id": ap.id,
        "doc_code": dt.code,
    }


@pytest_asyncio.fixture
async def adm024_paths(seed_lead_dependencies: dict):
    """Seed three paths simulating prod-like legacy state.

    - Two paths with allow_unverified_submission=TRUE (legacy default)
    - One path with allow_unverified_submission=FALSE (already strict)

    Lets us assert the migration only touches legacy rows.
    """
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            legacy_a = await _seed_path(s, allow_unverified=True, mpid=mpid, ts_suffix=f"a{ts}")
            legacy_b = await _seed_path(s, allow_unverified=True, mpid=mpid, ts_suffix=f"b{ts}")
            already_strict = await _seed_path(s, allow_unverified=False, mpid=mpid, ts_suffix=f"c{ts}")
    return {
        "unit_id": seed_lead_dependencies["unit_id"],
        "legacy_a": legacy_a,
        "legacy_b": legacy_b,
        "already_strict": already_strict,
    }


async def _create_draft(client, admin_token_headers, officer_user_in_db, cfg, *, full_name: str):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead_resp = await client.post(
        LeadsURLs.LEADS,
        json={
            "full_name": full_name,
            "phone": phone,
            "source": "website",
            "unit_id": cfg["unit_id"],
            "assigned_officer_id": officer_user_in_db["id"],
            "offering_id": cfg["path"]["offering_id"],
        },
        headers=admin_token_headers,
    )
    assert lead_resp.status_code in (200, 201), f"Lead create: {lead_resp.text}"
    lead = lead_resp.json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "Pre-admission"},
        headers=admin_token_headers,
    )
    prof_resp = await client.post(
        ADMISSIONS,
        json={"lead_id": lead["id"], "admission_method_id": cfg["path"]["method_id"]},
        headers=admin_token_headers,
    )
    assert prof_resp.status_code in (200, 201), f"Create profile: {prof_resp.text}"
    return prof_resp.json()


async def _officer_upload(client, oh, pid, doc_code):
    return await client.post(
        f"{ADMISSIONS}/{pid}/documents/{doc_code}/upload",
        headers=oh,
        files={"file": (f"{doc_code}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )


async def _fill_personal(client, oh, pid):
    ts_cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": v,
            "citizen_id": ts_cccd,
            "gender": "male",
            "dob": "2001-01-01",
            "nationality": "Viet Nam",
            "ethnicity": "Kinh",
            "place_of_birth": "Test",
            "family_info": [
                {"relationship": "Cha", "full_name": "P", "phone": "0901111111", "is_primary_guardian": True}
            ],
            "academic_history": [
                {"school_name": "THPT", "year_from": 2019, "year_to": 2022, "gpa": 8.0, "graduation_type": "THPT"}
            ],
            "admission_scores": {"gpa": 8.0, "subject_scores": {}},
        },
        headers=oh,
    )


async def _run_migration_upgrade() -> int:
    """Execute the migration's UPDATE statement; returns affected row count."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            result = await s.execute(text(MIGRATION_UPGRADE_SQL))
            return result.rowcount or 0


@pytest.mark.asyncio
async def test_migration_flips_legacy_paths_to_strict(adm024_paths: dict):
    """Migration flips TRUE→FALSE only; idempotent on re-run."""
    legacy_a = adm024_paths["legacy_a"]["path_id"]
    legacy_b = adm024_paths["legacy_b"]["path_id"]
    already_strict = adm024_paths["already_strict"]["path_id"]

    # Pre-migration sanity — paths in the expected initial state.
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT id, allow_unverified_submission FROM admission_path "
            "WHERE id IN (:a, :b, :c) ORDER BY id"
        ), {"a": legacy_a, "b": legacy_b, "c": already_strict})).all()
    pre = {r[0]: r[1] for r in rows}
    assert pre[legacy_a] is True
    assert pre[legacy_b] is True
    assert pre[already_strict] is False

    # First run flips both legacy rows. Other already-strict rows in
    # the DB (from this and prior tests) are not asserted on — we only
    # care that our seeded legacy rows flipped.
    affected_first = await _run_migration_upgrade()
    assert affected_first >= 2, (
        f"Expected at least the 2 seeded legacy rows to flip, got {affected_first}"
    )

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT id, allow_unverified_submission FROM admission_path "
            "WHERE id IN (:a, :b, :c) ORDER BY id"
        ), {"a": legacy_a, "b": legacy_b, "c": already_strict})).all()
    post = {r[0]: r[1] for r in rows}
    assert post[legacy_a] is False
    assert post[legacy_b] is False
    assert post[already_strict] is False, "Already-strict path must remain false"

    # Idempotency: second run touches zero of the rows we seeded.
    async with AsyncSessionLocal() as s:
        rows_after = (await s.execute(text(
            "SELECT COUNT(*) FROM admission_path "
            "WHERE id IN (:a, :b, :c) AND allow_unverified_submission = TRUE"
        ), {"a": legacy_a, "b": legacy_b, "c": already_strict})).scalar()
    assert rows_after == 0, "All seeded paths must be strict after upgrade"

    # Re-run migration; predicate matches nothing among our rows.
    await _run_migration_upgrade()
    async with AsyncSessionLocal() as s:
        still_strict = (await s.execute(text(
            "SELECT COUNT(*) FROM admission_path "
            "WHERE id IN (:a, :b, :c) AND allow_unverified_submission = FALSE"
        ), {"a": legacy_a, "b": legacy_b, "c": already_strict})).scalar()
    assert still_strict == 3


@pytest.mark.asyncio
async def test_migration_preserves_inflight_profile_snapshots(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm024_paths: dict,
):
    """Pre-migration profile keeps legacy snapshot; submit grandfathers."""
    cfg = {"unit_id": adm024_paths["unit_id"], "path": adm024_paths["legacy_a"]}

    # Create the profile while the path is still legacy (allow=true).
    prof = await _create_draft(client, admin_token_headers, officer_user_in_db, cfg, full_name="ADM024 Inflight")
    pid = prof["id"]

    # Force the snapshot to schema_version=1 + allow=true to mirror what
    # ``aa1i2j3k4l5m`` backfilled on prod. Disabling the immutability
    # trigger if present (test DB uses metadata.create_all and may not
    # carry the trigger from alembic history).
    async with AsyncSessionLocal() as s:
        async with s.begin():
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

    # Now run the migration.
    await _run_migration_upgrade()

    # Profile snapshot unchanged.
    async with AsyncSessionLocal() as s:
        row = (await s.execute(text(
            "SELECT applied_rules->>'schema_version', "
            "       applied_rules->>'allow_unverified_submission' "
            "FROM admission_profile WHERE id = :pid"
        ), {"pid": pid})).first()
    assert row[0] == "1", f"Snapshot schema_version drifted: {row[0]}"
    assert row[1] == "true", f"Snapshot allow_unverified drifted: {row[1]}"

    # Path is now strict.
    async with AsyncSessionLocal() as s:
        path_flag = (await s.execute(text(
            "SELECT allow_unverified_submission FROM admission_path WHERE id = :pid"
        ), {"pid": adm024_paths["legacy_a"]["path_id"]})).scalar()
    assert path_flag is False

    # Legacy profile still submits with uploaded-only docs (grandfathered).
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await _fill_personal(client, oh, pid)
    upload = await _officer_upload(client, oh, pid, adm024_paths["legacy_a"]["doc_code"])
    assert upload.status_code in (200, 201), upload.text

    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert resp.status_code == 200, f"Legacy snapshot must still submit: {resp.text[:300]}"


@pytest.mark.asyncio
async def test_new_profile_post_migration_strict_with_verify_unblocks(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    adm024_paths: dict,
):
    """New profile on flipped path snapshots strict; verify unblocks submit."""
    # Run the migration first — flips legacy_b to strict.
    await _run_migration_upgrade()

    cfg = {"unit_id": adm024_paths["unit_id"], "path": adm024_paths["legacy_b"]}
    prof = await _create_draft(client, admin_token_headers, officer_user_in_db, cfg, full_name="ADM024 PostMig")
    pid = prof["id"]

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await _fill_personal(client, oh, pid)

    # Snapshot must be schema_version=2 + allow=false (post-migration default).
    detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    applied = detail.get("applied_rules") or {}
    assert applied.get("schema_version") == 2, f"Expected schema_version=2, got {applied.get('schema_version')}"
    assert applied.get("allow_unverified_submission") is False, (
        f"Post-migration profile must snapshot strict, got {applied.get('allow_unverified_submission')}"
    )

    # Uploaded-only blocks submit (status stays draft, validation_errors set).
    upload = await _officer_upload(client, oh, pid, adm024_paths["legacy_b"]["doc_code"])
    assert upload.status_code in (200, 201), upload.text
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    blocked = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "draft", (
        f"Strict snapshot must block submit, got status={blocked.json()['status']}"
    )

    # Bonus per Q15a chốt: marking the doc verified unblocks submit.
    admin = await _login(client, "testadmin", "AdminPassword!123")
    verify_resp = await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{adm024_paths['legacy_b']['doc_code']}/verify-format",
        json={"format": "photo"},
        headers=admin,
    )
    assert verify_resp.status_code == 200, verify_resp.text

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    ok = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "submitted", (
        f"Verified docs must unblock submit, got {ok.json()['status']}"
    )
