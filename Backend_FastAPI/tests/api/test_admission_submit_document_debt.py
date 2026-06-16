"""Fast-track prepay/giữ chỗ — submit-with-document-debt contract (C1).

Covers TUITION_PREPAY_FASTTRACK_PLAN.md §6 (C1):

- staff submit with ONLY missing mandatory docs + acknowledge + reason →
  ``submitted`` + ``document_debt`` column populated correctly.
- SUBTRACTION: still blocked (stays draft) when ANY non-document error
  remains (here: a missing citizen_id) even with acknowledge + reason.
- No reason → blocked (acknowledge alone is insufficient).
- B2: an uploaded-but-pending-verify doc (strict mode) is NOT waivable —
  submit-with-debt stays blocked.
- Candidate/magic-link (current_user=None) can NEVER waive (service-level).
- ``outstanding_debt_codes`` is computed (snapshot ∩ docs still missing) and
  is in PARITY between the submit response and a subsequent GET; uploading
  the owed doc empties it (badge self-resolves).

All tests build profiles directly in the DB (mirroring the proven
``create_submittable_profile_direct`` recipe + the #337 seed chain) so the
ONLY remaining submit gate is the document one under test.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.builders import (
    ensure_submittable_ward,
    seed_submittable_offering_config,
    submittable_profile_fields,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _submittable_applied_rules(
    mandatory_docs: list[str],
    *,
    allow_unverified: bool = True,
) -> dict:
    """applied_rules that clear scoring + carry the given mandatory docs.

    ``schema_version=2`` + an explicit ``allow_unverified_submission`` so the
    strict/lax document branch is deterministic (no grandfather fallback).
    """
    return {
        "min_gpa": 0,
        "mandatory_docs": list(mandatory_docs),
        "allowed_subject_codes": ["TOAN"],
        "scoring_method": "sum",
        "required_subject_count": 1,
        "subject_selection_mode": "fixed",
        "schema_version": 2,
        "allow_unverified_submission": allow_unverified,
    }


async def _create_test_lead(unit_id: int, officer_id: int) -> int:
    unique = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Debt Applicant {unique}",
                phone=f"09{unique[:8]}",
                email=f"debt_{unique}@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def _ensure_subject_toan() -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            subj = (
                await session.execute(
                    select(models.Subject).where(models.Subject.code == "TOAN")
                )
            ).scalar_one_or_none()
            if subj is None:
                subj = models.Subject(code="TOAN", name_vi="Toan", is_active=True)
                session.add(subj)
                await session.flush()
            return subj.id


async def _create_doc_type(label: str) -> tuple[int, str]:
    """Create a ConfigDocumentType, return (id, code)."""
    ts = uuid.uuid4().hex[:10]
    code = f"{label}_{ts}"
    async with AsyncSessionLocal() as session:
        async with session.begin():
            dt = models.ConfigDocumentType(
                code=code, name=f"DOC {code}", display_order=99
            )
            session.add(dt)
            await session.flush()
            return dt.id, code


async def _build_profile(
    lead_id: int,
    *,
    mandatory_docs: list[str],
    allow_unverified: bool = True,
    citizen_id: str | None = "",  # "" → auto; None → leave NULL (force error)
) -> int:
    """Create a draft profile that is submittable EXCEPT for the docs under
    test. Returns the profile id."""
    await ensure_submittable_ward()
    subj_id = await _ensure_subject_toan()
    cid = (
        None
        if citizen_id is None
        else (citizen_id or f"0{datetime.now().timestamp():.0f}"[:12])
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = await session.get(models.Lead, lead_id)
            seed = await seed_submittable_offering_config(session, lead.unit_id)
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=cid,
                version=1,
                applied_rules=_submittable_applied_rules(
                    mandatory_docs, allow_unverified=allow_unverified
                ),
                academic_year=seed["academic_year"],
                family_info=[
                    {
                        "relationship": "Cha",
                        "full_name": "Test Father",
                        "phone": "0901234567",
                    }
                ],
                **submittable_profile_fields(seed),
            )
            session.add(profile)
            await session.flush()
            session.add(
                models.ProfileSubjectScore(
                    profile_id=profile.id, subject_id=subj_id, score=8.0
                )
            )
            await session.flush()
            return profile.id


async def _add_uploaded_doc(profile_id: int, doc_type_id: int) -> None:
    """Attach an uploaded-but-unverified ProfileDocument (file present,
    status='uploaded') for a mandatory doc — the B2 'pending verify' case."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                models.ProfileDocument(
                    profile_id=profile_id,
                    document_type_id=doc_type_id,
                    category="path",
                    status="uploaded",
                    file_path=f"uploads/admissions/{profile_id}/pending.pdf",
                    uploaded_at=datetime.now(timezone.utc),
                )
            )


async def _verify_doc(profile_id: int, doc_type_id: int) -> None:
    """Flip the pending doc to verified (officer resolved the debt)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pd = (
                await session.execute(
                    select(models.ProfileDocument).where(
                        models.ProfileDocument.profile_id == profile_id,
                        models.ProfileDocument.document_type_id == doc_type_id,
                    )
                )
            ).scalar_one()
            pd.status = "verified"
            pd.verified_at = datetime.now(timezone.utc)


async def _set_doc_status(profile_id: int, doc_type_id: int, status: str) -> None:
    """Set a ProfileDocument to an arbitrary status (e.g. paper_submitted)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pd = (
                await session.execute(
                    select(models.ProfileDocument).where(
                        models.ProfileDocument.profile_id == profile_id,
                        models.ProfileDocument.document_type_id == doc_type_id,
                    )
                )
            ).scalar_one()
            pd.status = status


async def _ver(client: AsyncClient, headers: dict, profile_id: int) -> int:
    """Current profile version (for optimistic-lock-guarded actions)."""
    res = await client.get(f"/api/admissions/{profile_id}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["version"]


async def _auth(client: AsyncClient, user: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert res.status_code == 200, f"login failed: {res.text}"
    token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {token}"}


async def _load_profile(profile_id: int) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubmitWithDocumentDebt:
    async def test_staff_submit_with_debt_succeeds_and_records_snapshot(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Officer + acknowledge + reason + only missing docs → submitted +
        document_debt column populated with {codes, reason, by_user_id, at}."""
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(lead_id, mandatory_docs=[doc_code])
        headers = await _auth(client, officer_user_in_db)

        res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "HS xin cấp lại học bạ, hẹn 30/06",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "submitted", res.json()

        profile = await _load_profile(pid)
        assert profile.status == "submitted"
        assert profile.document_debt is not None
        assert profile.document_debt["codes"] == [doc_code]
        assert profile.document_debt["reason"] == "HS xin cấp lại học bạ, hẹn 30/06"
        assert profile.document_debt["by_user_id"] == officer_user_in_db["id"]
        assert "at" in profile.document_debt

        # ⚠️ Anti-tamper: document_debt must NOT have leaked into applied_rules
        # (that would RAISE on the immutability trigger in prod).
        assert "document_debt" not in (profile.applied_rules or {})

    async def test_submit_with_debt_no_reason_blocks(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """acknowledge_missing_docs=True but NO reason → stays draft."""
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(lead_id, mandatory_docs=[doc_code])
        headers = await _auth(client, officer_user_in_db)

        res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={"acknowledge_missing_docs": True},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "draft", body
        assert body["validation_errors"]
        profile = await _load_profile(pid)
        assert profile.status == "draft"
        assert profile.document_debt is None

    async def test_plain_submit_missing_docs_blocks(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """No body (default) + missing docs → stays draft (original flow)."""
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(lead_id, mandatory_docs=[doc_code])
        headers = await _auth(client, officer_user_in_db)

        res = await client.post(f"/api/admissions/{pid}/submit", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "draft", body
        # missing-doc error is surfaced in the full list
        assert any("Thiếu tài liệu" in e for e in body["validation_errors"])
        profile = await _load_profile(pid)
        assert profile.document_debt is None

    async def test_other_error_still_blocks_despite_reason(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """SUBTRACTION: a non-document error (missing citizen_id) keeps the
        profile in draft even with acknowledge + reason — only docs waivable."""
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], citizen_id=None
        )
        headers = await _auth(client, officer_user_in_db)

        res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "cho nợ",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "draft", body
        assert any("CCCD" in e or "citizen_id" in e for e in body["validation_errors"])
        profile = await _load_profile(pid)
        assert profile.status == "draft"
        assert profile.document_debt is None

    async def test_unverified_doc_not_waived(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """B2: a doc uploaded-but-pending-verify (strict mode) is NOT missing,
        so submit-with-debt does not waive it — stays draft."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        # Upload the file but leave it unverified → strict mode rejects it,
        # but it is "pending verify", not "missing" → not waivable.
        await _add_uploaded_doc(pid, doc_type_id)
        headers = await _auth(client, officer_user_in_db)

        res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "cho nợ",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "draft", body
        assert any("chưa được xác minh" in e for e in body["validation_errors"])
        profile = await _load_profile(pid)
        assert profile.status == "draft"
        assert profile.document_debt is None

    async def test_candidate_magic_link_cannot_waive(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Service-level: current_user=None (magic-link candidate) may NOT
        waive even with acknowledge + reason — stays draft, no debt."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(lead_id, mandatory_docs=[doc_code])

        async with AsyncSessionLocal() as session:
            result, post_commit = await admission_service.submit_and_evaluate(
                db=session,
                profile_id=pid,
                current_user=None,  # magic-link candidate path
                acknowledge_missing_docs=True,
                document_debt_reason="candidate trying to skip docs",
            )
            await session.commit()
            if post_commit is not None:
                await post_commit()

        assert result["status"] == "draft", result
        profile = await _load_profile(pid)
        assert profile.status == "draft"
        assert profile.document_debt is None

    async def test_outstanding_debt_codes_parity_and_resolution(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """outstanding_debt_codes = snapshot ∩ docs-still-missing; parity
        between submit response and GET; empties after the doc is verified."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        headers = await _auth(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "cho nợ",
            },
        )
        assert submit_res.status_code == 200, submit_res.text
        submit_body = submit_res.json()
        assert submit_body["status"] == "submitted", submit_body

        # GET reflects the debt + computed outstanding codes.
        get_res = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_res.status_code == 200, get_res.text
        get_body = get_res.json()
        assert get_body["document_debt"]["codes"] == [doc_code]
        assert get_body["outstanding_debt_codes"] == [doc_code]
        assert doc_code in get_body["missing_doc_codes"]

        # Officer uploads + verifies the owed doc → outstanding self-resolves
        # to [] while the snapshot (audit) is retained.
        await _add_uploaded_doc(pid, doc_type_id)
        await _verify_doc(pid, doc_type_id)

        get_res2 = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_res2.status_code == 200, get_res2.text
        get_body2 = get_res2.json()
        assert get_body2["outstanding_debt_codes"] == [], get_body2[
            "outstanding_debt_codes"
        ]
        # snapshot retained for audit ("đã từng nợ")
        assert get_body2["document_debt"]["codes"] == [doc_code]


class TestOutstandingDebtVerifiedBased:
    """outstanding_debt_codes resolves on VERIFY, not on mere upload (C1.5).

    The regression these guard: when the path is in LAX mode
    (``allow_unverified_submission=True``), an uploaded-but-unverified doc
    LEAVES ``missing_doc_codes`` (lax counts an uploaded file as present). The
    OLD outstanding logic (``codes ∩ missing_doc_codes``) therefore emptied the
    debt the instant the officer uploaded — before any reviewer verified. The
    decision is "hết nợ chỉ khi VERIFY", so outstanding must stay non-empty
    until the doc is verified/paper_submitted.
    """

    async def test_upload_without_verify_keeps_debt_outstanding_lax_mode(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """LAX mode: officer uploads owed doc (status uploaded, NOT verified)
        → outstanding_debt_codes STILL lists it. Verify → it clears."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        # allow_unverified=True (lax) is the case that exposed the bug.
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=True
        )
        headers = await _auth(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "cho nợ học bạ",
            },
        )
        assert submit_res.status_code == 200, submit_res.text
        assert submit_res.json()["status"] == "submitted", submit_res.json()

        # Officer uploads the owed doc but it is NOT yet verified.
        await _add_uploaded_doc(pid, doc_type_id)

        get_res = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_res.status_code == 200, get_res.text
        body = get_res.json()
        # VERIFIED-based: still outstanding despite the upload (the bug fix).
        assert body["outstanding_debt_codes"] == [doc_code], body[
            "outstanding_debt_codes"
        ]
        # In lax mode the uploaded doc is no longer "missing" — proving the
        # outstanding set is NOT derived from missing_doc_codes anymore.
        assert doc_code not in body["missing_doc_codes"], body["missing_doc_codes"]

        # Reviewer verifies → debt clears.
        await _verify_doc(pid, doc_type_id)
        get_res2 = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_res2.status_code == 200, get_res2.text
        assert get_res2.json()["outstanding_debt_codes"] == [], get_res2.json()[
            "outstanding_debt_codes"
        ]

    async def test_paper_submitted_resolves_debt(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """A doc marked paper_submitted (bản giấy) also clears the debt."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        headers = await _auth(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": "cho nợ",
            },
        )
        assert submit_res.status_code == 200, submit_res.text
        assert submit_res.json()["status"] == "submitted"

        await _add_uploaded_doc(pid, doc_type_id)
        # Still outstanding until verify/paper_submitted.
        get_a = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_a.json()["outstanding_debt_codes"] == [doc_code]

        await _set_doc_status(pid, doc_type_id, "paper_submitted")
        get_b = await client.get(f"/api/admissions/{pid}", headers=headers)
        assert get_b.json()["outstanding_debt_codes"] == [], get_b.json()[
            "outstanding_debt_codes"
        ]


class TestApproveGateDocumentDebt:
    """Approve is BLOCKED while a document debt is outstanding (C1.5)."""

    async def _submit_with_debt(
        self,
        client: AsyncClient,
        officer_headers: dict,
        pid: int,
        reason: str = "cho nợ giấy tờ",
    ) -> None:
        res = await client.post(
            f"/api/admissions/{pid}/submit",
            headers=officer_headers,
            json={
                "acknowledge_missing_docs": True,
                "document_debt_reason": reason,
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "submitted", res.json()

    async def test_approve_blocked_while_debt_outstanding(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """submitted-with-debt + owed doc unverified → manager approve is
        rejected with a 400 BusinessRuleViolation; the FE approve flag is off."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        officer_headers = await _auth(client, officer_user_in_db)
        await self._submit_with_debt(client, officer_headers, pid)

        manager_headers = await _auth(client, manager_user_in_db)

        # FE contract: the approve permission/action is suppressed.
        get_res = await client.get(f"/api/admissions/{pid}", headers=manager_headers)
        assert get_res.status_code == 200, get_res.text
        body = get_res.json()
        assert body["outstanding_debt_codes"] == [doc_code]
        assert body["permissions"].get("approve") is False, body["permissions"]
        assert "approve" not in body["available_actions"], body["available_actions"]

        # Server gate: attempting approve anyway → 400.
        version = body["version"]
        approve_res = await client.post(
            f"/api/admissions/{pid}/approve",
            headers=manager_headers,
            json={"notes": "duyệt", "version": version},
        )
        assert approve_res.status_code == 400, approve_res.text
        assert "nợ giấy tờ" in approve_res.json()["detail"], approve_res.json()

        # Profile stayed submitted (no seat consumed, no transition).
        profile = await _load_profile(pid)
        assert profile.status == "submitted"

    async def test_approve_ok_after_debt_verified(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Once the owed doc is verified (outstanding empties) approve works."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        officer_headers = await _auth(client, officer_user_in_db)
        await self._submit_with_debt(client, officer_headers, pid)

        # Officer supplies + reviewer verifies the owed doc.
        await _add_uploaded_doc(pid, doc_type_id)
        await _verify_doc(pid, doc_type_id)

        manager_headers = await _auth(client, manager_user_in_db)
        get_res = await client.get(f"/api/admissions/{pid}", headers=manager_headers)
        assert get_res.status_code == 200, get_res.text
        body = get_res.json()
        assert body["outstanding_debt_codes"] == [], body["outstanding_debt_codes"]
        assert body["permissions"].get("approve") is True, body["permissions"]

        version = body["version"]
        approve_res = await client.post(
            f"/api/admissions/{pid}/approve",
            headers=manager_headers,
            json={"notes": "đủ giấy tờ", "version": version},
        )
        assert approve_res.status_code == 200, approve_res.text
        assert approve_res.json()["status"] == "approved", approve_res.json()

    async def test_approve_unaffected_without_document_debt(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """No-regression: a profile submitted WITHOUT a debt (all docs present)
        approves exactly as before — the gate is a no-op when document_debt is
        NULL."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=True
        )
        # Upload the mandatory doc up-front so a plain submit (no debt) passes.
        await _add_uploaded_doc(pid, doc_type_id)
        officer_headers = await _auth(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{pid}/submit", headers=officer_headers
        )
        assert submit_res.status_code == 200, submit_res.text
        assert submit_res.json()["status"] == "submitted", submit_res.json()

        profile = await _load_profile(pid)
        assert profile.document_debt is None

        manager_headers = await _auth(client, manager_user_in_db)
        version = await _ver(client, manager_headers, pid)
        approve_res = await client.post(
            f"/api/admissions/{pid}/approve",
            headers=manager_headers,
            json={"notes": "ok", "version": version},
        )
        assert approve_res.status_code == 200, approve_res.text
        assert approve_res.json()["status"] == "approved", approve_res.json()

    async def test_bulk_approve_skips_profile_with_outstanding_debt(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """bulk_approve must NOT bypass the debt gate — the debt-laden item is
        skipped (recorded in errors), not approved."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("needdoc")
        lead_id = await _create_test_lead(unit_id, officer_user_in_db["id"])
        pid = await _build_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=False
        )
        officer_headers = await _auth(client, officer_user_in_db)
        await self._submit_with_debt(client, officer_headers, pid)

        profile = await _load_profile(pid)
        version = profile.version

        async with AsyncSessionLocal() as session:
            manager = await session.get(models.User, manager_user_in_db["id"])
            result, post_commit = await admission_service.bulk_approve(
                db=session,
                items=[{"profile_id": pid, "version": version}],
                approver=manager,
            )
            await session.commit()
            if post_commit is not None:
                await post_commit()

        assert result["success_count"] == 0, result
        assert pid in result["failed_ids"], result
        assert "nợ giấy tờ" in result["errors"][pid], result["errors"]

        # Profile stayed submitted (not approved).
        profile_after = await _load_profile(pid)
        assert profile_after.status == "submitted"
