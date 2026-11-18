"""GĐ1b §4.6b + §8 — xoá thứ đang có tệp bằng chứng (đặc tả bản 3.6 §9 "Tệp bằng chứng", "[MỚI 3.3] Bằng chứng (F376)").

* K3-B (tầng chủ sở hữu, ứng dụng): xoá hồ sơ mà nguồn DUY NHẤT là dòng ``document_evidence_file`` ⇒ 409, dòng + tệp còn.
  Hai nguồn kia (dữ liệu hiện hành / nhật ký duyệt) đã có ca riêng ở ``test_gd1b_khoa_va_tep.py``.
* RESTRICT (lớp phòng thủ thêm, CSDL): SQL trực tiếp xoá hồ sơ / dòng giấy có bằng chứng ⇒ CSDL từ chối — hỏi CSDL từ một
  phiên RIÊNG (không qua ứng dụng), rồi đọc lại từ phiên thứ ba.
* ORM không tự gán NULL: ``session.delete(...)`` dòng giấy / dòng nhật ký duyệt đang được bằng chứng tham chiếu ⇒ lỗi khoá
  ngoại, KHÔNG có câu ``UPDATE document_evidence_file`` nào được phát ra.

Mỗi ca kiểm MỘT bất biến; biến thể phá ở ``kiem-thu-phien-a/ma/gd1b_bc_*.json``. Dữ liệu giả.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal, engine
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    parity_config,
)
from tests.api.test_gd1b_bang_chung_tai import PDF, _bang_chung, _dn, _ho_so_co_bang_chung, _tai_len

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"


class _BatCau:
    """Ghi mọi câu SQL engine ứng dụng phát ra trong khối ``with``."""

    def __init__(self):
        self.cau = []

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(engine.sync_engine, "before_cursor_execute", self._ghi)

    def _ghi(self, conn, cursor, statement, parameters, context, executemany):
        self.cau.append(" ".join(statement.split()))

    def co(self, mau: str) -> list:
        return [c for c in self.cau if re.search(mau, c, re.I)]


def _la_vi_pham_khoa_ngoai_bang_chung(e: IntegrityError) -> bool:
    """Lỗi đúng lý do: SQLSTATE 23503 (vi phạm khoá ngoại) và chính ràng buộc của ``document_evidence_file``."""
    goc = getattr(e.orig, "__cause__", None) or e.orig
    sqlstate = getattr(goc, "sqlstate", None) or getattr(e.orig, "sqlstate", None) or getattr(e.orig, "pgcode", None)
    return sqlstate == "23503" and "document_evidence_file" in str(e)


async def _con_nguyen(pid: int, doc_id: int, ev_id: int, tep: str, sha: str) -> None:
    """Đọc lại từ một phiên KHÁC: hồ sơ, dòng giấy, dòng bằng chứng còn; tệp còn trên ổ, đúng băm."""
    async with AsyncSessionLocal() as s:
        assert (await s.get(models.AdmissionProfile, pid)) is not None
        assert (await s.get(models.ProfileDocument, doc_id)) is not None
        ev = await s.get(models.DocumentEvidenceFile, ev_id)
        assert ev is not None and ev.profile_document_id == doc_id
    assert os.path.isfile(tep) and hashlib.sha256(open(tep, "rb").read()).hexdigest() == sha


# ---------------------------------------------------------------- K3-B: nguồn "dòng bằng chứng" (§8)
async def test_k3b_chi_co_dong_bang_chung_thi_xoa_ho_so_409_dong_va_tep_con(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """Giấy vẫn 'đã tải' (không duyệt / từ chối, không nhật ký duyệt) — CHỈ còn dòng bằng chứng ⇒ K3-B vẫn chặn."""
    prof = await _create_profile(client, await _dn(client, admin_user_in_db), officer_user_in_db, parity_config, "bc_k3b")
    pid = prof["id"]
    noi_dung = PDF + os.urandom(16)
    d = await _tai_len(client, officer_user_in_db, pid, parity_config["upload_doc_code"], noi_dung)
    assert d.status == "uploaded" and d.verified_by is None and d.rejected_by is None
    async with AsyncSessionLocal() as s:
        async with s.begin():
            nk_tai = (
                await s.execute(
                    select(models.DocumentAuditLog.id).where(
                        models.DocumentAuditLog.profile_document_id == d.id, models.DocumentAuditLog.action == "uploaded"
                    )
                )
            ).scalar_one()
            ev = models.DocumentEvidenceFile(
                profile_document_id=d.id, verification_audit_id=nk_tai, profile_id=pid, file_path=d.file_path,
                sha256=hashlib.sha256(noi_dung).hexdigest(), verified_by_user_id=admin_user_in_db["id"],
                verified_at=datetime.now(timezone.utc),
            )
            s.add(ev)
            await s.flush()
            ev_id = ev.id
            # Tiền đề: hai nguồn kia của K3-B đều sạch ⇒ chỉ nguồn "bằng chứng" có thể chặn.
            assert (
                await s.execute(
                    select(models.DocumentAuditLog.id)
                    .join(models.ProfileDocument, models.ProfileDocument.id == models.DocumentAuditLog.profile_document_id)
                    .where(models.ProfileDocument.profile_id == pid, models.DocumentAuditLog.action.in_(("verified", "rejected")))
                )
            ).first() is None
    r = await client.delete(f"{ADMISSIONS}/{pid}", headers=await _dn(client, admin_user_in_db))
    assert r.status_code == 409, r.text
    assert "dùng Rút hồ sơ" in r.json()["detail"]
    await _con_nguyen(pid, d.id, ev_id, d.file_path, hashlib.sha256(noi_dung).hexdigest())


# ---------------------------------------------------------------- RESTRICT ở CSDL — SQL trực tiếp từ phiên riêng
async def test_sql_truc_tiep_xoa_ho_so_co_bang_chung_csdl_tu_choi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, d, ev, noi_dung = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sql_ho_so"
    )
    with pytest.raises(IntegrityError) as loi:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text("DELETE FROM admission_profile WHERE id = :p"), {"p": pid})
    assert _la_vi_pham_khoa_ngoai_bang_chung(loi.value), str(loi.value)
    await _con_nguyen(pid, d.id, ev.id, ev.file_path, ev.sha256)


async def test_sql_truc_tiep_xoa_dong_giay_co_bang_chung_csdl_tu_choi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, d, ev, noi_dung = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sql_giay"
    )
    with pytest.raises(IntegrityError) as loi:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text("DELETE FROM profile_document WHERE id = :d"), {"d": d.id})
    assert _la_vi_pham_khoa_ngoai_bang_chung(loi.value), str(loi.value)
    await _con_nguyen(pid, d.id, ev.id, ev.file_path, ev.sha256)


# ---------------------------------------------------------------- ORM không tự gán NULL (§4.6b)
async def test_orm_xoa_dong_giay_co_bang_chung_bao_loi_khong_tu_gan_null(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_orm_giay"
    )
    with _BatCau() as b:
        with pytest.raises(IntegrityError) as loi:
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    giay = await s.get(models.ProfileDocument, d.id)
                    await s.delete(giay)
                    await s.flush()
    assert b.co(r"^UPDATE document_evidence_file") == [], "ORM tự gán NULL vượt qua RESTRICT"
    assert _la_vi_pham_khoa_ngoai_bang_chung(loi.value), str(loi.value)
    await _con_nguyen(pid, d.id, ev.id, ev.file_path, ev.sha256)


async def test_orm_xoa_nhat_ky_duyet_co_bang_chung_bao_loi_khong_tu_gan_null(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_orm_nhat_ky"
    )
    with _BatCau() as b:
        with pytest.raises(IntegrityError) as loi:
            async with AsyncSessionLocal() as s:
                async with s.begin():
                    nk = await s.get(models.DocumentAuditLog, ev.verification_audit_id)
                    assert nk is not None and nk.action == "verified"
                    await s.delete(nk)
                    await s.flush()
    assert b.co(r"^UPDATE document_evidence_file") == [], "ORM tự gán NULL vượt qua RESTRICT"
    assert _la_vi_pham_khoa_ngoai_bang_chung(loi.value), str(loi.value)
    async with AsyncSessionLocal() as s:
        assert (await s.get(models.DocumentAuditLog, ev.verification_audit_id)) is not None
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.verification_audit_id == ev.verification_audit_id
