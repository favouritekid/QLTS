"""PR1 Commit 1 anchor tests — authed admission document download (A01/A05/A09).

Pins the contract that:
  * the checklist projection exposes ``document_id`` for a path doc that has a
    real file (and null when there's no artifact) — without it the FE can't
    build the download URL and PR2 breaks (Pydantic drops undeclared fields);
  * GET .../documents/{document_id}/download serves the file only to in-scope
    staff, binds the document to the authorized profile (cross-profile id →
    404), refuses anonymous callers (401), and writes a ``downloaded`` audit
    row;
  * the path-traversal guard ``_resolve_under`` rejects escapes.

Reuses the self-contained fixture chain from
``test_admission_doc_mutations_response_parity`` (one upload doc + one
paper-only doc on a fresh admission path).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services.admission_service import _resolve_under

# Reuse the parity fixture + helpers (self-contained admission path + docs).
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    parity_config,
    _login,
    _create_profile,
)

ADMISSIONS = "/api/admissions"
PDF_BYTES = b"%PDF-1.4\n%%EOF"


async def _upload_and_get_checklist(client, oh, pid, doc_code):
    """Officer uploads a PDF, return the upload response's checklist keyed by code."""
    up = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{doc_code}/upload",
        headers=oh,
        files={"file": ("u.pdf", PDF_BYTES, "application/pdf")},
        data={"actual_submission_format": "photo"},
    )
    assert up.status_code in (200, 201), up.text
    return {d["code"]: d for d in up.json()["documents_checklist"]}


def test_resolve_under_rejects_traversal():
    """Pure-function guard: in-dir paths pass; escapes return None."""
    base = "uploads/admissions/42"
    assert _resolve_under(base, "uploads/admissions/42/HOC_BA_abc.pdf") is not None
    # ../ escape into a sibling profile dir → rejected.
    assert _resolve_under(base, "uploads/admissions/42/../43/secret.pdf") is None
    # Absolute escape → rejected.
    assert _resolve_under(base, "/etc/passwd") is None
    # Deep traversal out of the tree → rejected.
    assert _resolve_under(base, "uploads/admissions/42/../../../../etc/passwd") is None


@pytest.mark.asyncio
async def test_checklist_exposes_document_id_for_path_doc(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "docid"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    checklist = await _upload_and_get_checklist(
        client, oh, pid, parity_config["upload_doc_code"]
    )

    up_item = checklist[parity_config["upload_doc_code"]]
    assert isinstance(up_item.get("document_id"), int), (
        "uploaded path doc must expose an int document_id for the download URL; "
        f"got {up_item.get('document_id')!r}"
    )
    # The paper-only doc has no file artifact → document_id must stay null so
    # the FE doesn't render a broken "Xem PDF" button.
    paper_item = checklist[parity_config["paper_doc_code"]]
    assert paper_item.get("document_id") is None, (
        "doc with no file must have document_id=None; "
        f"got {paper_item.get('document_id')!r}"
    )


@pytest.mark.asyncio
async def test_checklist_exposes_document_id_for_extra_doc(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    """Plan parity: document_id must also appear on EXTRA docs (the is_extra
    block — a ProfileDocument whose code is NOT in the current mandatory
    snapshot, e.g. after the path was edited). Same projection code as path
    docs, asserted here so the FE contract holds for BOTH append branches."""
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "extra"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )

    # Insert a ProfileDocument for a doc type NOT in the path's document group
    # → it lands in the is_extra block of the checklist projection. file_path
    # is set, so document_id must be exposed.
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            dt_extra = models.ConfigDocumentType(
                code=f"extra_{ts}", name=f"EXTRA_{ts}", display_order=99
            )
            s.add(dt_extra)
            await s.flush()
            pd = models.ProfileDocument(
                profile_id=pid,
                document_type_id=dt_extra.id,
                category="path",
                status="uploaded",
                file_path=f"uploads/admissions/{pid}/extra_{ts}.pdf",
                uploaded_at=datetime.now(timezone.utc),
            )
            s.add(pd)
            await s.flush()
            extra_doc_id = pd.id
            extra_code = dt_extra.code

    res = await client.get(f"{ADMISSIONS}/{pid}", headers=oh)
    assert res.status_code == 200, res.text
    checklist = {d["code"]: d for d in res.json()["documents_checklist"]}
    assert extra_code in checklist, "inserted extra doc must appear in checklist"
    item = checklist[extra_code]
    assert item.get("is_extra") is True, (
        f"expected is_extra=True, got {item.get('is_extra')!r}"
    )
    assert item.get("document_id") == extra_doc_id, (
        "extra doc with a file must expose document_id (is_extra projection "
        f"block); got {item.get('document_id')!r}"
    )


@pytest.mark.asyncio
async def test_download_owner_officer_ok_and_audited(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "dl_ok"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    checklist = await _upload_and_get_checklist(
        client, oh, pid, parity_config["upload_doc_code"]
    )
    document_id = checklist[parity_config["upload_doc_code"]]["document_id"]

    resp = await client.get(
        f"{ADMISSIONS}/{pid}/documents/{document_id}/download", headers=oh
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "inline" in resp.headers.get("content-disposition", "")
    assert resp.headers.get("cache-control") == "private, no-store"

    # Gap 1 (A09): a ``downloaded`` audit row must exist for this document.
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(models.DocumentAuditLog).where(
                    models.DocumentAuditLog.profile_document_id == document_id,
                    models.DocumentAuditLog.action == "downloaded",
                )
            )
        ).scalars().all()
    assert len(rows) >= 1, "download must write a 'downloaded' DocumentAuditLog row"
    assert rows[0].actor_user_id == officer_user_in_db["id"]


@pytest.mark.asyncio
async def test_download_requires_auth(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "dl_401"
    )
    pid = prof["id"]
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    checklist = await _upload_and_get_checklist(
        client, oh, pid, parity_config["upload_doc_code"]
    )
    document_id = checklist[parity_config["upload_doc_code"]]["document_id"]

    # Clear the cookie jar so the prior login's access_token cookie doesn't
    # silently authenticate this "anonymous" request (memory
    # ``test-httpx-cookie-jar-contamination``).
    client.cookies.clear()
    resp = await client.get(f"{ADMISSIONS}/{pid}/documents/{document_id}/download")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_download_cross_profile_document_id_404(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    """IDOR binding: a document_id belonging to another profile must 404 even
    when the caller is authorized for the profile named in the URL."""
    oh = await _login(
        client, officer_user_in_db["username"], officer_user_in_db["password"]
    )
    # Profile A — upload a doc, capture its document_id.
    prof_a = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "idor_a"
    )
    checklist_a = await _upload_and_get_checklist(
        client, oh, prof_a["id"], parity_config["upload_doc_code"]
    )
    doc_id_a = checklist_a[parity_config["upload_doc_code"]]["document_id"]

    # Profile B — same officer/unit (authorized), different profile.
    prof_b = await _create_profile(
        client, admin_token_headers, officer_user_in_db, parity_config, "idor_b"
    )

    # Request A's document under B's URL → doc.profile_id != B → 404.
    resp = await client.get(
        f"{ADMISSIONS}/{prof_b['id']}/documents/{doc_id_a}/download", headers=oh
    )
    assert resp.status_code == 404, resp.text
