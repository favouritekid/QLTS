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
            # Optional doc type (is_mandatory=False) — để test phân loại is_extra:
            # tài liệu tùy chọn của method hiện tại KHÔNG được coi là "ngoài yêu cầu".
            dt_opt = models.ConfigDocumentType(code=f"opt_{ts}", name=f"OPT_{ts}", display_order=2)
            s.add(dt_opt); await s.flush()
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
            # Optional (paper) item — mirrors giay_kham_suc_khoe trong prod config.
            dgi_opt = models.DocumentGroupItem(
                group_id=dg.id,
                document_type_id=dt_opt.id,
                is_mandatory=False,
                requires_upload=False,
                submission_format="original",
                display_order=2,
            )
            s.add(dgi_opt); await s.flush()
    return {
        "unit_id": uid, "offering_id": po.id, "method_id": am.id,
        "round_id": round_id, "optional_doc_code": f"opt_{ts}",
    }


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
        "admission_round_id": cfg["round_id"],
        "academic_year": 2026,
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
async def test_optional_doc_in_main_list_not_extra(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """Tài liệu TÙY CHỌN (is_mandatory=false trong doc_configs) phải nằm trong
    danh sách chính: ``is_extra=false`` + ``is_mandatory=false`` — KHÔNG bị gán
    nhầm "ngoài yêu cầu / phương thức trước đó".

    Regression cho bug phân loại is_extra: builder cũ chỉ duyệt mandatory_docs
    nên optional doc (vd giay_kham_suc_khoe) khi đã nộp rơi vào pass 2 →
    is_extra=True + read-only. Sau fix: builder duyệt cả doc_configs keyset →
    optional hiển thị ngay cả khi chưa nộp, có nút thao tác bình thường.
    """
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, doc_perm_config
    )
    pid = prof["id"]

    checklist = (
        await client.get(f"{ADMISSIONS}/{pid}", headers=admin_token_headers)
    ).json()["documents_checklist"]
    opt_code = doc_perm_config["optional_doc_code"]
    opt = next((d for d in checklist if d["code"] == opt_code), None)

    assert opt is not None, (
        f"optional doc {opt_code!r} phải xuất hiện trong checklist chính "
        f"(logic is_extra cũ làm nó vô hình khi chưa nộp). "
        f"codes: {[d['code'] for d in checklist]}"
    )
    assert opt["is_extra"] is False, "optional doc của method hiện tại KHÔNG phải extra"
    assert opt["is_mandatory"] is False, "optional doc phải đánh dấu không bắt buộc"
    # KHÔNG bị clamp read-only như extra: admin thấy đủ 5 flag (giá trị tùy status).
    expected_flags = (
        "can_upload", "can_verify", "can_reject", "can_reset",
        "can_mark_paper_submitted",
    )
    for flag in expected_flags:
        assert flag in opt, f"optional doc thiếu flag {flag}"


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
async def test_officer_cannot_verify_reject_or_reset_even_with_casbin_allow(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """Service-layer guard keeps reviewer actions out of officer reach.

    Before PR #5 review follow-up, the 4 doc-mutation routes only ran
    Casbin + an IDOR check. Even after we relax Casbin to let the
    officer hit /paper-submitted (needed for the can_mark_paper_submitted
    flag), a separate `_authorize_document_action` guard must still
    reject officer attempts on verify-format / reject / reset — the
    can_* flags the FE receives would be false for those actions, and
    the API must honour that, not just hide the buttons.
    """
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, doc_perm_config)
    pid = prof["id"]

    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    current = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()["documents_checklist"]
    target = next(d for d in current if d.get("requires_upload"))

    # Officer uploads first so verify/reject/reset have a non-missing target.
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{target['code']}/upload",
        headers=oh,
        files={"file": (f"{target['code']}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    # Casbin may also reject officer — either way, the action is forbidden.
    # Accept any 4xx that is NOT 200 so behaviour is robust to whether
    # Casbin seed has been applied yet.
    for route, method, body in [
        (f"{ADMISSIONS}/{pid}/documents/{target['code']}/verify-format", "PATCH", {"format": "photo"}),
        (f"{ADMISSIONS}/{pid}/documents/{target['code']}/reject", "POST", {"reason": "officer-not-allowed"}),
        (f"{ADMISSIONS}/{pid}/documents/{target['code']}/reset", "POST", {}),
    ]:
        resp = await client.request(method, route, headers=oh, json=body)
        assert resp.status_code in (403, 404), (
            f"{method} {route}: expected 403/404 for officer, got {resp.status_code}: {resp.text[:200]}"
        )


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


@pytest.mark.asyncio
async def test_extras_are_locked_at_service_layer_not_just_in_response(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    doc_perm_config: dict,
):
    """BR2 (2026-04-29; def fix 2026-06-09): documents whose code is no longer
    in the profile's ``applied_rules.doc_configs`` (mandatory + optional) are
    evidence-only — every direct API mutation must be rejected, not just hidden
    in the UI.

    Set up: create a profile (which seeds ``doc_configs`` from the path), upload
    its mandatory doc, then mutate the snapshot in DB so that doc drops out of
    ``doc_configs`` (becomes "extra"). Re-fetch and confirm the response marks
    it ``is_extra=True`` with all ``can_*`` false. Then call every
    document-mutation endpoint directly and assert each one is rejected —
    proves the service guard, not just the response shape, enforces read-only.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from sqlalchemy import select
    from tests.fixtures.constants import TestUsers

    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, doc_perm_config
    )
    pid = prof["id"]

    # Officer uploads so the doc has artifact state to "freeze" as evidence.
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    checklist = (await client.get(f"{ADMISSIONS}/{pid}", headers=oh)).json()[
        "documents_checklist"
    ]
    target = next(d for d in checklist if d.get("requires_upload"))
    upload = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{target['code']}/upload",
        headers=oh,
        files={
            "file": (f"{target['code']}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
        },
        data={"actual_submission_format": "photo"},
    )
    assert upload.status_code in (200, 201), upload.text

    # Mutate the snapshot so target becomes "extra". This simulates the
    # AdmissionPath being edited after profile creation; the service
    # under test must observe applied_rules.doc_configs as the
    # source of truth and reject mutations on the now-stale doc.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            row = await s.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == pid
                )
            )
            db_profile = row.scalar_one()
            new_rules = dict(db_profile.applied_rules or {})
            # BR2 (fix 2026-06-09): "extra" giờ định nghĩa theo doc_configs
            # (mandatory + optional), KHÔNG chỉ mandatory_docs. Để target thành
            # extra THẬT (mô phỏng AdmissionPath đổi → doc rớt hẳn), xóa khỏi CẢ
            # mandatory_docs LẪN doc_configs.
            new_rules["mandatory_docs"] = []
            new_rules["doc_configs"] = {}
            db_profile.applied_rules = new_rules
            flag_modified(db_profile, "applied_rules")

    admin_headers = await _login(
        client, TestUsers.ADMIN["username"], TestUsers.ADMIN["password"]
    )

    # Response shape: row marked is_extra + all can_* false.
    refreshed = (
        await client.get(f"{ADMISSIONS}/{pid}", headers=admin_headers)
    ).json()
    extra = next(
        d for d in refreshed["documents_checklist"] if d["code"] == target["code"]
    )
    assert extra["is_extra"] is True, extra
    for flag in (
        "can_upload",
        "can_verify",
        "can_reject",
        "can_reset",
        "can_mark_paper_submitted",
    ):
        assert extra[flag] is False, f"extras must clamp {flag}=False, got {extra}"

    # Service guard: every direct mutation endpoint must reject.
    # Includes both reviewer-side (verify/reject/reset) and
    # applicant-side (upload/paper-submitted) — the read-only contract
    # is symmetric.
    code = target["code"]
    rejection_routes = [
        (
            f"{ADMISSIONS}/{pid}/documents/{code}/verify-format",
            "PATCH",
            {"format": "photo"},
            None,
        ),
        (
            f"{ADMISSIONS}/{pid}/documents/{code}/reject",
            "POST",
            {"reason": "extras lock contract test"},
            None,
        ),
        (
            f"{ADMISSIONS}/{pid}/documents/{code}/reset",
            "POST",
            {},
            None,
        ),
        (
            f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted",
            "POST",
            # Include actual_submission_format so the request passes the
            # Pydantic schema validation gate and reaches the service
            # guard — without it the endpoint would 422 on the body
            # shape, which doesn't prove the BR2 lock.
            {"actual_submission_format": "photo"},
            None,
        ),
    ]
    for route, method, body, _ in rejection_routes:
        resp = await client.request(method, route, headers=admin_headers, json=body)
        assert resp.status_code in (403, 404), (
            f"{method} {route} on extra doc: expected 403/404, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )

    # Upload endpoint takes multipart, not JSON — exercise it separately
    # so the service guard is hit before the file-handling path.
    upload_again = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/upload",
        headers=admin_headers,
        files={"file": (f"{code}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert upload_again.status_code in (403, 404), (
        f"POST upload on extra doc: expected 403/404, "
        f"got {upload_again.status_code}: {upload_again.text[:200]}"
    )
