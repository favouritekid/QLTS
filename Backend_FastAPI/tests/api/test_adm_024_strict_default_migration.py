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

⚠️ RUN THIS FILE ON ITS OWN, SEQUENTIALLY
-----------------------------------------
Two reasons, both global side effects:

1. ``_run_migration_upgrade`` executes ``UPDATE admission_path SET
   allow_unverified_submission = FALSE`` with NO id predicate — it flips
   EVERY row in the table, including paths another test seeded as legacy.
2. ``test_migration_preserves_inflight_profile_snapshots`` runs
   ``ALTER TABLE admission_profile DISABLE TRIGGER
   enforce_applied_rules_immutability`` — a table-level DDL that suspends
   the guard for every concurrent session until it is re-enabled.

Neither is scoped to this test's own rows, so running this file in parallel
with (or interleaved into) another admission suite can silently corrupt the
other suite's fixtures. Give it its own pytest invocation, no ``-n``.

Submit chain
------------
``_seed_path`` builds on ``tests/fixtures/builders.seed_submittable_offering_config``
— the proven #337 recipe. Rolling its own chain (as this file used to) left
out ``OfferingAdmissionConfig`` and ``MajorProgram.degree_level_id``, so
``create_profile`` stored ``offering_admission_config_id = NULL``
(app/services/admission_service.py:4854-4869) and ``submit`` fail-closed with
``CONFIG_GAP_TARGET_LEVEL`` (app/services/admission_service.py:6424-6430)
BEFORE the document rule under test ever ran.
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


ACADEMIC_YEAR = 2026


async def _seed_path(session, *, allow_unverified: bool, unit_id: int) -> dict:
    """Seed one SUBMITTABLE admission path with a single mandatory document.

    Built on ``seed_submittable_offering_config`` (the #337 recipe) rather than
    a hand-rolled chain, so the path carries everything ``submit_and_evaluate``
    needs BEFORE the document rule:

    * ``OfferingAdmissionConfig`` on (academic_info, criteria) — the row
      ``create_profile`` looks up to fill ``offering_admission_config_id``
      (app/services/admission_service.py:4854-4869). Missing ⇒ submit raises
      ``CONFIG_GAP_TARGET_LEVEL`` (app/services/admission_service.py:6424-6430).
    * ``MajorProgram.degree_level_id`` + ``ProgramOffering.offering_type_id`` —
      what ``derive_target_level_and_type`` reads (app/services/priority_service.py:976,996).
    * a ``VnSchool`` + ``VnSchoolKvAssignment`` so the THPT academic_history
      entry resolves a KV instead of ``KV_UNRESOLVED``.

    On top of that this helper adds ONLY the bits ADM-024 is about: the path
    with the flag under test, plus one mandatory upload-required doc — so the
    document rule is the sole remaining gate and a blocked submit can only mean
    the doc rule blocked it.

    The caller owns the transaction; must be paired with one
    ``ensure_submittable_ward()`` before any profile is created.
    """
    from tests.fixtures.builders import (
        AdmissionRoundBuilder,
        _next_id,
        seed_submittable_offering_config,
    )

    seed = await seed_submittable_offering_config(
        session, unit_id=unit_id, academic_year=ACADEMIC_YEAR
    )
    round_id = await AdmissionRoundBuilder.get_or_create_default_round(
        session, academic_year=ACADEMIC_YEAR
    )

    # Monotonic suffix (NOT a seconds/ms timestamp): the three paths of one
    # fixture are seeded inside a single call, and `code` columns are UNIQUE.
    sid = _next_id()

    ap = models.AdmissionPath(
        academic_info_id=seed["academic_info_id"],
        admission_method_id=seed["method_id"],
        admission_round_id=round_id,
        criteria_id=seed["criteria_id"],
        status="active",
        display_name=f"ADM024 {sid}",
        display_order=0,
        visibility="public",
        allow_unverified_submission=allow_unverified,
    )
    session.add(ap)
    await session.flush()

    dt = models.ConfigDocumentType(
        code=f"tcc_{sid}", name=f"TCC_{sid}", display_order=1
    )
    session.add(dt)
    await session.flush()
    dg = models.DocumentGroup(
        offering_type_id=seed["offering_type_id"],
        admission_method_id=seed["method_id"],
        code=f"dg_{sid}",
        name=f"DG_{sid}",
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
        "offering_id": seed["offering_id"],
        "method_id": seed["method_id"],
        "path_id": ap.id,
        "doc_code": dt.code,
        # Round contract hardening (plan v4): POST /api/admissions now REQUIRES
        # both (app/schemas/admission.py:470, :482).
        "round_id": round_id,
        "academic_year": ACADEMIC_YEAR,
        # KV layer — the academic_history entry must point at THIS school.
        "school_id": seed["school_id"],
    }


@pytest_asyncio.fixture
async def adm024_paths(seed_lead_dependencies: dict):
    """Seed three paths simulating prod-like legacy state.

    - Two paths with allow_unverified_submission=TRUE (legacy default)
    - One path with allow_unverified_submission=FALSE (already strict)

    Lets us assert the migration only touches legacy rows.

    Each path owns its own offering/academic_info/method/criteria chain, so the
    3-col UNIQUE (admission_round_id, academic_info_id, admission_method_id) on
    ``admission_path`` is satisfied even though all three share DOT_1/2026.
    """
    from tests.fixtures.builders import ensure_submittable_ward

    unit_id = seed_lead_dependencies["unit_id"]
    # Gap #3 submit gate: one CURRENT-era ward backing
    # ``SUBMITTABLE_PERMANENT_ADDRESS``. Own session — call before the
    # transaction below so it is committed and visible to the API.
    await ensure_submittable_ward()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            legacy_a = await _seed_path(s, allow_unverified=True, unit_id=unit_id)
            legacy_b = await _seed_path(s, allow_unverified=True, unit_id=unit_id)
            already_strict = await _seed_path(s, allow_unverified=False, unit_id=unit_id)
    return {
        "unit_id": unit_id,
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
        json={
            "lead_id": lead["id"],
            "admission_method_id": cfg["path"]["method_id"],
            # Round contract hardening (plan v4, 2026-05-25): both fields are
            # REQUIRED — app/schemas/admission.py:470 and :482. Omitting them
            # 422s at the Pydantic boundary, before create_profile runs.
            "admission_round_id": cfg["path"]["round_id"],
            "academic_year": cfg["path"]["academic_year"],
        },
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


async def _fill_personal(client, oh, pid, *, school_id):
    """Clear every NON-document submit gate so the outcome of ``/submit``
    hinges purely on the document rule this file is about.

    Beyond the personal columns the old version filled, this now supplies:
      * ``**SUBMITTABLE_PERMANENT_ADDRESS`` — the Gap #3 gate wants
        permanent_province/ward + a CURRENT-era ``permanent_commune_code``;
      * ``cultural_education_level='graduated_thpt'`` + ``vocational_qualification``
        — the eligibility check against the derived target level;
      * an academic_history THPT row carrying ``school_id`` (+ level/grade_to)
        so KV resolves via ``VnSchoolKvAssignment`` instead of ``KV_UNRESOLVED``.

    The PUT is asserted: silently swallowing a 4xx here is exactly how a
    "submit blocked" assertion goes green for the wrong reason.
    """
    from tests.fixtures.builders import SUBMITTABLE_PERMANENT_ADDRESS

    ts_cccd = f"{int(datetime.now().timestamp()) % 10**12:012d}"
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    r = await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
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
            "family_info": [
                {"relationship": "Cha", "full_name": "P", "phone": "0901111111", "is_primary_guardian": True}
            ],
            "academic_history": [
                {
                    "school_name": "THPT Submittable",
                    "year_from": 2020,
                    "year_to": 2024,
                    "gpa": 8.0,
                    "graduation_type": "THPT",
                    "level": "THPT",
                    "grade_to": 12,
                    "school_id": school_id,
                }
            ],
            "admission_scores": {"gpa": 8.0, "subject_scores": {}},
        },
        headers=oh,
    )
    assert r.status_code == 200, f"_fill_personal PUT failed: {r.status_code} {r.text}"


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
    await _fill_personal(client, oh, pid, school_id=adm024_paths["legacy_a"]["school_id"])
    upload = await _officer_upload(client, oh, pid, adm024_paths["legacy_a"]["doc_code"])
    assert upload.status_code in (200, 201), upload.text

    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    resp = await client.post(f"{ADMISSIONS}/{pid}/submit", json={"version": v}, headers=oh)
    # 200 alone is NOT success: /submit answers 200 + status='draft' +
    # validation_errors when a gate blocks (see the strict test below). The
    # grandfather claim is only proven by the resulting STATE.
    assert resp.status_code == 200, f"Legacy snapshot must still submit: {resp.text[:300]}"
    body = resp.json()
    assert body["status"] == "submitted", (
        "Grandfathered legacy snapshot must actually transition to submitted, "
        f"got status={body['status']} errors={body.get('validation_errors')}"
    )


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
    await _fill_personal(client, oh, pid, school_id=adm024_paths["legacy_b"]["school_id"])

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
    blocked_body = blocked.json()
    assert blocked_body["status"] == "draft", (
        f"Strict snapshot must block submit, got status={blocked_body['status']}"
    )
    # status='draft' alone does NOT prove the STRICT DOC RULE blocked it — any
    # unmet gate (CONFIG_GAP, KV, missing address) parks the profile in draft
    # too. Require the verify-document message so this case really touches the
    # contract ADM-024 guards.
    blocked_errors = blocked_body.get("validation_errors") or []
    assert any(
        "xác minh" in e.lower() or "verify" in e.lower() for e in blocked_errors
    ), (
        "Strict submit must be blocked by the document-verification rule, not "
        f"by some other unmet gate. validation_errors={blocked_errors}"
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
