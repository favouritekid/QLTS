"""GĐ1b §4.6b — tải lại tệp bằng chứng duyệt (hợp đồng API bản 4 §2.3; đặc tả bản 3.6 §4.6b, §9 "Tệp bằng chứng").

Thêm hợp đồng bổ sung bản 5 B6: so sha256 lúc tải (409 ``EVIDENCE_FILE_ALTERED``) + cờ ``file_missing`` tự tắt khi tệp có
mặt ĐÚNG băm.

Mỗi ca kiểm MỘT bất biến; mỗi cổng có biến thể phá riêng (``kiem-thu-phien-a/ma/gd1b_bc_*.json``). Không trùng ca của
``test_gd1b_transition.py`` (ghi sha256 lúc duyệt, tệp mất lúc duyệt, Đặt lại giữ tệp) và ``test_gd1b_khoa_va_tep.py``
(tải lại giữ tệp cũ, dấu tải của route tải thường).

Router chưa đăng ký ở ``app/main.py`` (Claude đăng ký khi tích hợp) ⇒ fixture ``gan_route_bang_chung`` gắn tạm trong phạm
vi MỘT test rồi trả bảng route về như cũ; đã đăng ký sẵn thì không gắn lần hai.

Client giữ cookie đăng nhập và ứng dụng ưu tiên cookie ⇒ mỗi lần đổi người thao tác: xoá cookie rồi đăng nhập lại
(``_dn``). Dữ liệu giả, không dữ liệu thật.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"
PDF = b"%PDF-1.4\n% gd1b bang chung\n"
ROUTE_PATH = "/api/admissions/{profile_id}/documents/{document_row_id}/evidence/{evidence_id}/download"


# ---------------------------------------------------------------- tiện ích
@pytest_asyncio.fixture
async def gan_route_bang_chung(client):
    """Gắn ``app.routers.document_evidence.router`` (prefix ``/api``) cho MỘT test; trả bảng route về như cũ sau test."""
    from app.main import fastapi_app
    from app.routers import document_evidence

    truoc = list(fastapi_app.router.routes)
    if not any(getattr(r, "path", None) == ROUTE_PATH for r in truoc):
        fastapi_app.include_router(document_evidence.router, prefix="/api")
    assert any(getattr(r, "path", None) == ROUTE_PATH for r in fastapi_app.router.routes)
    try:
        yield
    finally:
        fastapi_app.router.routes[:] = truoc


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _url(pid: int, doc_id: int, ev_id: int) -> str:
    return f"{ADMISSIONS}/{pid}/documents/{doc_id}/evidence/{ev_id}/download"


async def _dn(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    return await _login(client, user["username"], user["password"])


async def _giay(pid: int, code: str) -> models.ProfileDocument:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def _bang_chung(doc_id: int) -> list:
    async with AsyncSessionLocal() as s:
        return list(
            (
                await s.execute(
                    select(models.DocumentEvidenceFile)
                    .where(models.DocumentEvidenceFile.profile_document_id == doc_id)
                    .order_by(models.DocumentEvidenceFile.id)
                )
            ).scalars()
        )


async def _tai_len(client, user, pid, code, noi_dung: bytes) -> models.ProfileDocument:
    h = await _dn(client, user)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/upload", headers=h,
        files={"file": ("u.pdf", noi_dung, "application/pdf")}, data={"actual_submission_format": "photo"},
    )
    assert r.status_code in (200, 201), r.text
    return await _giay(pid, code)


async def _duyet(client, user, pid, code) -> models.ProfileDocument:
    d = await _giay(pid, code)
    h = await _dn(client, user)
    r = await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{code}/verify-format", headers=h,
        # Giấy scan duyệt ĐÚNG hình thức đã khai lúc tải lên (owner 18-11, Codex 71 điểm 2).
        json={"format": d.actual_submission_format, "expected_row_version": d.row_version},
    )
    assert r.status_code == 200, r.text
    return await _giay(pid, code)


async def _tu_choi(client, user, pid, code) -> models.ProfileDocument:
    d = await _giay(pid, code)
    h = await _dn(client, user)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/reject", headers=h,
        json={"reason": "Ảnh mờ, nộp lại", "expected_row_version": d.row_version},
    )
    assert r.status_code == 200, r.text
    return await _giay(pid, code)


async def _ho_so_co_bang_chung(client, admin, officer, cfg, admin_headers, hau_to, noi_dung=None):
    """Hồ sơ (cán bộ ``officer`` phụ trách) + giấy tải tệp do cán bộ tải, Admin duyệt ⇒ đúng một dòng bằng chứng.

    Dựng hồ sơ bằng một lượt đăng nhập Admin MỚI: Admin đăng nhập lại ở bước duyệt làm phiên của ``admin_token_headers``
    bị thu hồi (401 ở lần dựng hồ sơ thứ hai trong cùng test)."""
    noi_dung = noi_dung or PDF + os.urandom(32)
    prof = await _create_profile(client, await _dn(client, admin), officer, cfg, hau_to)
    assert "id" in prof, prof
    code = cfg["upload_doc_code"]
    await _tai_len(client, officer, prof["id"], code, noi_dung)
    d = await _duyet(client, admin, prof["id"], code)
    (ev,) = await _bang_chung(d.id)
    return prof["id"], d, ev, noi_dung


async def _tao_quyen_cheo(grantee_id: int, unit_id: int, admin_id: int) -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(
                models.DocumentCrossReviewGrant(
                    grantee_user_id=grantee_id, unit_id=unit_id, allow_verify=True, allow_reject=True,
                    granted_by_user_id=admin_id, expires_at=datetime.now(timezone.utc) + timedelta(days=2),
                    reason="Hỗ trợ duyệt giấy đơn vị bạn",
                )
            )


# ---------------------------------------------------------------- sha256 (§9: đổi một byte ⇒ sha khác)
async def test_sha256_bang_chung_la_bam_noi_dung_doi_mot_byte_thi_khac(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """Cùng giấy, duyệt hai lần với hai tệp chỉ khác BYTE CUỐI ⇒ hai sha256 khác nhau, mỗi sha đúng bằng băm nội dung.

    Tệp dài hơn 1 MiB (khối đọc của ``_sha256_file``) ⇒ byte khác nằm NGOÀI khối đầu: băm chỉ khối đầu cũng bị bắt."""
    a = PDF + os.urandom((1 << 20) + 64)
    b = a[:-1] + bytes([a[-1] ^ 0x01])
    pid, d, _, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_mot_byte", a
    )
    code = parity_config["upload_doc_code"]
    await _tu_choi(client, admin_user_in_db, pid, code)
    await _tai_len(client, officer_user_in_db, pid, code, b)
    await _duyet(client, admin_user_in_db, pid, code)
    e1, e2 = await _bang_chung(d.id)
    assert e1.sha256 != e2.sha256, "đổi một byte mà sha256 không đổi"
    assert (e1.sha256, e2.sha256) == (_sha(a), _sha(b))


# ---------------------------------------------------------------- tải tệp mới không ghi đè tệp đã duyệt
async def test_tai_tep_moi_khong_ghi_de_tep_da_duyet_tai_bang_chung_tra_dung_tep_da_duyet(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, a = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_khong_ghi_de"
    )
    code = parity_config["upload_doc_code"]
    await _tu_choi(client, admin_user_in_db, pid, code)
    b = PDF + os.urandom(32)
    moi = await _tai_len(client, officer_user_in_db, pid, code, b)
    assert moi.file_path != ev.file_path
    (ev_sau,) = await _bang_chung(d.id)
    assert (ev_sau.file_path, ev_sau.sha256) == (ev.file_path, ev.sha256), "đường dẫn tệp đã duyệt là bất biến"
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 200, r.text
    assert r.content == a and _sha(r.content) == ev.sha256, "tải bằng chứng phải trả ĐÚNG tệp lúc duyệt, không tệp mới"


# ---------------------------------------------------------------- phạm vi (§4.6b, §9)
async def test_quan_ly_dung_don_vi_va_admin_tai_duoc_bang_chung(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, a = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_pham_vi_dung"
    )
    for user in (manager_user_in_db, admin_user_in_db):
        r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, user))
        assert r.status_code == 200, (user["username"], r.text)
        assert r.content == a
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["content-type"] == "application/pdf"


async def test_quan_ly_sai_don_vi_tai_bang_chung_404(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_other_unit_user_in_db,
    officer_user_in_db, parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sai_don_vi"
    )
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_other_unit_user_in_db))
    assert r.status_code == 404, r.text


async def test_can_bo_phu_trach_tai_bang_chung_404(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """Cán bộ phụ trách lead (đọc được hồ sơ) vẫn KHÔNG tải được bằng chứng — chỉ Quản lý / Admin."""
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_can_bo"
    )
    h = await _dn(client, officer_user_in_db)
    assert (await client.get(f"{ADMISSIONS}/{pid}", headers=h)).status_code == 200, "tiền đề: cán bộ đọc được hồ sơ"
    r = await client.get(_url(pid, d.id, ev.id), headers=h)
    assert r.status_code == 404, r.text


async def test_can_bo_duoc_cap_duyet_cheo_tai_bang_chung_404(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, officer_user_in_db, seed_other_unit,
    parity_config,
):
    """Cán bộ đơn vị khác có quyền duyệt chéo CÒN HIỆU LỰC trên đơn vị của lead ⇒ vẫn 404 (quyền chéo không mở K2)."""
    from tests.conftest import _create_user_and_role

    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_cheo"
    )
    cheo = await _create_user_and_role(
        {"username": "gd1b_bc_cheo", "email": "gd1b_bc_cheo@example.com", "password": "CheoPassword!345",
         "role": "officer", "status": "active"},
        "role:officer", unit_id=seed_other_unit["unit_id"],
    )
    await _tao_quyen_cheo(cheo["id"], parity_config["unit_id"], admin_user_in_db["id"])
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, cheo))
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------- bằng chứng phải thuộc ĐÚNG giấy + hồ sơ
async def test_bang_chung_cua_giay_khac_cung_ho_so_404(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_giay_khac"
    )
    giay_khac = await _giay(pid, parity_config["paper_doc_code"])
    r = await client.get(_url(pid, giay_khac.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 404, r.text


async def test_bang_chung_cua_ho_so_ngoai_pham_vi_ghep_vao_url_ho_so_trong_pham_vi_404(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    seed_other_unit, parity_config,
):
    """Quản lý đơn vị 1 ghép (giấy, bằng chứng) của hồ sơ đơn vị KHÁC vào URL hồ sơ mình được xem ⇒ 404, không lộ tệp."""
    pid_1, _, _, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_ghep_1"
    )
    pid_2, d2, ev2, b = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_ghep_2"
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)"),
                {"u": seed_other_unit["unit_id"], "p": pid_2},
            )
    h = await _dn(client, manager_user_in_db)
    assert (await client.get(f"{ADMISSIONS}/{pid_2}", headers=h)).status_code == 404, "tiền đề: hồ sơ 2 ngoài phạm vi"
    r = await client.get(_url(pid_1, d2.id, ev2.id), headers=h)
    assert r.status_code == 404, r.text
    assert b not in r.content


# ---------------------------------------------------------------- đường dẫn kiểm bằng _resolve_under
@pytest.mark.parametrize("kieu", ["di_nguoc", "tuyet_doi"])
async def test_duong_dan_csdl_ra_ngoai_thu_muc_ho_so_thi_404_khong_phuc_vu_khong_danh_dau_mat(
    kieu, client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, f"bc_duong_dan_{kieu}"
    )
    nan_nhan = f"uploads/admissions/{pid + 100000}/nan-nhan.pdf"
    bi_mat = PDF + b"tep-cua-ho-so-khac" + os.urandom(16)
    os.makedirs(os.path.dirname(nan_nhan), exist_ok=True)
    with open(nan_nhan, "wb") as f:
        f.write(bi_mat)
    gia = (
        f"uploads/admissions/{pid}/../{pid + 100000}/nan-nhan.pdf" if kieu == "di_nguoc" else os.path.abspath(nan_nhan)
    )
    try:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text("UPDATE document_evidence_file SET file_path = :p WHERE id = :e"), {"p": gia, "e": ev.id})
        r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
        assert r.status_code == 404, r.text
        assert bi_mat not in r.content
        (ev_sau,) = await _bang_chung(d.id)
        assert ev_sau.file_missing is False, "đường dẫn sai lệch KHÔNG phải tệp mất"
    finally:
        if os.path.exists(nan_nhan):
            os.remove(nan_nhan)
            os.rmdir(os.path.dirname(nan_nhan))


# ---------------------------------------------------------------- tệp mất: 410, file_missing, lịch sử không đổi
async def test_tep_bang_chung_mat_thi_410_evidence_file_missing_khong_500(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_mat_410"
    )
    os.remove(ev.file_path)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 410, r.text
    assert r.json()["error_code"] == "EVIDENCE_FILE_MISSING"


async def test_tep_bang_chung_mat_thi_file_missing_true_da_commit(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """Cờ ghi ở giao dịch RIÊNG, commit dù phản hồi là lỗi 410 — đọc lại từ một phiên khác."""
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_mat_co"
    )
    assert ev.file_missing is False
    os.remove(ev.file_path)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 410, r.text
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.file_missing is True


async def test_tep_bang_chung_mat_thi_lich_su_khong_doi_khong_ghi_dau_tai(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_mat_lich_su"
    )

    async def _anh_lich_su():
        async with AsyncSessionLocal() as s:
            nk = (
                await s.execute(
                    select(models.DocumentAuditLog.id, models.DocumentAuditLog.action)
                    .where(models.DocumentAuditLog.profile_document_id == d.id)
                    .order_by(models.DocumentAuditLog.id)
                )
            ).all()
            dau = (
                await s.execute(
                    select(models.DocumentDownloadLog.id).where(models.DocumentDownloadLog.document_row_id == d.id)
                )
            ).all()
            bc = (
                await s.execute(
                    select(models.DocumentEvidenceFile.id, models.DocumentEvidenceFile.verification_audit_id)
                    .where(models.DocumentEvidenceFile.profile_document_id == d.id)
                )
            ).all()
        return [tuple(x) for x in nk], [tuple(x) for x in dau], [tuple(x) for x in bc]

    truoc = await _anh_lich_su()
    os.remove(ev.file_path)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 410, r.text
    sau = await _anh_lich_su()
    assert sau == truoc, (truoc, sau)
    assert sau[1] == [], "tệp không còn ⇒ không có lượt tải nào để ghi"


# ---------------------------------------------------------------- B6 (hợp đồng bổ sung bản 5): sha256 lúc tải + cờ tự tắt
def _doi_byte_cuoi(duong_dan: str) -> bytes:
    """Đổi BYTE CUỐI của tệp trên ổ (đọc → ghi tệp tạm → thay), trả nội dung mới đã đọc lại."""
    goc = open(duong_dan, "rb").read()
    moi = goc[:-1] + bytes([goc[-1] ^ 0x01])
    tam = duong_dan + ".tam"
    with open(tam, "wb") as f:
        f.write(moi)
    os.replace(tam, duong_dan)
    doc_lai = open(duong_dan, "rb").read()
    assert doc_lai == moi and doc_lai != goc and len(doc_lai) == len(goc), "HẠ TẦNG: chưa đổi được byte"
    return moi


async def _dat_co_bang_chung(ev_id: int, sql_set: str) -> None:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text(f"UPDATE document_evidence_file SET {sql_set} WHERE id = :e"), {"e": ev_id})


async def _dem_tai(doc_id: int) -> tuple:
    """(số dòng ``downloaded``, số dòng ``document_download_log``) của giấy — đọc từ phiên riêng."""
    async with AsyncSessionLocal() as s:
        nk = (
            await s.execute(
                select(models.DocumentAuditLog.id).where(
                    models.DocumentAuditLog.profile_document_id == doc_id, models.DocumentAuditLog.action == "downloaded"
                )
            )
        ).all()
        dau = (
            await s.execute(select(models.DocumentDownloadLog.id).where(models.DocumentDownloadLog.document_row_id == doc_id))
        ).all()
    return len(nk), len(dau)


async def test_tep_bang_chung_bi_sua_mot_byte_thi_409_khong_tra_tep_khong_ghi_nhat_ky_co_khong_doi(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """B6a. Tệp > 1 MiB, đổi byte CUỐI (ngoài khối đọc đầu) ⇒ băm phải là băm TOÀN tệp mới bắt được."""
    a = PDF + os.urandom((1 << 20) + 64)
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sua_byte", a
    )
    moi = _doi_byte_cuoi(ev.file_path)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 409, r.status_code
    assert r.json()["error_code"] == "EVIDENCE_FILE_ALTERED"
    assert moi[-64:] not in r.content and len(r.content) < 4096, "không trả tệp"
    assert await _dem_tai(d.id) == (0, 0), "không ghi nhật ký tải"
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.file_missing is False, "file_missing không đổi"


async def test_co_mat_tep_dang_bat_ma_tep_co_mat_dung_noi_dung_thi_200_va_tat_co(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """B6b. Tệp được khôi phục ĐÚNG nội dung ⇒ trả tệp, cờ về false (commit — đọc lại từ phiên riêng)."""
    pid, d, ev, a = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_tat_co"
    )
    await _dat_co_bang_chung(ev.id, "file_missing = true")
    (ev_bat,) = await _bang_chung(d.id)
    assert ev_bat.file_missing is True, "tiền đề: cờ đang bật"
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 200, r.text
    assert r.content == a
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.file_missing is False


async def test_co_mat_tep_dang_bat_ma_tep_co_mat_sai_noi_dung_thi_409_co_van_bat(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """B6b/B6a. Tệp "khôi phục" SAI nội dung ⇒ 409, cờ VẪN bật (chỉ tự tắt khi chứng minh được đúng tệp)."""
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sai_khoi_phuc"
    )
    await _dat_co_bang_chung(ev.id, "file_missing = true")
    _doi_byte_cuoi(ev.file_path)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 409, r.status_code
    assert r.json()["error_code"] == "EVIDENCE_FILE_ALTERED"
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.file_missing is True


async def test_sha_da_ghi_rong_thi_khong_chung_minh_duoc_409_co_van_bat(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """Dòng bằng chứng điền ngược lúc migration khi tệp đã mất (sha256 NULL, cờ bật) mà tệp xuất hiện lại ⇒ không có gì để
    chứng minh ⇒ 409, không trả tệp, cờ VẪN bật."""
    pid, d, ev, a = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_sha_rong"
    )
    await _dat_co_bang_chung(ev.id, "file_missing = true, sha256 = NULL")
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 409, r.status_code
    assert r.json()["error_code"] == "EVIDENCE_FILE_ALTERED"
    assert a not in r.content
    (ev_sau,) = await _bang_chung(d.id)
    assert ev_sau.file_missing is True


# ---------------------------------------------------------------- nhật ký tải: khoá bằng route tải thường (một nguồn)
async def test_tai_bang_chung_ghi_nhat_ky_giong_het_route_tai_thuong(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    """Hai bản ghi nhật ký tải (route tải thường trong ``admission_service`` và route bằng chứng) phải sinh ĐÚNG cùng dòng
    ``downloaded`` + ``document_download_log`` (trừ id / giờ / ``extra_data.evidence_id``) và cùng tiêu đề phản hồi.

    Cũng là ca B6 (d): tải bình thường (tệp có mặt, khớp sha256) vẫn ghi nhật ký như cũ."""
    pid, d, ev, a = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_nhat_ky"
    )
    h = await _dn(client, manager_user_in_db)
    r_thuong = await client.get(f"{ADMISSIONS}/{pid}/documents/{d.id}/download", headers=h)
    r_bc = await client.get(_url(pid, d.id, ev.id), headers=h)
    assert (r_thuong.status_code, r_bc.status_code) == (200, 200), (r_thuong.text, r_bc.text)
    assert r_thuong.content == r_bc.content == a
    for tieu_de in ("content-type", "content-disposition", "cache-control", "referrer-policy", "x-content-type-options"):
        assert r_thuong.headers.get(tieu_de) == r_bc.headers.get(tieu_de), tieu_de

    async with AsyncSessionLocal() as s:
        nk = list(
            (
                await s.execute(
                    select(models.DocumentAuditLog)
                    .where(models.DocumentAuditLog.profile_document_id == d.id, models.DocumentAuditLog.action == "downloaded")
                    .order_by(models.DocumentAuditLog.id)
                )
            ).scalars()
        )
        dau = list(
            (
                await s.execute(
                    select(models.DocumentDownloadLog)
                    .where(models.DocumentDownloadLog.document_row_id == d.id)
                    .order_by(models.DocumentDownloadLog.id)
                )
            ).scalars()
        )
    assert len(nk) == 2 and len(dau) == 2, (len(nk), len(dau))
    cot_nk = [c.name for c in models.DocumentAuditLog.__table__.columns if c.name not in {"id", "created_at", "extra_data"}]
    cot_dau = [c.name for c in models.DocumentDownloadLog.__table__.columns if c.name not in {"id", "downloaded_at", "source_audit_id"}]
    assert {c: getattr(nk[0], c) for c in cot_nk} == {c: getattr(nk[1], c) for c in cot_nk}
    assert {c: getattr(dau[0], c) for c in cot_dau} == {c: getattr(dau[1], c) for c in cot_dau}
    assert (nk[1].extra_data or {}) == {"evidence_id": ev.id}
    assert [x.source_audit_id for x in dau] == [x.id for x in nk], "dấu tải trỏ đúng dòng nhật ký cùng lượt"
    assert dau[1].actor_user_id == manager_user_in_db["id"] and dau[1].profile_id == pid
