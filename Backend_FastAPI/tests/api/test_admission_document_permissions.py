"""API-level contract: documents_checklist carries per-doc permission flags (PR #5).

Probes the 5 backend-computed booleans (`can_upload`, `can_verify`,
`can_reject`, `can_reset`, `can_mark_paper_submitted`) for the two
roles that differ most from the old `can('edit')` assumption: an
owning officer (should see upload/paper actions) and an admin acting
on the same profile (should see verify/reject/reset).
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
async def doc_perm_config(seed_lead_dependencies: dict):
    """Admission config + lead + draft profile so documents_checklist exists.

    Mirrors the inline fixture in the bulk-assign test (still not worth
    promoting to shared conftest until a third consumer arrives).
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
                min_gpa=6.0, scoring_method="average", subject_selection_mode="fixed",
                policy_version="2026.1", is_active=True,
            )
            s.add(ac); await s.flush()
            ap = models.AdmissionPath(
                academic_info_id=ai.id, admission_method_id=am.id, criteria_id=ac.id,
                status="active", display_name="Test", display_order=0, visibility="public",
            )
            s.add(ap); await s.flush()
            # Wire a document group so newly created profiles populate
            # documents_checklist with at least one mandatory upload row.
            # Without this, the checklist would be empty and the permission
            # assertions would never exercise a real doc.
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
    return {"unit_id": uid, "offering_id": po.id, "method_id": am.id}


async def _create_profile(client, admin_token_headers, officer_user_in_db, cfg):
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    lead = (await client.post(LeadsURLs.LEADS, json={
        "full_name": "PR5 Doc Perm Probe",
        "phone": "0988123460",
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
    }, headers=admin_token_headers)).json()
    return prof


@pytest.mark.asyncio
async def test_documents_checklist_exposes_permission_flags(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """Every doc row must carry the 5 explicit flags, irrespective of role."""
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, doc_perm_config)
    pid = prof["id"]

    admin_detail = (await client.get(f"{ADMISSIONS}/{pid}", headers=admin_token_headers)).json()
    checklist = admin_detail.get("documents_checklist", [])
    assert checklist, "Admission profile should expose a documents_checklist once created"
    required_flags = {
        "can_upload",
        "can_verify",
        "can_reject",
        "can_reset",
        "can_mark_paper_submitted",
    }
    for doc in checklist:
        missing = required_flags - doc.keys()
        assert not missing, (
            f"doc {doc.get('code')!r} missing permission flags: {missing}. "
            f"Got: {sorted(doc.keys())}"
        )
        for flag in required_flags:
            assert isinstance(doc[flag], bool), (
                f"{flag} on {doc.get('code')!r} should be bool, got {type(doc[flag]).__name__}"
            )


@pytest.mark.asyncio
async def test_officer_owner_has_upload_but_not_verify(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """Owning officer on a draft profile may upload, not verify/reject/reset."""
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, doc_perm_config)
    pid = prof["id"]

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    checklist = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["documents_checklist"]
    upload_docs = [d for d in checklist if d.get("requires_upload")]
    assert upload_docs, "Test setup expects at least one upload-required doc"
    for doc in upload_docs:
        # missing + owning officer + profile editable → may upload
        assert doc["can_upload"] is True, f"{doc['code']}: owning officer should upload"
        # Verify/reject/reset belong to reviewer scope only.
        assert doc["can_verify"] is False, f"{doc['code']}: officer must not verify"
        assert doc["can_reject"] is False, f"{doc['code']}: officer must not reject"
        assert doc["can_reset"] is False, f"{doc['code']}: officer must not reset"


@pytest.mark.asyncio
async def test_admin_has_reviewer_actions_after_upload(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """After an officer uploads, admin sees verify/reject/reset flags flip on."""
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, doc_perm_config)
    pid = prof["id"]

    # Officer uploads the first upload-required doc so we have a non-missing
    # row to exercise reviewer actions against.
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    current = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["documents_checklist"]
    target = next(d for d in current if d.get("requires_upload"))
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{target['code']}/upload",
        headers=oh,
        files={"file": (f"{target['code']}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    # Re-login as admin so the Authorization token is fresh; the shared
    # cookie jar was last written by the officer upload above.
    from tests.fixtures.constants import TestUsers
    admin_headers = await _login(client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"])
    admin_view = (await client.get(f"{ADMISSIONS}/{pid}", headers=admin_headers)).json()
    uploaded_row = next(
        d for d in admin_view["documents_checklist"] if d["code"] == target["code"]
    )
    assert uploaded_row["status"] in ("uploaded", "paper_submitted"), uploaded_row
    assert uploaded_row["can_verify"] is True, uploaded_row
    assert uploaded_row["can_reject"] is True, uploaded_row
    assert uploaded_row["can_reset"] is True, uploaded_row
    # Admin is not the lead's assigned officer → can_upload should flip off
    # once status is no longer missing/rejected.
    assert uploaded_row["can_upload"] is False
