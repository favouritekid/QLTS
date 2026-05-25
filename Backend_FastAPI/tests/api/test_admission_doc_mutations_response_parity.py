"""G2 (ADM-032 partial): doc mutation responses must carry the same
computed fields as a subsequent GET — no schema-default placeholders.

Before this fix, ``upload_document``, ``mark_paper_submitted`` and
``confirm_document_format`` services only called
``_compute_frontend_fields``, leaving ``permissions``,
``available_actions``, ``eligibility_status``, ``step_status``,
``completion_percent``, ``assigned_officer_name`` and
``assigned_reviewer_name`` at schema defaults on the mutation
response. The FE had to refetch via GET to render the row, which
killed optimistic update.

This test pins the contract: every doc-mutation endpoint that
returns ``AdmissionProfileResponse`` must populate the full computed
surface so the FE can trust the response.

Test strategy
-------------
Run a mutation, capture the response, then immediately GET the same
profile and diff the computed-field surface. The shapes must match.
We assert the diff (set-symmetric on values) rather than asserting
hard-coded "permissions={...}" so the test stays robust to future
permission-matrix changes.
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

# The fields that ``_populate_response_fields`` populates on a profile
# and that a subsequent GET would also populate. If a mutation skips
# the helper, these come back as schema defaults; if the helper runs,
# they match the GET response.
COMPUTED_SURFACE = (
    "permissions",
    "available_actions",
    "eligibility_status",
    "step_status",
    "completion_percent",
    "validation_errors",
    "assigned_officer_name",
)


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def parity_config(seed_lead_dependencies: dict):
    """Seed a self-contained admission path + one upload + one paper-only
    document so all three mutation endpoints have a real target."""
    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(code=f"tq_{ts}", name=f"TQ_{ts}", display_order=1)
            s.add(ot); await s.flush()
            dt_upload = models.ConfigDocumentType(
                code=f"tcc_up_{ts}", name=f"TCC_UP_{ts}", display_order=1
            )
            dt_paper = models.ConfigDocumentType(
                code=f"tcc_paper_{ts}", name=f"TCC_PAPER_{ts}", display_order=2
            )
            s.add_all([dt_upload, dt_paper]); await s.flush()
            po = models.ProgramOffering(
                offering_type=f"TQ_{ts}", program_id=mpid, offering_type_id=ot.id,
                is_active=True, duration_semesters=6,
            )
            s.add(po); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=po.id, academic_year=2026,
                tuition_fee_per_year=5000000, annual_admission_quota=100,
                is_published=True,
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
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id,
                admission_round_id=round_id, criteria_id=ac.id,
                status="active", display_name=f"Parity {ts}",
                display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
            dg = models.DocumentGroup(
                offering_type_id=ot.id, admission_method_id=am.id,
                code=f"dg_{ts}", name=f"DG_{ts}", is_active=True,
            )
            s.add(dg); await s.flush()
            s.add_all([
                models.DocumentGroupItem(
                    group_id=dg.id, document_type_id=dt_upload.id,
                    is_mandatory=True, requires_upload=True,
                    submission_format="photo", display_order=1,
                ),
                models.DocumentGroupItem(
                    group_id=dg.id, document_type_id=dt_paper.id,
                    is_mandatory=True, requires_upload=False,
                    submission_format="photo", display_order=2,
                ),
            ])
            await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "upload_doc_code": dt_upload.code,
        "paper_doc_code": dt_paper.code,
        # Round contract hardening (plan v4): now-required admission_round_id.
        "round_id": round_id,
    }


async def _create_profile(client, admin_token_headers, officer_user_in_db, cfg, suffix):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (await client.post(LeadsURLs.LEADS, json={
        "full_name": f"G2 Parity {suffix}",
        "phone": phone,
        "source": "website",
        "unit_id": cfg["unit_id"],
        "assigned_officer_id": officer_user_in_db["id"],
        "offering_id": cfg["offering_id"],
    }, headers=admin_token_headers)).json()
    await client.post(
        f"{LeadsURLs.LEADS}/{lead['id']}/consultations",
        json={"status_id": INITIAL_LEAD_STATUS_ID, "method": "phone", "notes": "Pre-admission"},
        headers=admin_token_headers,
    )
    prof = (await client.post(ADMISSIONS, json={
        "lead_id": lead["id"],
        "admission_method_id": cfg["method_id"],
        "admission_round_id": cfg["round_id"],
        "academic_year": 2026,
    }, headers=admin_token_headers)).json()
    return prof


def _diff_surface(mutation_resp: dict, get_resp: dict) -> list[str]:
    """Return the names of computed fields whose values diverge between
    the mutation response and a subsequent GET. Empty list = parity."""
    drift = []
    for field in COMPUTED_SURFACE:
        if mutation_resp.get(field) != get_resp.get(field):
            drift.append(
                f"{field}: mutation={mutation_resp.get(field)!r} "
                f"vs GET={get_resp.get(field)!r}"
            )
    return drift


@pytest.mark.asyncio
async def test_upload_document_response_matches_get(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    parity_config: dict,
):
    """upload_document mutation response must carry the same computed
    fields as a subsequent GET. Without _populate_response_fields the
    response had permissions={}, available_actions=[],
    eligibility_status='pending' instead of the real values."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "upload"
    )
    pid = prof["id"]
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])

    upload_resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{parity_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": (f"u.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload_resp.status_code in (200, 201), upload_resp.text
    mutation = upload_resp.json()

    get_resp = await client.get(f"{ADMISSIONS}/{pid}", headers=oh)
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    drift = _diff_surface(mutation, fetched)
    assert not drift, (
        "upload_document response must match subsequent GET on computed "
        f"fields. Drift: {drift}"
    )
    # Anchor: permissions must NOT be the empty schema default.
    assert mutation["permissions"], (
        "upload_document response permissions={} — _populate_response_fields "
        "regression. Check that the service runs the helper after db.flush()."
    )


@pytest.mark.asyncio
async def test_mark_paper_submitted_response_matches_get(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    parity_config: dict,
):
    """mark_paper_submitted mutation response must carry the same
    computed fields as a subsequent GET."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "paper"
    )
    pid = prof["id"]
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])

    paper_resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{parity_config['paper_doc_code']}/paper-submitted",
        headers=oh,
        json={"actual_submission_format": "photo"},
    )
    assert paper_resp.status_code in (200, 201), paper_resp.text
    mutation = paper_resp.json()

    get_resp = await client.get(f"{ADMISSIONS}/{pid}", headers=oh)
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    drift = _diff_surface(mutation, fetched)
    assert not drift, (
        "mark_paper_submitted response must match subsequent GET. "
        f"Drift: {drift}"
    )
    assert mutation["permissions"], (
        "mark_paper_submitted permissions={} — _populate_response_fields "
        "regression."
    )


@pytest.mark.asyncio
async def test_upload_preserves_subject_scores(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    parity_config: dict,
):
    """Side-effect guard: ``_populate_response_fields`` runs
    ``_calculate_and_update_totals`` which recomputes
    ``total_score`` / ``average_score`` / ``snapshot_score`` from the
    snapshot rules. Doc upload must NOT zero those out — recomputed
    must equal what a fresh GET would compute.

    Catches a regression where the helper falls back to
    ``profile.subject_scores`` (lazy-loaded → empty in service path)
    instead of fetching via the explicit ``get_profile_scores`` query.
    """
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "scores"
    )
    pid = prof["id"]
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])

    # Seed subject scores via the profile update endpoint (the same
    # path the FE uses). Method on this fixture path is gpa_based on
    # the criteria (min_gpa=0, scoring_method=average) — populate gpa
    # so the totals helper has something to compute against.
    v = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["version"]
    await client.put(
        f"{ADMISSIONS}/{pid}",
        json={
            "version": v,
            "academic_history": [
                {"school_name": "THPT", "year_from": 2019, "year_to": 2022,
                 "gpa": 8.5, "graduation_type": "THPT"},
            ],
            "admission_scores": {"gpa": 8.5, "subject_scores": {}},
        },
        headers=oh,
    )

    upload_resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{parity_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": (f"u.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload_resp.status_code in (200, 201), upload_resp.text
    mutation = upload_resp.json()

    fetched = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()

    # Score surface must match GET — guards against the helper running
    # against an empty subject_scores list and zeroing the totals.
    for field in ("total_score", "average_score", "admission_scores"):
        assert mutation.get(field) == fetched.get(field), (
            f"upload_document tampered with {field}: "
            f"mutation={mutation.get(field)!r} vs GET={fetched.get(field)!r}"
        )


@pytest.mark.asyncio
async def test_confirm_document_format_response_matches_get(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    parity_config: dict,
):
    """confirm_document_format (verify) mutation response must carry the
    same computed fields as a subsequent GET."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "verify"
    )
    pid = prof["id"]
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])

    # Officer uploads first so the doc has an 'uploaded' status to verify.
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{parity_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": (f"v.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    # Admin verifies (officer cannot per PR #5 guard).
    admin = await _login(client, "testadmin", "AdminPassword!123")
    verify_resp = await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{parity_config['upload_doc_code']}/verify-format",
        headers=admin,
        json={"format": "photo"},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    mutation = verify_resp.json()

    get_resp = await client.get(f"{ADMISSIONS}/{pid}", headers=admin)
    assert get_resp.status_code == 200
    fetched = get_resp.json()

    drift = _diff_surface(mutation, fetched)
    assert not drift, (
        "confirm_document_format response must match subsequent GET. "
        f"Drift: {drift}"
    )
    assert mutation["permissions"], (
        "confirm_document_format permissions={} — _populate_response_fields "
        "regression."
    )
