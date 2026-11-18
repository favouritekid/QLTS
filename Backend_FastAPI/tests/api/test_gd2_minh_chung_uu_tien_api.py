"""GĐ2-0 — quy tắc duyệt minh chứng ưu tiên (quyết định owner C1, 17-11, ``QUYET-DINH-OWNER-GD1B-2026-11-17.md`` nhóm C).

(a) người tải minh chứng KHÔNG tự duyệt / từ chối; (b) người duyệt = Quản lý trong đơn vị + Admin ("giống giấy tờ").
Mọi ca đi qua REQUEST THẬT trên CSDL thật (router → deps → dịch vụ → CSDL). Không dữ liệu thật. Mỗi ca kiểm một bất biến.

Đường đã rà (CLAUDE.md §6 "vá một nhánh còn bốn nhánh"):
  * ``PATCH /api/v2/admissions/{id}/priority-objects/{mã}/verify`` — (b) + (a);
  * ``PATCH …/reject`` — (b) + (a);
  * ``PUT /api/admissions/{id}`` (``priority_object_evidence`` trong thân) — lối vào thứ hai đặt "đã duyệt";
  * ``POST …/priority-evidence/{mã}/upload`` — ghi người tải, khoá hồ sơ trước;
  * cờ ``permissions.verify_priority_object`` — cùng vị từ với cổng route.
  Giấy thường (``transition_document``) không nhận dòng minh chứng (``category <> 'path'`` ⇒ 404 — sẵn có từ GĐ1b).
"""
from __future__ import annotations

import re
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text

from app import models
from app.database import AsyncSessionLocal, engine
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)

pytestmark = pytest.mark.asyncio

V2 = "/api/v2/admissions"
V1 = "/api/admissions"
MA = "04"
PDF = b"%PDF-1.4\n%\xff\xff\xff\xff\n" + b"x" * 200


async def _sql(cau: str, **ts):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await s.execute(text(cau), ts)


def _khong_cookie(client):
    """Máy chủ ưu tiên cookie ``access_token`` hơn tiêu đề ``Authorization``: cookie của lần đăng nhập SAU CÙNG sẽ đè
    vai của mọi request. Xoá cookie trước MỖI request ⇒ request đi đúng vai của tiêu đề."""
    client.cookies.clear()


async def _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, nhan, trang_thai="submitted"):
    """Hồ sơ đã ghi nhận diện ``MA`` ở trạng thái chờ xét + danh mục mã diện của năm."""
    _khong_cookie(client)
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, nhan)
    pid = prof["id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            co = (
                await s.execute(
                    text("SELECT count(*) FROM priority_object_config WHERE academic_year = 2026 AND sub_code = :m"),
                    {"m": MA},
                )
            ).scalar_one()
            if not co:
                s.add(
                    models.PriorityObjectConfig(
                        academic_year=2026, group_code="UT1", sub_code=MA, description="Diện thử GĐ2-0",
                        bonus_points=Decimal("1.00"), effective_from=date(2025, 1, 1), effective_to=None,
                    )
                )
            await s.execute(
                text(
                    "UPDATE admission_profile SET status = :st, priority_object_codes = CAST(:c AS jsonb) WHERE id = :p"
                ),
                {"st": trang_thai, "c": '["%s"]' % MA, "p": pid},
            )
    return pid


async def _phien_ban(pid: int) -> int:
    return (await _sql("SELECT version FROM admission_profile WHERE id = :p", p=pid)).scalar_one()


async def _minh_chung(pid: int):
    return (
        await _sql("SELECT priority_object_evidence FROM admission_profile WHERE id = :p", p=pid)
    ).scalar_one() or {}


async def _tai_len(client, headers, pid):
    _khong_cookie(client)
    return await client.post(
        f"{V2}/{pid}/priority-evidence/{MA}/upload", headers=headers,
        files={"file": ("ut.pdf", PDF, "application/pdf")},
    )


async def _duyet(client, headers, pid):
    _khong_cookie(client)
    return await client.patch(
        f"{V2}/{pid}/priority-objects/{MA}/verify", headers=headers,
        json={"version": await _phien_ban(pid), "document_id": None},
    )


async def _tu_choi(client, headers, pid):
    _khong_cookie(client)
    return await client.patch(
        f"{V2}/{pid}/priority-objects/{MA}/reject", headers=headers,
        json={"version": await _phien_ban(pid), "reject_reason": "Minh chứng không rõ nét, cần nộp lại"},
    )


@pytest.fixture
def don_tep():
    pids = []
    yield pids
    for pid in pids:
        shutil.rmtree(Path("uploads") / "admissions" / str(pid), ignore_errors=True)


@pytest.fixture
async def ba_vai(client, admin_token_headers, officer_user_in_db, manager_user_in_db):
    vai = {
        "admin": admin_token_headers,
        "can_bo": await _login(client, officer_user_in_db["username"], officer_user_in_db["password"]),
        "quan_ly": await _login(client, manager_user_in_db["username"], manager_user_in_db["password"]),
    }
    _khong_cookie(client)
    return vai


# --------------------------------------------------------------------------------------------------------------------
# (b) — ai được duyệt / từ chối
# --------------------------------------------------------------------------------------------------------------------
async def test_can_bo_phu_trach_khong_duyet_duoc_minh_chung_403(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "b_cb_duyet")
    don_tep.append(pid)
    r = await _duyet(client, ba_vai["can_bo"], pid)
    assert r.status_code == 403, r.text
    assert "Quản lý trong đơn vị" in r.json().get("detail", ""), r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_can_bo_phu_trach_khong_tu_choi_duoc_minh_chung_403(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "b_cb_tc")
    don_tep.append(pid)
    r = await _tu_choi(client, ba_vai["can_bo"], pid)
    assert r.status_code == 403, r.text
    assert "Quản lý trong đơn vị" in r.json().get("detail", ""), r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_quan_ly_don_vi_khac_nhan_404(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, manager_other_unit_user_in_db, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "b_ql_khac")
    don_tep.append(pid)
    h = await _login(client, manager_other_unit_user_in_db["username"], manager_other_unit_user_in_db["password"])
    r = await _duyet(client, h, pid)  # _duyet xoá cookie ⇒ đúng vai của tiêu đề
    assert r.status_code == 404, r.text


async def test_quan_ly_trong_don_vi_duyet_minh_chung_can_bo_tai(
    client: AsyncClient, admin_token_headers, officer_user_in_db, manager_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "b_ql_duyet")
    don_tep.append(pid)
    r = await _tai_len(client, ba_vai["can_bo"], pid)
    assert r.status_code == 200, r.text
    nguoi_tai = (
        await _sql(
            "SELECT uploaded_by, uploaded_by_unknown FROM profile_document WHERE profile_id = :p "
            "AND category = 'priority_evidence' AND priority_sub_code = :m",
            p=pid, m=MA,
        )
    ).one()
    assert tuple(nguoi_tai) == (officer_user_in_db["id"], False)
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 200, r.text
    mc = (await _minh_chung(pid))[MA]
    assert mc["status"] == "verified" and mc["verified_by"] == manager_user_in_db["id"], mc
    assert mc["paper_only_verification"] is False


async def test_co_verify_priority_object_theo_dung_vai(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "b_co")
    don_tep.append(pid)
    co = {}
    for vai, h in ba_vai.items():
        _khong_cookie(client)
        r = await client.get(f"{V1}/{pid}", headers=h)
        assert r.status_code == 200, (vai, r.text)
        co[vai] = r.json()["permissions"]["verify_priority_object"]
    assert co == {"admin": True, "can_bo": False, "quan_ly": True}, co


# --------------------------------------------------------------------------------------------------------------------
# (a) — người tải không tự duyệt / từ chối
# --------------------------------------------------------------------------------------------------------------------
async def test_quan_ly_tu_tai_khong_tu_duyet_409_admin_duyet_duoc(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_ql_tu")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["quan_ly"], pid)).status_code == 200
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409, r.text
    assert r.json().get("error_code") == "PRIORITY_EVIDENCE_OWN_SUBMISSION", r.text
    assert (await _minh_chung(pid)).get(MA) is None
    r = await _duyet(client, ba_vai["admin"], pid)
    assert r.status_code == 200, r.text
    assert (await _minh_chung(pid))[MA]["status"] == "verified"


async def test_quan_ly_tu_tai_khong_tu_tu_choi_409(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_ql_tc")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["quan_ly"], pid)).status_code == 200
    r = await _tu_choi(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409, r.text
    assert r.json().get("error_code") == "PRIORITY_EVIDENCE_OWN_SUBMISSION", r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_admin_tu_tai_cung_khong_tu_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_admin_tu")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["admin"], pid)).status_code == 200
    r = await _duyet(client, ba_vai["admin"], pid)
    assert r.status_code == 409, r.text
    assert r.json().get("error_code") == "PRIORITY_EVIDENCE_OWN_SUBMISSION", r.text
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 200, r.text


async def test_tai_lai_doi_nguoi_tai_luat_theo_nguoi_tai_moi(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Quản lý tải ⇒ không tự duyệt; cán bộ tải LẠI tệp ⇒ người tải mới là cán bộ ⇒ quản lý duyệt được."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_tai_lai")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["quan_ly"], pid)).status_code == 200
    assert (await _duyet(client, ba_vai["quan_ly"], pid)).status_code == 409
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 200, r.text


async def test_tep_khong_ro_nguoi_tai_bi_chan_den_khi_tai_lai(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Tệp có trước GĐ2-0 (``uploaded_by`` NULL) ⇒ không ai duyệt được (409) cho tới khi có người tải lại."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_khong_ro")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    await _sql(
        "UPDATE profile_document SET uploaded_by = NULL WHERE profile_id = :p AND category = 'priority_evidence'", p=pid
    )
    for vai in ("quan_ly", "admin"):
        r = await _duyet(client, ba_vai[vai], pid)
        assert r.status_code == 409, (vai, r.text)
        assert r.json().get("error_code") == "PRIORITY_EVIDENCE_UNKNOWN_SUBMITTER", r.text
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    assert (await _duyet(client, ba_vai["quan_ly"], pid)).status_code == 200


async def test_duyet_ho_so_giay_khong_tep_quan_ly_duoc(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Không có tệp (duyệt theo hồ sơ giấy): không có người tải để so ⇒ Quản lý trong đơn vị duyệt được."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_giay")
    don_tep.append(pid)
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 200, r.text
    assert (await _minh_chung(pid))[MA]["paper_only_verification"] is True


# --------------------------------------------------------------------------------------------------------------------
# Lối vào thứ hai: PUT hồ sơ thường
# --------------------------------------------------------------------------------------------------------------------
async def _put(client, headers, pid, minh_chung):
    _khong_cookie(client)
    return await client.put(
        f"{V1}/{pid}", headers=headers,
        json={"version": await _phien_ban(pid), "priority_object_evidence": minh_chung},
    )


async def test_put_ho_so_khong_dat_duoc_da_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_dat", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    r = await _put(client, ba_vai["can_bo"], pid, {MA: {"status": "verified", "verified_by": officer_user_in_db["id"]}})
    assert r.status_code == 400, r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_put_ho_so_khong_doi_cho_dang_cho_thanh_da_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_doi", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    await _sql(
        "UPDATE admission_profile SET priority_object_evidence = CAST(:e AS jsonb) WHERE id = :p",
        e='{"%s": {"status": "pending"}}' % MA, p=pid,
    )
    r = await _put(client, ba_vai["can_bo"], pid, {MA: {"status": "verified", "verified_by": officer_user_in_db["id"]}})
    assert r.status_code == 400, r.text
    assert (await _minh_chung(pid))[MA]["status"] == "pending"


async def test_put_ho_so_khong_bo_duoc_muc_da_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, admin_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_bo", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    await _sql(
        "UPDATE admission_profile SET priority_object_evidence = CAST(:e AS jsonb) WHERE id = :p",
        e='{"%s": {"status": "verified", "verified_by": %d}}' % (MA, admin_user_in_db["id"]), p=pid,
    )
    r = await _put(client, ba_vai["can_bo"], pid, {MA: {"status": "pending"}})
    assert r.status_code == 400, r.text
    r = await _put(client, ba_vai["can_bo"], pid, {})
    assert r.status_code == 400, r.text
    assert (await _minh_chung(pid))[MA]["status"] == "verified"


async def test_put_ho_so_gui_lai_nguyen_muc_da_duyet_van_qua_va_giu_ban_luu(
    client: AsyncClient, admin_token_headers, officer_user_in_db, admin_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_lai", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    goc = {"status": "verified", "verified_by": admin_user_in_db["id"], "paper_only_verification": True}
    await _sql(
        "UPDATE admission_profile SET priority_object_evidence = CAST(:e AS jsonb) WHERE id = :p",
        e='{"%s": {"status": "verified", "verified_by": %d, "paper_only_verification": true}}'
        % (MA, admin_user_in_db["id"]),
        p=pid,
    )
    r = await _put(
        client, ba_vai["can_bo"], pid,
        {MA: {"status": "verified", "verified_by": admin_user_in_db["id"], "paper_only_verification": False}},
    )
    assert r.status_code == 200, r.text
    assert (await _minh_chung(pid))[MA] == goc


async def test_put_ho_so_van_ghi_duoc_muc_cho_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_cho", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    r = await _put(client, ba_vai["can_bo"], pid, {MA: {"status": "pending"}})
    assert r.status_code == 200, r.text
    assert (await _minh_chung(pid))[MA]["status"] == "pending"


# --------------------------------------------------------------------------------------------------------------------
# Thứ tự khoá: tải minh chứng khoá hồ sơ TRƯỚC câu ghi dòng giấy (người tải không đổi giữa lúc xét và lúc ghi)
# --------------------------------------------------------------------------------------------------------------------
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


async def test_tai_minh_chung_khoa_ho_so_truoc_cau_ghi_giay(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "khoa_tai")
    don_tep.append(pid)
    with _BatCau() as b:
        r = await _tai_len(client, ba_vai["can_bo"], pid)
    assert r.status_code == 200, r.text
    khoa = b.vi_tri(r"FROM admission_profile .*FOR UPDATE")
    ghi = b.vi_tri(r"^(INSERT INTO|UPDATE) profile_document")
    assert khoa is not None and ghi is not None and khoa < ghi, (khoa, ghi)
