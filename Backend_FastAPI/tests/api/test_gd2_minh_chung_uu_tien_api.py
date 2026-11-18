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


async def _duyet(client, headers, pid, **them):
    _khong_cookie(client)
    return await client.patch(
        f"{V2}/{pid}/priority-objects/{MA}/verify", headers=headers,
        json={"version": await _phien_ban(pid), "document_id": None, **them},
    )


async def _tu_choi(client, headers, pid, **them):
    _khong_cookie(client)
    return await client.patch(
        f"{V2}/{pid}/priority-objects/{MA}/reject", headers=headers,
        json={"version": await _phien_ban(pid), "reject_reason": "Minh chứng không rõ nét, cần nộp lại", **them},
    )


async def _ghi_nhan_giay(client, headers, pid):
    _khong_cookie(client)
    return await client.post(f"{V2}/{pid}/priority-evidence/{MA}/paper-submitted", headers=headers)


async def _dong_giay(pid):
    return (
        await _sql(
            "SELECT id, status, file_path, paper_submitted_by, paper_submitted_by_unknown, uploaded_by FROM profile_document "
            "WHERE profile_id = :p AND category = 'priority_evidence' AND priority_sub_code = :m",
            p=pid, m=MA,
        )
    ).one_or_none()


async def _vet_moi_nhat(pid):
    return (
        await _sql(
            # Cột CSDL tên ``metadata`` (thuộc tính ORM ``audit_metadata``).
            'SELECT action_type, actor_id, new_value, "metadata" FROM priority_audit_log WHERE profile_id = :p '
            "ORDER BY id DESC LIMIT 1",
            p=pid,
        )
    ).one()


CAM_KET = {"unknown_submitter_ack": True, "reason": "Đã đối chiếu bản gốc tại phòng tuyển sinh"}


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
    assert r.json().get("error_code") == "OWN_SUBMISSION", r.text
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
    assert r.json().get("error_code") == "OWN_SUBMISSION", r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_admin_tu_tai_cung_khong_tu_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_admin_tu")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["admin"], pid)).status_code == 200
    r = await _duyet(client, ba_vai["admin"], pid)
    assert r.status_code == 409, r.text
    assert r.json().get("error_code") == "OWN_SUBMISSION", r.text
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
    """Tệp có trước GĐ2-0 (``uploaded_by`` NULL) ⇒ KHÔNG cam kết thì không ai duyệt được (409); tải lại tệp là một cách
    gỡ."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a_khong_ro")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    await _sql(
        "UPDATE profile_document SET uploaded_by = NULL WHERE profile_id = :p AND category = 'priority_evidence'", p=pid
    )
    for vai in ("quan_ly", "admin"):
        r = await _duyet(client, ba_vai[vai], pid)
        assert r.status_code == 409, (vai, r.text)
        assert r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    assert (await _duyet(client, ba_vai["quan_ly"], pid)).status_code == 200


async def test_tep_khong_ro_nguoi_tai_co_cam_ket_va_ly_do_thi_quan_ly_duyet_duoc_va_luu_vet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, manager_user_in_db, parity_config, ba_vai, don_tep
):
    """Câu 1 owner 19-11 (N1b A′): Quản lý trong đơn vị đi đường cam kết + lý do ⇒ duyệt được; vết ghi ai / lý do / mã."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a1_tep_ck")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    await _sql(
        "UPDATE profile_document SET uploaded_by = NULL WHERE profile_id = :p AND category = 'priority_evidence'", p=pid
    )
    r = await _duyet(client, ba_vai["quan_ly"], pid, unknown_submitter_ack=True, reason="   ")
    assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    r = await _duyet(client, ba_vai["quan_ly"], pid, unknown_submitter_ack=False, reason="Có lý do mà không cam kết")
    assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    r = await _duyet(client, ba_vai["quan_ly"], pid, **CAM_KET)
    assert r.status_code == 200, r.text
    hanh_dong, nguoi, moi, them = await _vet_moi_nhat(pid)
    assert (hanh_dong, nguoi, moi["sub_code"]) == ("ut_evidence_verified", manager_user_in_db["id"], MA)
    assert (them["unknown_submitter_ack"], them["ack_reason"], them["receiver_kind"]) == (
        True, CAM_KET["reason"], "upload",
    )


async def test_cam_ket_khong_vuot_qua_vai_nguoi_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Đường cam kết vẫn phải qua vị từ người duyệt (C1b): cán bộ có cam kết + lý do vẫn 403."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a1_cb_ck")
    don_tep.append(pid)
    r = await _duyet(client, ba_vai["can_bo"], pid, **CAM_KET)
    assert r.status_code == 403, r.text


async def test_chua_ghi_nhan_giay_khong_ro_nguoi_nhan_can_cam_ket(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Không tệp, chưa ghi nhận bản giấy (mọi lần duyệt giấy trước bản sửa) ⇒ không rõ người nhận ⇒ như câu 1."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_khong_dong")
    don_tep.append(pid)
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    r = await _tu_choi(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    r = await _tu_choi(client, ba_vai["quan_ly"], pid, unknown_submitter_ack=True)
    assert r.status_code == 200, r.text
    assert (await _minh_chung(pid))[MA]["status"] == "rejected"
    them = (await _vet_moi_nhat(pid))[3]
    assert (them["unknown_submitter_ack"], them["receiver_kind"]) == (True, "none")


async def test_can_bo_ghi_nhan_giay_quan_ly_duyet_duoc(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_cb_giay")
    don_tep.append(pid)
    r = await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)
    assert r.status_code == 200, r.text
    dong = await _dong_giay(pid)
    assert (dong.status, dong.file_path, dong.paper_submitted_by, dong.paper_submitted_by_unknown) == (
        "paper_submitted", None, officer_user_in_db["id"], False,
    )
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 200, r.text
    muc = (await _minh_chung(pid))[MA]
    assert (muc["status"], muc["document_id"], muc["paper_only_verification"]) == ("verified", dong.id, True)


async def test_nguoi_nhan_giay_khong_tu_duyet_409(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_ql_duyet")
    don_tep.append(pid)
    assert (await _ghi_nhan_giay(client, ba_vai["quan_ly"], pid)).status_code == 200
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409 and r.json().get("error_code") == "OWN_SUBMISSION", r.text
    r = await _duyet(client, ba_vai["quan_ly"], pid, **CAM_KET)  # cam kết không mở đường cho người nhận đã biết
    assert r.status_code == 409 and r.json().get("error_code") == "OWN_SUBMISSION", r.text
    assert (await _minh_chung(pid)).get(MA) is None
    r = await _duyet(client, ba_vai["admin"], pid)
    assert r.status_code == 200, r.text


async def test_nguoi_nhan_giay_khong_tu_tu_choi_409(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_ql_tc")
    don_tep.append(pid)
    assert (await _ghi_nhan_giay(client, ba_vai["quan_ly"], pid)).status_code == 200
    r = await _tu_choi(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409 and r.json().get("error_code") == "OWN_SUBMISSION", r.text
    assert (await _minh_chung(pid)).get(MA) is None


async def test_giay_khong_ro_nguoi_nhan_can_cam_ket(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Bản ghi giấy cũ mất người nhận ⇒ xử lý như câu 1."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_giay_khong_ro")
    don_tep.append(pid)
    assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200
    await _sql(
        "UPDATE profile_document SET paper_submitted_by = NULL WHERE profile_id = :p AND category = 'priority_evidence'",
        p=pid,
    )
    r = await _duyet(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", r.text
    r = await _duyet(client, ba_vai["quan_ly"], pid, **CAM_KET)
    assert r.status_code == 200, r.text
    assert (await _vet_moi_nhat(pid))[3]["receiver_kind"] == "paper"


async def test_ghi_nhan_giay_chi_mot_lan_va_khong_khi_da_co_tep(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Đổi người nhận không có đường qua ghi nhận lại (chỉ từ "chưa có dòng"); đã có tệp thì không ghi nhận giấy."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_mot_lan")
    don_tep.append(pid)
    assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200
    r = await _ghi_nhan_giay(client, ba_vai["quan_ly"], pid)
    assert r.status_code == 400, r.text
    assert (await _dong_giay(pid)).paper_submitted_by == officer_user_in_db["id"]
    pid2 = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_co_tep")
    don_tep.append(pid2)
    assert (await _tai_len(client, ba_vai["can_bo"], pid2)).status_code == 200
    r = await _ghi_nhan_giay(client, ba_vai["quan_ly"], pid2)
    assert r.status_code == 400, r.text


async def test_dong_bang_chan_ghi_nhan_giay_503(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep, monkeypatch
):
    from app.config import settings

    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "a2_dong_bang")
    don_tep.append(pid)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    r = await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)
    assert r.status_code == 503 and r.json()["code"] == "ADMISSION_FROZEN", r.text
    assert await _dong_giay(pid) is None
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", False)
    assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200


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


@pytest.mark.parametrize(
    "muc",
    [{"status": "pending", "paper_only_verification": True}, {"status": "pending", "document_id": 1}],
)
async def test_put_ho_so_khong_gan_dau_ban_giay_hay_dong_giay_cho_muc_chua_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep, muc
):
    """Câu 2 owner 19-11: đường PUT hồ sơ thường không gắn được cờ "duyệt theo bản giấy" / dòng giấy vào mục chưa duyệt."""
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, "put_dau_giay", trang_thai="revision_requested"
    )
    don_tep.append(pid)
    r = await _put(client, ba_vai["can_bo"], pid, {MA: muc})
    assert r.status_code == 400, r.text
    assert (await _minh_chung(pid)).get(MA) is None


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


async def test_ghi_nhan_giay_khoa_ho_so_truoc_cau_ghi_giay(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "khoa_giay")
    don_tep.append(pid)
    _khong_cookie(client)
    with _BatCau() as b:
        r = await client.post(f"{V2}/{pid}/priority-evidence/{MA}/paper-submitted", headers=ba_vai["can_bo"])
    assert r.status_code == 200, r.text
    khoa = b.vi_tri(r"FROM admission_profile .*FOR UPDATE")
    ghi = b.vi_tri(r"^INSERT INTO profile_document")
    assert khoa is not None and ghi is not None and khoa < ghi, (khoa, ghi)


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
