"""GĐ1b S3 — thứ tự khoá (§4.5), K3-B (§8), dấu tải (§4.3 K4c), người tải (§4.3 / I1), tệp bằng chứng (§4.6b).

Đặc tả GĐ1b bản 3.6. Fixture dùng lại chuỗi tự đủ của ``test_admission_doc_mutations_response_parity`` (một giấy tải tệp +
một giấy bản giấy trên đường xét mới). Không dữ liệu thật.
"""
from __future__ import annotations

import ast
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, text

from app import models
from app.database import AsyncSessionLocal, engine
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)

ADMISSIONS = "/api/admissions"
PDF_BYTES = b"%PDF-1.4\n%%EOF"
GOC = Path(__file__).resolve().parents[2]

#: Bộ ghi dòng giấy của repository. Hàm dịch vụ nào gọi chúng là "đường ghi giấy thường".
REPO_DOC_WRITERS = {
    "update_document_status",
    "mark_paper_submitted",
    "update_graduation_proof",
}


# --------------------------------------------------------------------------------------------------------------------
# §4.5 mục 3 — luật chung "ghi giấy phải khoá hồ sơ trước".
# --------------------------------------------------------------------------------------------------------------------
def test_moi_ham_ghi_giay_khoa_ho_so_truoc_loi_goi_ghi_dau_tien():
    """AST: mọi hàm trong ``admission_service`` gọi bộ ghi giấy của repository phải gọi
    ``_lock_profile_for_document_write`` ở dòng TRƯỚC lời gọi ghi đầu tiên. Hàm viết sau mà quên ⇒ đỏ."""
    src = (GOC / "app" / "services" / "admission_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cac_ham = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        dong_ghi, dong_khoa = [], []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in REPO_DOC_WRITERS and isinstance(node.func.value, ast.Name) and node.func.value.id.endswith("repo"):
                    dong_ghi.append(node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_lock_profile_for_document_write":
                dong_khoa.append(node.lineno)
        if dong_ghi:
            cac_ham[fn.name] = (min(dong_khoa) if dong_khoa else None, min(dong_ghi))
    assert set(cac_ham) >= {"upload_document", "mark_paper_submitted", "update_graduation_proof_kind"}, sorted(cac_ham)
    sai = {ten: v for ten, v in cac_ham.items() if v[0] is None or v[0] > v[1]}
    assert sai == {}, sai

    # Duyệt / từ chối / Đặt lại: nơi DUY NHẤT là transition_document — khoá hồ sơ TRƯỚC câu UPDATE profile_document.
    src_t = (GOC / "app" / "services" / "document_transition.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src_t)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "transition_document"
    )
    khoa = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_lock_profile_for_document_write"]
    ghi = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "update"]
    assert khoa and ghi and min(khoa) < min(ghi), (khoa, ghi)
    # Không hàm dịch vụ nào khác ghi trạng thái duyệt / từ chối / Đặt lại: bộ ghi cũ của repository đã gỡ.
    repo = (GOC / "app" / "repositories" / "admission_repository.py").read_text(encoding="utf-8")
    for ten in ("confirm_document_format", "reject_document", "reset_document"):
        assert f"def {ten}(" not in repo, ten


class _BatCau:
    def __init__(self):
        self.cau = []

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(engine.sync_engine, "before_cursor_execute", self._ghi)

    def _ghi(self, conn, cursor, statement, parameters, context, executemany):
        self.cau.append(" ".join(statement.split()))

    def vi_tri(self, mau):
        for i, c in enumerate(self.cau):
            if re.search(mau, c, re.I | re.S):
                return i
        return None


@pytest.mark.asyncio
async def test_tai_len_khoa_ho_so_truoc_cau_ghi_giay_do_bang_cau_sql_that(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "khoa_tai")
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    with _BatCau() as b:
        r = await client.post(
            f"{ADMISSIONS}/{prof['id']}/documents/{parity_config['upload_doc_code']}/upload",
            headers=oh, files={"file": ("u.pdf", PDF_BYTES, "application/pdf")},
            data={"actual_submission_format": "photo"},
        )
    assert r.status_code in (200, 201), r.text
    khoa = b.vi_tri(r"FROM admission_profile .*FOR UPDATE")
    ghi = b.vi_tri(r"^UPDATE profile_document")
    assert khoa is not None and ghi is not None and khoa < ghi, (khoa, ghi)


@pytest.mark.asyncio
async def test_xoa_ho_so_khoa_ho_so_truoc_lead(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "khoa_xoa")
    with _BatCau() as b:
        r = await client.delete(f"{ADMISSIONS}/{prof['id']}", headers=admin_token_headers)
    assert r.status_code in (200, 204), r.text
    khoa_hs = b.vi_tri(r"FROM admission_profile .*FOR UPDATE")
    khoa_lead = b.vi_tri(r"FROM lead .*FOR UPDATE")
    assert khoa_hs is not None and khoa_lead is not None and khoa_hs < khoa_lead, (khoa_hs, khoa_lead)


# --------------------------------------------------------------------------------------------------------------------
# §8 K3-B — mỗi nguồn một ca.
# --------------------------------------------------------------------------------------------------------------------
async def _giay(pid, code):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_k3b_du_lieu_hien_hanh_da_duyet_thieu_nhat_ky_thi_chan(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "k3b_hien_hanh")
    d = await _giay(prof["id"], parity_config["paper_doc_code"])
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text(
                    "UPDATE profile_document SET status = 'verified', paper_submitted_by = :u, verified_by = :u, "
                    "verified_at = now() WHERE id = :d"
                ),
                {"u": officer_user_in_db["id"], "d": d.id},
            )
    r = await client.delete(f"{ADMISSIONS}/{prof['id']}", headers=admin_token_headers)
    assert r.status_code == 409, r.text
    assert "dùng Rút hồ sơ" in r.json()["detail"]


@pytest.mark.asyncio
async def test_k3b_chi_nhat_ky_duyet_du_lieu_hien_hanh_sach_thi_van_chan(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "k3b_nhat_ky")
    d = await _giay(prof["id"], parity_config["paper_doc_code"])
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(models.DocumentAuditLog(profile_document_id=d.id, action="rejected", actor_user_id=officer_user_in_db["id"]))
    r = await client.delete(f"{ADMISSIONS}/{prof['id']}", headers=admin_token_headers)
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_k3b_chi_co_nhat_ky_tai_xuong_thi_van_xoa_duoc_va_dau_tai_con(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "k3b_tai")
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    up = await client.post(
        f"{ADMISSIONS}/{prof['id']}/documents/{parity_config['upload_doc_code']}/upload",
        headers=oh, files={"file": ("u.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"},
    )
    assert up.status_code in (200, 201), up.text
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    # Client giữ cookie đăng nhập của cán bộ và ứng dụng ưu tiên cookie ⇒ xoá cookie để lệnh dưới đúng là của Admin.
    client.cookies.clear()
    tai = await client.get(f"{ADMISSIONS}/{prof['id']}/documents/{d.id}/download", headers=admin_token_headers)
    assert tai.status_code == 200, tai.text
    r = await client.delete(f"{ADMISSIONS}/{prof['id']}", headers=admin_token_headers)
    assert r.status_code in (200, 204), r.text
    async with AsyncSessionLocal() as s:
        dau = (
            await s.execute(select(models.DocumentDownloadLog).where(models.DocumentDownloadLog.document_row_id == d.id))
        ).scalars().all()
    assert len(dau) == 1 and dau[0].profile_id == prof["id"]


# --------------------------------------------------------------------------------------------------------------------
# §4.3 K4c — dấu tải ghi CÙNG giao dịch với nhật ký "downloaded".
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tai_xuong_ghi_dau_tai_doc_lap_khop_dong_nhat_ky(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, admin_user_in_db
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "dau_tai")
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    await client.post(
        f"{ADMISSIONS}/{prof['id']}/documents/{parity_config['upload_doc_code']}/upload",
        headers=oh, files={"file": ("u.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"},
    )
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    # Client giữ cookie đăng nhập của cán bộ và ứng dụng ưu tiên cookie ⇒ xoá cookie để lệnh dưới đúng là của Admin.
    client.cookies.clear()
    tai = await client.get(f"{ADMISSIONS}/{prof['id']}/documents/{d.id}/download", headers=admin_token_headers)
    assert tai.status_code == 200, tai.text
    async with AsyncSessionLocal() as s:
        nk = (
            await s.execute(
                select(models.DocumentAuditLog).where(
                    models.DocumentAuditLog.profile_document_id == d.id, models.DocumentAuditLog.action == "downloaded"
                )
            )
        ).scalar_one()
        dau = (
            await s.execute(select(models.DocumentDownloadLog).where(models.DocumentDownloadLog.document_row_id == d.id))
        ).scalar_one()
    assert (dau.actor_user_id, dau.profile_id, dau.source_audit_id, dau.document_type_code) == (
        admin_user_in_db["id"], prof["id"], nk.id, parity_config["upload_doc_code"],
    )


# --------------------------------------------------------------------------------------------------------------------
# §4.3 / I1 — tải / thay tệp ghi người tải mới và XOÁ cờ "không rõ".
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_thay_tep_ghi_nguoi_tai_moi_va_xoa_co_khong_ro(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "nguoi_tai")
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    url = f"{ADMISSIONS}/{prof['id']}/documents/{parity_config['upload_doc_code']}/upload"
    r = await client.post(url, headers=oh, files={"file": ("u.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"})
    assert r.status_code in (200, 201), r.text
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    assert (d.uploaded_by, d.uploaded_by_unknown) == (officer_user_in_db["id"], False)
    # Giấy rơi về "không rõ người tải" rồi bị từ chối (dữ liệu cũ) ⇒ tải lại phải ghi người tải và xoá cờ.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("UPDATE profile_document SET uploaded_by = NULL, uploaded_by_unknown = true, status = 'rejected' WHERE id = :d"),
                {"d": d.id},
            )
    r = await client.post(url, headers=oh, files={"file": ("v.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"})
    assert r.status_code in (200, 201), r.text
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    assert (d.uploaded_by, d.uploaded_by_unknown) == (officer_user_in_db["id"], False)


# --------------------------------------------------------------------------------------------------------------------
# §4.6b — tải lại không xoá tệp đang là bằng chứng (Đã duyệt → Từ chối → tải lại ⇒ tệp cũ còn — F365).
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tai_lai_giu_tep_cu_dang_la_bang_chung(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "giu_bc")
    oh = await _login(client, officer_user_in_db["username"], officer_user_in_db["password"])
    url = f"{ADMISSIONS}/{prof['id']}/documents/{parity_config['upload_doc_code']}/upload"
    r = await client.post(url, headers=oh, files={"file": ("a.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"})
    assert r.status_code in (200, 201), r.text
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    tep_a = d.file_path
    assert os.path.exists(tep_a)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            nk = models.DocumentAuditLog(profile_document_id=d.id, action="verified", actor_user_id=officer_user_in_db["id"])
            s.add(nk)
            await s.flush()
            s.add(
                models.DocumentEvidenceFile(
                    profile_document_id=d.id, verification_audit_id=nk.id, profile_id=prof["id"], file_path=tep_a,
                    sha256="0" * 64, verified_by_user_id=officer_user_in_db["id"], verified_at=datetime.now(timezone.utc),
                )
            )
            await s.execute(text("UPDATE profile_document SET status = 'rejected' WHERE id = :d"), {"d": d.id})
    r = await client.post(url, headers=oh, files={"file": ("b.pdf", PDF_BYTES, "application/pdf")}, data={"actual_submission_format": "photo"})
    assert r.status_code in (200, 201), r.text
    d = await _giay(prof["id"], parity_config["upload_doc_code"])
    assert d.file_path != tep_a
    assert os.path.exists(tep_a), "tệp bằng chứng phải còn trên đĩa"


def test_quet_ma_khong_xoa_tep_giay_thuong_truc_tiep_ngoai_helper():
    """§9 "Quét mã": ở các hàm xoá tệp của giấy thường, ``os.remove`` / ``os.unlink`` / ``shutil.rmtree`` chỉ được dùng
    cho tệp tạm ``staging_path`` của chính lượt tải; mọi tệp khác đi qua ``document_file_guard``."""
    src = (GOC / "app" / "services" / "admission_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    ham_giay_thuong = {"upload_document", "reset_document", "delete_profile", "reject_document", "confirm_document_format"}
    sai = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef) or fn.name not in ham_giay_thuong:
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            ten = node.func.attr
            goc = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
            if (goc, ten) in {("os", "remove"), ("os", "unlink"), ("shutil", "rmtree")}:
                arg = node.args[0] if node.args else None
                if not (isinstance(arg, ast.Name) and arg.id == "staging_path"):
                    sai.append((fn.name, node.lineno, ast.unparse(node)))
    assert sai == [], sai
