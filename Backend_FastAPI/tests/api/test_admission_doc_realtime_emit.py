"""ADM-032 — verify cross-tab realtime ``data_updated`` emit on the 5
document mutation routes.

Contract under test
-------------------
1. Each successful mutation emits exactly ONE ``data_updated`` event
   with ``resource_type="admission_profile"``, ``operation="update"``,
   ``resource_id=<profile_id>`` and ``data.document_action`` matching
   the route.
2. ``upload`` and ``reset`` schedule emit AFTER ``finalize(True)`` —
   if commit fails, ``finalize(False)`` runs and emit MUST NOT fire
   (other tabs would refetch and observe rolled-back state).
3. ``reset_document`` mutation response carries the populated
   computed fields (G2 parity bundled into ADM-032 PR — closes the
   gap PR #169 missed for this one service).

Mocking strategy
----------------
Patch ``app.routers.admissions._emit_realtime_update`` with an
``AsyncMock``. The router calls the helper inside a thin
``_emit_admission_doc_mutation`` wrapper, so asserting on the inner
helper directly counts ``await``s 1:1 with mutation success.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"

# Path to the helper we mock — keep this string centralised so a
# future rename of the router-level wrapper surfaces here loudly
# instead of silently no-oping the test.
_EMIT_HELPER = "app.routers.admissions._emit_realtime_update"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(
        AuthURLs.LOGIN, data={"username": username, "password": password}
    )
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def realtime_config(seed_lead_dependencies: dict):
    """Self-contained admission path + 1 upload-required + 1 paper-only doc."""
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
            dt_upload = models.ConfigDocumentType(
                code=f"up_{ts}", name=f"UP_{ts}", display_order=1
            )
            dt_paper = models.ConfigDocumentType(
                code=f"paper_{ts}", name=f"PAPER_{ts}", display_order=2
            )
            s.add_all([dt_upload, dt_paper])
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
            ai = models.OfferingAcademicInfo(
                offering_id=po.id,
                academic_year=2026,
                tuition_fee_per_year=5000000,
                annual_admission_quota=100,
                is_published=True,
            )
            s.add(ai)
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
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(s, academic_year=2026)
            ap = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=am.id,
                admission_round_id=round_id,
                criteria_id=ac.id,
                status="active",
                display_name=f"RT {ts}",
                display_order=0,
                visibility="public",
            )
            s.add(ap)
            await s.flush()
            dg = models.DocumentGroup(
                offering_type_id=ot.id,
                admission_method_id=am.id,
                code=f"dg_{ts}",
                name=f"DG_{ts}",
                is_active=True,
            )
            s.add(dg)
            await s.flush()
            s.add_all(
                [
                    models.DocumentGroupItem(
                        group_id=dg.id,
                        document_type_id=dt_upload.id,
                        is_mandatory=True,
                        requires_upload=True,
                        submission_format="photo",
                        display_order=1,
                    ),
                    models.DocumentGroupItem(
                        group_id=dg.id,
                        document_type_id=dt_paper.id,
                        is_mandatory=True,
                        requires_upload=False,
                        submission_format="photo",
                        display_order=2,
                    ),
                ]
            )
            await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "upload_doc_code": dt_upload.code,
        "paper_doc_code": dt_paper.code,
    }


async def _create_profile(client, admin_token_headers, officer_user_in_db, cfg, suffix):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (
        await client.post(
            LeadsURLs.LEADS,
            json={
                "full_name": f"RT {suffix}",
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
    prof = (
        await client.post(
            ADMISSIONS,
            json={
                "lead_id": lead["id"],
                "admission_method_id": cfg["method_id"],
            },
            headers=admin_token_headers,
        )
    ).json()
    return prof


def _assert_emit_called_once(
    mock: AsyncMock,
    *,
    profile_id: int,
    document_action: str,
    doc_code: str,
) -> None:
    """Assert the realtime emit fired exactly once with the expected payload."""
    assert mock.await_count == 1, (
        f"Expected exactly 1 emit, got {mock.await_count}. "
        f"Calls: {mock.await_args_list}"
    )
    kwargs = mock.await_args.kwargs
    assert kwargs["resource_type"] == "admission_profile", kwargs
    assert kwargs["operation"] == "update", kwargs
    assert kwargs["resource_id"] == profile_id, kwargs
    payload = kwargs.get("data") or {}
    assert payload.get("document_action") == document_action, payload
    assert payload.get("doc_code") == doc_code, payload


# =============================================================================
# Happy-path: each mutation emits once
# =============================================================================


@pytest.mark.asyncio
async def test_upload_emits_data_updated_after_commit(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "upload"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
            headers=oh,
            files={"file": ("u.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            data={"actual_submission_format": "photo"},
        )
        assert resp.status_code in (200, 201), resp.text

    _assert_emit_called_once(
        mock_emit,
        profile_id=pid,
        document_action="upload",
        doc_code=realtime_config["upload_doc_code"],
    )


@pytest.mark.asyncio
async def test_paper_submitted_emits_data_updated(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "paper"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{realtime_config['paper_doc_code']}/paper-submitted",
            headers=oh,
            json={"actual_submission_format": "photo"},
        )
        assert resp.status_code in (200, 201), resp.text

    _assert_emit_called_once(
        mock_emit,
        profile_id=pid,
        document_action="paper_submitted",
        doc_code=realtime_config["paper_doc_code"],
    )


@pytest.mark.asyncio
async def test_verify_emits_data_updated(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "verify"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # Officer uploads first (sets doc to 'uploaded' so verify is allowed).
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": ("v.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    admin = await _login(client, "testadmin", "AdminPassword!123")
    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.patch(
            f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/verify-format",
            headers=admin,
            json={"format": "photo"},
        )
        assert resp.status_code == 200, resp.text

    _assert_emit_called_once(
        mock_emit,
        profile_id=pid,
        document_action="verify",
        doc_code=realtime_config["upload_doc_code"],
    )


@pytest.mark.asyncio
async def test_reject_emits_data_updated(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "reject"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": ("r.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    admin = await _login(client, "testadmin", "AdminPassword!123")
    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/reject",
            headers=admin,
            json={"reason": "Bản scan mờ, vui lòng upload lại bản rõ hơn"},
        )
        assert resp.status_code == 200, resp.text

    _assert_emit_called_once(
        mock_emit,
        profile_id=pid,
        document_action="reject",
        doc_code=realtime_config["upload_doc_code"],
    )


@pytest.mark.asyncio
async def test_reset_emits_data_updated_and_response_parity(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    """Reset emits + (Q16f bundled) response carries the populated
    computed surface (``permissions`` etc.) instead of schema defaults.
    """
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "reset"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": ("rst.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    admin = await _login(client, "testadmin", "AdminPassword!123")
    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/reset",
            headers=admin,
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

    _assert_emit_called_once(
        mock_emit,
        profile_id=pid,
        document_action="reset",
        doc_code=realtime_config["upload_doc_code"],
    )

    # G2 parity (bundled): reset response must match a subsequent GET
    # on the computed surface — anchor against schema defaults like
    # ``permissions={}`` / ``available_actions=[]``.
    fetched = (await client.get(f"{ADMISSIONS}/{pid}", headers=admin)).json()
    assert body[
        "permissions"
    ], "reset response permissions={} — _populate_response_fields not wired"
    for field in (
        "permissions",
        "available_actions",
        "eligibility_status",
        "step_status",
        "completion_percent",
        "validation_errors",
        "assigned_officer_name",
    ):
        assert body.get(field) == fetched.get(field), (
            f"reset response drifts from GET on {field}: "
            f"mutation={body.get(field)!r} vs GET={fetched.get(field)!r}"
        )


# =============================================================================
# Failure paths: emit MUST NOT fire if commit/finalize fails
# =============================================================================


@pytest.mark.asyncio
async def test_upload_does_not_emit_when_commit_fails(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    """If ``db.commit()`` raises, the router calls ``finalize(False)``
    and re-raises BEFORE the emit line. Anchor: a future change that
    moves the emit ABOVE the commit (or skips the re-raise) would
    surface here.
    """
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, realtime_config, "fail_commit"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # Patch the AsyncSession.commit at the symbol the router uses to
    # raise once. The router catches, calls ``finalize(False)``, then
    # re-raises. We assert emit was NOT awaited.
    from sqlalchemy.ext.asyncio import AsyncSession

    real_commit = AsyncSession.commit

    async def _failing_commit(self):
        raise RuntimeError("simulated commit failure")

    # ASGITransport propagates the uncaught exception through the test
    # boundary (no FastAPI 500 handler in this test setup), so wrap the
    # call. The contract under test is "emit MUST NOT fire", not the
    # HTTP status code.
    with patch.object(AsyncSession, "commit", _failing_commit), patch(
        _EMIT_HELPER, new_callable=AsyncMock
    ) as mock_emit:
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            await client.post(
                f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
                headers=oh,
                files={"file": ("nc.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
                data={"actual_submission_format": "photo"},
            )
    AsyncSession.commit = real_commit

    assert mock_emit.await_count == 0, (
        "Emit fired despite commit failure — "
        "tabs would refetch and observe rolled-back state"
    )


@pytest.mark.asyncio
async def test_reset_does_not_emit_when_finalize_raises(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    realtime_config: dict,
):
    """If ``finalize(True)`` raises (e.g. file deletion fails on a
    locked file), the emit line is unreachable. Anchor: future
    refactor that swallows finalize errors must not silently fire
    emit afterward.
    """
    prof = await _create_profile(
        client,
        admin_token_headers,
        officer_user_in_db,
        realtime_config,
        "fail_finalize",
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # Upload first so reset has a file to delete.
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/upload",
        headers=oh,
        files={"file": ("fn.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    # Patch the service's reset_document so the returned ``finalize``
    # raises. We keep the original behaviour for the profile mutation
    # half (so commit succeeds) and only break the post-commit hook.
    from app.services import admission_service as svc

    original_reset = svc.reset_document

    async def reset_with_failing_finalize(*args, **kwargs):
        profile, _orig_finalize = await original_reset(*args, **kwargs)

        async def _bad_finalize(committed: bool) -> None:
            if committed:
                raise OSError("simulated finalize failure")

        return profile, _bad_finalize

    admin = await _login(client, "testadmin", "AdminPassword!123")
    with patch.object(svc, "reset_document", reset_with_failing_finalize), patch(
        _EMIT_HELPER, new_callable=AsyncMock
    ) as mock_emit:
        with pytest.raises(OSError, match="simulated finalize failure"):
            await client.post(
                f"{ADMISSIONS}/{pid}/documents/{realtime_config['upload_doc_code']}/reset",
                headers=admin,
                json={},
            )

    assert mock_emit.await_count == 0, (
        "Emit fired despite finalize failure — "
        "other tabs would observe an inconsistent post-reset state"
    )
