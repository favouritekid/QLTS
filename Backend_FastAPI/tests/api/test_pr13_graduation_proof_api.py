"""PR #13.4b — API + Casbin contract cho graduation-proof update endpoint.

Covers the whole officer flow for ``bang_tot_nghiep_thpt``:

1. Officer marks the paper-only graduation doc as paper-submitted with
   ``provisional_cert`` + a supplement due date → the checklist row surfaces
   ``graduation_proof_kind`` / ``supplement_due_date`` and flips
   ``can_update_graduation_kind`` on (the "nợ bằng" badge).
2. Officer later records the official diploma via the NEW endpoint
   ``POST /documents/{code}/graduation-proof`` → status unchanged, due date
   cleared, flag off.
3. Realtime ``data_updated`` emit fires once with
   ``document_action="graduation_proof_updated"`` (review finding #4).
4. ``DocumentAuditLog.extra_data`` records the proof kind on paper-submit AND
   the upgrade on update (review finding #4 — audit trail for "nợ bằng").
5. Guard: a non-graduation doc code → 400; a basic ``user`` role is denied by
   Casbin (the endpoint mirrors paper-submitted: officer ALLOW, others bounce).
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.admission_config.profile_data import (
    DocumentAuditLog,
    ProfileDocument,
)
from tests.fixtures.constants import AuthURLs, LeadsURLs


ADMISSIONS = "/api/admissions"
GRAD_CODE = "bang_tot_nghiep_thpt"
DUE = "2027-06-30"
# Mock target — the router calls this helper inside the thin
# ``_emit_admission_doc_mutation`` wrapper, so asserting on it counts
# emits 1:1 with mutation success (mirror test_admission_doc_realtime_emit).
_EMIT_HELPER = "app.routers.admissions._emit_realtime_update"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post(
        AuthURLs.LOGIN, data={"username": username, "password": password}
    )
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest_asyncio.fixture
async def graduation_config(seed_lead_dependencies: dict):
    """Admission path wired to a paper-only ``bang_tot_nghiep_thpt`` doc.

    The graduation doc type has a FIXED code (the service hard-checks it), so
    we get-or-create it; the offering/method/criteria/group are per-``ts`` to
    stay isolated. The doc is paper-only (``requires_upload=False``) so a new
    profile exposes a paper-submittable graduation row.
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
            existing = await s.execute(
                select(models.ConfigDocumentType).where(
                    models.ConfigDocumentType.code == GRAD_CODE
                )
            )
            dt_grad = existing.scalar_one_or_none()
            if dt_grad is None:
                dt_grad = models.ConfigDocumentType(
                    code=GRAD_CODE,
                    name="Bằng tốt nghiệp THPT / Giấy CN tốt nghiệp tạm thời",
                    display_order=1,
                )
                s.add(dt_grad)
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

            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026
            )
            ap = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=am.id,
                admission_round_id=round_id,
                criteria_id=ac.id,
                status="active",
                display_name=f"GRAD {ts}",
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
            s.add(
                models.DocumentGroupItem(
                    group_id=dg.id,
                    document_type_id=dt_grad.id,
                    is_mandatory=True,
                    requires_upload=False,  # paper-only graduation doc
                    submission_format="original",
                    display_order=1,
                )
            )
            await s.flush()
    return {
        "unit_id": uid,
        "offering_id": po.id,
        "method_id": am.id,
        "round_id": round_id,
    }


async def _create_profile(client, admin_token_headers, officer_user_in_db, cfg, suffix):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID

    phone = f"0988{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
    lead = (
        await client.post(
            LeadsURLs.LEADS,
            json={
                "full_name": f"GradProof {suffix}",
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
                "admission_round_id": cfg["round_id"],
                "academic_year": 2026,
            },
            headers=admin_token_headers,
        )
    ).json()
    return prof


def _grad_row(detail: dict) -> dict:
    row = next(
        (d for d in detail.get("documents_checklist", []) if d["code"] == GRAD_CODE),
        None,
    )
    assert row is not None, (
        f"graduation doc {GRAD_CODE!r} missing from checklist: "
        f"{[d['code'] for d in detail.get('documents_checklist', [])]}"
    )
    return row


async def _paper_submit_provisional(client, oh, pid):
    resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/paper-submitted",
        headers=oh,
        json={
            "actual_submission_format": "certified_copy",
            "graduation_proof_kind": "provisional_cert",
            "supplement_due_date": DUE,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_provisional_then_official_roundtrip(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    graduation_config: dict,
):
    """provisional_cert + due → official_diploma clears the "nợ bằng" debt."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, graduation_config, "rt"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # 1. Officer records the provisional certificate + supplement due date.
    await _paper_submit_provisional(client, oh, pid)

    after_submit = _grad_row(
        (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    )
    assert after_submit["graduation_proof_kind"] == "provisional_cert", after_submit
    assert after_submit["supplement_due_date"] == DUE, after_submit
    assert after_submit["can_update_graduation_kind"] is True, after_submit
    assert after_submit["status"] == "paper_submitted", after_submit

    # 2. Officer upgrades to the official diploma via the NEW endpoint.
    upd = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/graduation-proof",
        headers=oh,
        json={"kind": "official_diploma"},
    )
    assert upd.status_code == 200, upd.text

    after_update = _grad_row(
        (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()
    )
    assert after_update["graduation_proof_kind"] == "official_diploma", after_update
    assert after_update["supplement_due_date"] is None, after_update
    assert after_update["can_update_graduation_kind"] is False, after_update
    # Status must NOT change — the doc was already received.
    assert after_update["status"] == "paper_submitted", after_update


@pytest.mark.asyncio
async def test_update_emits_data_updated(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    graduation_config: dict,
):
    """The update endpoint emits exactly one ``graduation_proof_updated``."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, graduation_config, "emit"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    await _paper_submit_provisional(client, oh, pid)

    with patch(_EMIT_HELPER, new_callable=AsyncMock) as mock_emit:
        resp = await client.post(
            f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/graduation-proof",
            headers=oh,
            json={"kind": "official_diploma"},
        )
        assert resp.status_code == 200, resp.text

    assert mock_emit.await_count == 1, (
        f"Expected exactly 1 emit, got {mock_emit.await_count}: "
        f"{mock_emit.await_args_list}"
    )
    kwargs = mock_emit.await_args.kwargs
    assert kwargs["resource_type"] == "admission_profile", kwargs
    assert kwargs["operation"] == "update", kwargs
    assert kwargs["resource_id"] == pid, kwargs
    payload = kwargs.get("data") or {}
    assert payload.get("document_action") == "graduation_proof_updated", payload
    assert payload.get("doc_code") == GRAD_CODE, payload


@pytest.mark.asyncio
async def test_paper_submit_and_update_write_audit_extra_data(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    graduation_config: dict,
):
    """extra_data carries the proof kind on submit + the upgrade on update."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, graduation_config, "audit"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    await _paper_submit_provisional(client, oh, pid)
    upd = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/graduation-proof",
        headers=oh,
        json={"kind": "official_diploma"},
    )
    assert upd.status_code == 200, upd.text

    async with AsyncSessionLocal() as s:
        logs = (
            await s.execute(
                select(DocumentAuditLog)
                .join(
                    ProfileDocument,
                    DocumentAuditLog.profile_document_id == ProfileDocument.id,
                )
                .where(ProfileDocument.profile_id == pid)
                .order_by(DocumentAuditLog.created_at)
            )
        ).scalars().all()

    extras = [dict(log.extra_data or {}) for log in logs]
    # Paper-submit logged the provisional kind + the supplement due date.
    submit_extra = next(
        (e for e in extras if e.get("graduation_proof_kind") == "provisional_cert"),
        None,
    )
    assert submit_extra is not None, f"no paper-submit proof-kind audit: {extras}"
    assert submit_extra.get("supplement_due_date") == DUE, submit_extra
    # Update logged the upgrade flag + the new kind.
    update_extra = next(
        (e for e in extras if e.get("graduation_proof_update") is True), None
    )
    assert update_extra is not None, f"no graduation-proof update audit: {extras}"
    assert update_extra.get("new_kind") == "official_diploma", update_extra


@pytest.mark.asyncio
async def test_update_rejects_non_graduation_doc(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    graduation_config: dict,
):
    """Any doc code other than bang_tot_nghiep_thpt → 400 (BusinessRule)."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, graduation_config, "guard"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/hoc_ba_thpt/graduation-proof",
        headers=oh,
        json={"kind": "official_diploma"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_regular_user_denied_by_casbin(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    regular_user_token_headers: dict,
    graduation_config: dict,
):
    """A basic ``user`` role has no graduation-proof policy → Casbin bounces.

    Mirrors paper-submitted: officer ALLOW, others denied. Accept 403 or 404
    (the latter is the IDOR-safe shape some gates return)."""
    # The ``regular_user_token_headers`` fixture logs in → its cookie lands in
    # the shared jar, and the backend prefers the cookie over the Bearer
    # header. Clear before the admin-driven setup so admin's Bearer is
    # authoritative (else /api/leads 403s as role:user — cookie jar
    # contamination, memory test-httpx-cookie-jar-contamination).
    client.cookies.clear()
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, graduation_config, "deny"
    )
    pid = prof["id"]
    # Drop admin's cookie so the regular user's Bearer is the authoritative
    # identity for the probe under test.
    client.cookies.clear()
    resp = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/graduation-proof",
        headers=regular_user_token_headers,
        json={"kind": "official_diploma"},
    )
    assert resp.status_code in (403, 404), resp.text
