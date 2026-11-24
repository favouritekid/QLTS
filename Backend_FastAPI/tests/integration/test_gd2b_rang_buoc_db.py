# -*- coding: utf-8 -*-
"""GĐ2-B (lát L1) — ràng buộc CSDL của lần xét nháp / điểm sàn / lượt chạy / dòng kết quả, đo bằng câu SQL TRỰC TIẾP (SQL tay —
không qua dịch vụ; dịch vụ chỉ là lớp phụ). Tầng chủ sở hữu: trigger ``app/models/admission_review_ddl.py`` + CHECK / UNIQUE / khoá
ngoại ``app/models/admission_review.py``. Đặc tả GĐ2-B bản 4 §4.2, §4.3, §10 (BT27, BT28 phần SQL tay, BT37, BT38); hợp đồng API
bản 4 §1.3, §6, §7.

Mỗi ca kiểm MỘT bất biến; lỗi so bằng (SQLSTATE, tên ràng buộc) — không đọc chữ thông báo. Dữ liệu GIẢ:

* ca một phiên dùng fixture ``c`` của ``test_quota_occupancy_db.py`` (một giao dịch, lùi khi ra; hai học vụ X / Y năm 2026, đợt
  ``vong`` năm 2026, người dùng ``nguoi``);
* ca HAI PHIÊN (khoá ``FOR SHARE`` của trigger) dựng nền đã commit (``setup_test_database`` xoá sạch ở ca sau), "chờ" đo bằng
  ``pg_blocking_pids`` từ phiên thứ ba (khuôn ``tests/api/test_gd2a_bang_chi_tieu_api.py``).
"""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as csdl
from app.repositories.council_decision_repository import db_error_codes
from tests.fixtures.hoi_dong_seed import danh_muc
from tests.integration.test_quota_occupancy_db import _x, c  # noqa: F401

pytestmark = pytest.mark.integration

NAM = 2026
QLC02 = "QLC02"  # lần xét không còn nháp (admission_review_ddl.SQLSTATE_REVIEW_SESSION_NOT_DRAFT)
QLC03 = "QLC03"  # dữ liệu lần xét bất biến (admission_review_ddl.SQLSTATE_REVIEW_IMMUTABLE)
QLC04 = "QLC04"  # huỷ ở mức cô lập không hỗ trợ (admission_review_ddl.SQLSTATE_REVIEW_ISOLATION_UNSUPPORTED)

CHEN_LAN_XET = (
    "INSERT INTO admission_review_session (academic_year, admission_round_id, seq_no, created_by_user_id) "
    "VALUES (:y, :r, :s, :u) RETURNING id"
)
HUY = (
    "UPDATE admission_review_session SET status = 'cancelled', cancelled_by_user_id = :u, cancelled_at = now(), "
    "cancel_reason = 'Lý do thử', version = version + 1 WHERE id = :s"
)
CHEN_SAN = (
    "INSERT INTO admission_review_floor (session_id, academic_year, offering_academic_info_id, floor_score, "
    "updated_by_user_id) VALUES (:s, :y, :a, :f, :u)"
)
XONG = (
    "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 5, "
    "summary = CAST('{}' AS jsonb), quota_view = CAST('{}' AS jsonb) WHERE id = :r"
)
HONG = "UPDATE admission_review_run SET status = 'failed', finished_at = now(), duration_ms = 5, error_code = 'thu' WHERE id = :r"


# ── Dựng dữ liệu ───────────────────────────────────────────────────────────────────────────────────────────────────────
async def _bat(c, cau, **ts):
    """Chạy ``cau`` trong một savepoint; trả lỗi CSDL (đã lùi savepoint) hoặc ``None`` nếu KHÔNG lỗi."""
    sp = await c.begin_nested()
    try:
        await _x(c, cau, **ts)
    except DBAPIError as e:
        await sp.rollback()
        return e
    await sp.rollback()
    return None


async def _loi(c, cau, **ts):
    """(SQLSTATE, tên ràng buộc) của lỗi, hoặc ``None`` nếu câu chạy được (rồi lùi)."""
    e = await _bat(c, cau, **ts)
    return None if e is None else db_error_codes(e)


async def _bang(c, nam=NAM):
    await _x(c, "INSERT INTO admission_quota_table (academic_year) VALUES (:y)", y=nam)


async def _dot(c, nam):
    return (
        await _x(
            c,
            "INSERT INTO offering_admission_round (academic_year, round_code, round_name) VALUES (:y, :m, 'Đợt giả') "
            "RETURNING id",
            y=nam, m="GIA-%d" % nam,
        )
    ).scalar_one()


async def _nguoi(c, ten):
    return (
        await _x(
            c,
            'INSERT INTO "user" (username, email, password_hash, role, total_lead_score) '
            "VALUES (:t, :e, 'x', 'officer', 0) RETURNING id",
            t=ten, e=ten + "@example.invalid",
        )
    ).scalar_one()


async def _lan_xet(c, *, so=1, nam=NAM, dot=None, nguoi=None, co_bang=True):
    """Một lần xét nháp; ``co_bang`` = tạo luôn bảng chỉ tiêu năm (lần đầu của năm)."""
    if co_bang:
        await _x(
            c,
            "INSERT INTO admission_quota_table (academic_year) VALUES (:y) ON CONFLICT (academic_year) DO NOTHING",
            y=nam,
        )
    d = c.info["d"]
    return (
        await _x(c, CHEN_LAN_XET, y=nam, r=dot or d["vong"], s=so, u=nguoi or d["nguoi"])
    ).scalar_one()


async def _huy(c, sid, nguoi=None):
    await _x(c, HUY, u=nguoi or c.info["d"]["nguoi"], s=sid)


def _ts_san(c, sid, o="X", diem="15.00", nam=NAM, nguoi=None):
    return dict(s=sid, y=nam, a=c.info[o]["ai"], f=Decimal(diem), u=nguoi or c.info["d"]["nguoi"])


async def _san(c, sid, o="X", **kw):
    await _x(c, CHEN_SAN, **_ts_san(c, sid, o, **kw))


async def _luot(c, sid, status="running", nguoi=None):
    bat_dau = "NULL" if status == "queued" else "now()"
    return (
        await _x(
            c,
            "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, "
            "inputs) VALUES (:s, 'evaluate', :st, 'gd2b-1', :u, %s, CAST(:i AS jsonb)) RETURNING id" % bat_dau,
            s=sid, st=status, u=nguoi or c.info["d"]["nguoi"], i=json.dumps({"academic_year": NAM, "floors": []}),
        )
    ).scalar_one()


_JSON = {"per_choice", "document_gaps", "prior_year_findings"}
_MANG = {"reason_codes", "flags", "decision_hints"}


def _dong_khong_du(**sua):
    """Dòng ``ineligible`` vì điều kiện hồ sơ (E1 — ngoài tập xét): ``per_choice`` rỗng, không ưu tiên, không điểm."""
    return {
        "profile_id": 9001, "profile_status": "revision_requested", "tab": "ineligible",
        "reason_codes": ["status_not_in_pool"], "per_choice": [], "row_hash": "a" * 64, **sua,
    }


def _dong_dat(c, **sua):
    """Dòng ``auto`` hợp lệ: có NV được xếp (học vụ X) + điểm."""
    x = c.info["X"]
    return {
        "profile_id": 9002, "profile_status": "submitted", "tab": "auto", "reason_codes": [],
        "considered_choice_id": 11, "considered_display_order": 1, "considered_offering_academic_info_id": x["ai"],
        "considered_offering_id": x["off"], "considered_admission_path_id": x["path"],
        "review_total": Decimal("18.50"), "floor_score": Decimal("15.00"), "rank_in_major": 1, "within_seats": True,
        "ethnic_priority_state": "not_applicable",
        "per_choice": [{"choice_id": 11, "status": "passed_floor"}], "row_hash": "b" * 64, **sua,
    }


def _cau_dong(rid, cot):
    ten, gia, ts = ["run_id"], [":run_id"], {"run_id": rid}
    for k, v in cot.items():
        ten.append(k)
        if k in _JSON:
            gia.append("CAST(:%s AS jsonb)" % k)
            ts[k] = json.dumps(v)
        elif k in _MANG:
            gia.append("CAST(:%s AS text[])" % k)
            ts[k] = list(v)
        else:
            gia.append(":%s" % k)
            ts[k] = v
    return "INSERT INTO admission_review_row (%s) VALUES (%s)" % (", ".join(ten), ", ".join(gia)), ts


async def _dong(c, rid, cot):
    cau, ts = _cau_dong(rid, cot)
    await _x(c, cau, **ts)


async def _loi_dong(c, rid, cot):
    cau, ts = _cau_dong(rid, cot)
    return await _loi(c, cau, **ts)


async def _dem(c, bang, cot, gia):
    return (await _x(c, "SELECT count(*) FROM %s WHERE %s = :v" % (bang, cot), v=gia)).scalar_one()


# ── Đối chứng: dữ liệu hợp lệ chèn được (nếu không, mọi ca "bị chặn" dưới có thể đỏ vì lý do khác) ───────────────────
async def test_doi_chung_lan_xet_san_luot_dong_hop_le_chen_duoc(c):
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    rid = await _luot(c, sid)
    await _dong(
        c, rid,
        _dong_dat(
            c, flags=["same_citizen_admitted_previous_year"],
            prior_year_findings=[{"year": 2025, "basis": "occupying_status", "status": "enrolled"}],
        ),
    )
    await _dong(c, rid, _dong_khong_du())
    await _x(c, XONG, r=rid)
    assert await _dem(c, "admission_review_row", "run_id", rid) == 2
    # Không truyền ⇒ mặc định mảng rỗng (không có cờ A13).
    assert (
        await _x(
            c, "SELECT prior_year_findings = '[]' FROM admission_review_row WHERE run_id = :r AND profile_id = 9001", r=rid
        )
    ).scalar_one() is True
    assert await _dem(c, "admission_review_floor", "session_id", sid) == 1


# ── Lần xét ────────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_lan_xet_da_huy_khong_sua_duoc(c):
    sid = await _lan_xet(c)
    await _huy(c, sid)
    assert await _loi(c, "UPDATE admission_review_session SET version = version + 1 WHERE id = :s", s=sid) == (
        QLC02, None
    )


async def test_lan_xet_khong_xoa_duoc(c):
    sid = await _lan_xet(c)
    assert await _loi(c, "DELETE FROM admission_review_session WHERE id = :s", s=sid) == (QLC03, None)


async def test_lan_xet_khong_doi_nam(c):
    """Năm của lần xét không bao giờ đổi (E4 đọc năm TRƯỚC khi lấy khoá năm). Câu đổi năm hợp lệ về mọi mặt khác (bảng chỉ tiêu +
    đợt của năm mới có thật, không có sàn) ⇒ chỉ trigger chặn."""
    sid = await _lan_xet(c)
    await _bang(c, 2027)
    dot_2027 = await _dot(c, 2027)
    assert await _loi(
        c, "UPDATE admission_review_session SET academic_year = 2027, admission_round_id = :r WHERE id = :s",
        r=dot_2027, s=sid,
    ) == (QLC03, None)


async def test_huy_lan_xet_khi_con_san_bi_chan(c):
    """P4: lần xét đã huỷ không giữ sàn nào ⇒ chuyển ``cancelled`` khi còn dòng sàn bị chặn (E5 phải xoá sàn TRƯỚC)."""
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    assert await _loi(c, HUY, u=c.info["d"]["nguoi"], s=sid) == (QLC03, None)


async def test_huy_lan_xet_sau_khi_xoa_san_thi_duoc(c):
    """Đối chứng của ca trên — ĐÚNG thứ tự E5: xoá sàn (lúc còn ``draft``) rồi chuyển ``cancelled`` ⇒ được, 0 dòng sàn."""
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    await _x(c, "DELETE FROM admission_review_floor WHERE session_id = :s", s=sid)
    await _huy(c, sid)
    assert await _dem(c, "admission_review_floor", "session_id", sid) == 0


@pytest.mark.parametrize(
    "cau, rang_buoc",
    [
        ("UPDATE admission_review_session SET status = 'locked' WHERE id = :s", "ck_admission_review_session_status"),
        ("UPDATE admission_review_session SET version = 0 WHERE id = :s", "ck_admission_review_session_version"),
        (
            "UPDATE admission_review_session SET status = 'cancelled', cancelled_by_user_id = created_by_user_id, "
            "cancelled_at = now() WHERE id = :s",
            "ck_admission_review_session_cancelled",
        ),
        (
            "UPDATE admission_review_session SET status = 'cancelled', cancelled_by_user_id = created_by_user_id, "
            "cancelled_at = now(), cancel_reason = '   ' WHERE id = :s",
            "ck_admission_review_session_cancelled",
        ),
        ("UPDATE admission_review_session SET cancelled_at = now() WHERE id = :s", "ck_admission_review_session_cancel_clear"),
    ],
    ids=["trang_thai_la", "phien_ban_0", "huy_thieu_ly_do", "huy_ly_do_trang", "nhap_co_cot_huy"],
)
async def test_check_lan_xet(c, cau, rang_buoc):
    sid = await _lan_xet(c)
    assert await _loi(c, cau, s=sid) == ("23514", rang_buoc)


async def test_so_thu_tu_phai_duong(c):
    await _bang(c)
    d = c.info["d"]
    assert await _loi(c, CHEN_LAN_XET, y=NAM, r=d["vong"], s=0, u=d["nguoi"]) == (
        "23514", "ck_admission_review_session_seq_no"
    )


async def test_so_thu_tu_khong_trung_trong_nam(c):
    await _lan_xet(c, so=1)
    d = c.info["d"]
    assert await _loi(c, CHEN_LAN_XET, y=NAM, r=d["vong"], s=1, u=d["nguoi"]) == (
        "23505", "uq_admission_review_session_year_seq"
    )


async def test_nam_chua_co_bang_chi_tieu_khong_tao_duoc_lan_xet(c):
    dot_2027 = await _dot(c, 2027)
    assert await _loi(c, CHEN_LAN_XET, y=2027, r=dot_2027, s=1, u=c.info["d"]["nguoi"]) == (
        "23503", "fk_admission_review_session_quota_table"
    )


async def test_dot_khac_nam_khong_tao_duoc_lan_xet(c):
    """Khoá ngoại GHÉP (đợt, năm): đợt năm 2026 không dùng được cho lần xét năm 2027 (bảng chỉ tiêu 2027 có thật)."""
    await _bang(c, 2027)
    assert await _loi(c, CHEN_LAN_XET, y=2027, r=c.info["d"]["vong"], s=1, u=c.info["d"]["nguoi"]) == (
        "23503", "fk_admission_review_session_round"
    )


# ── Điểm sàn (BT28 phần SQL tay) ───────────────────────────────────────────────────────────────────────────────────────
async def test_ghi_san_khi_lan_xet_da_huy_bi_chan(c):
    sid = await _lan_xet(c)
    await _huy(c, sid)
    assert await _loi(c, CHEN_SAN, **_ts_san(c, sid, "X")) == (QLC02, None)


async def _san_mo_coi(c):
    """Trạng thái CẤM dựng bằng chế độ replica (trigger + khoá ngoại tắt, CHECK vẫn chạy): lần xét ``cancelled`` còn MỘT dòng sàn
    (học vụ X). Trả (id lần xét đã huỷ, id dòng sàn)."""
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    await _x(c, "SET LOCAL session_replication_role = replica")
    await _huy(c, sid)
    await _x(c, "SET LOCAL session_replication_role = origin")
    fid = (await _x(c, "SELECT id FROM admission_review_floor WHERE session_id = :s", s=sid)).scalar_one()
    return sid, fid


async def test_sua_san_chuyen_khoi_lan_xet_da_huy_bi_chan(c):
    """Nhánh OLD của trigger: chuyển dòng sàn từ lần xét ĐÃ HUỶ sang một lần xét NHÁP (đích hợp lệ) ⇒ vẫn bị chặn."""
    _, fid = await _san_mo_coi(c)
    nhap = await _lan_xet(c, so=2)
    assert await _loi(c, "UPDATE admission_review_floor SET session_id = :n WHERE id = :f", n=nhap, f=fid) == (QLC02, None)


async def test_xoa_san_cua_lan_xet_da_huy_bi_chan(c):
    _, fid = await _san_mo_coi(c)
    assert await _loi(c, "DELETE FROM admission_review_floor WHERE id = :f", f=fid) == (QLC02, None)


async def test_sua_san_chuyen_vao_lan_xet_da_huy_bi_chan(c):
    """Nhánh NEW của trigger cho UPDATE: dòng sàn của lần xét NHÁP chuyển sang lần xét ĐÃ HUỶ ⇒ bị chặn."""
    nhap = await _lan_xet(c, so=1)
    await _san(c, nhap, "X")
    da_huy = await _lan_xet(c, so=2)
    await _huy(c, da_huy)
    assert await _loi(
        c, "UPDATE admission_review_floor SET session_id = :h WHERE session_id = :n", h=da_huy, n=nhap
    ) == (QLC02, None)


async def test_diem_san_am_bi_chan(c):
    sid = await _lan_xet(c)
    assert await _loi(c, CHEN_SAN, **_ts_san(c, sid, "X", diem="-0.01")) == ("23514", "ck_admission_review_floor_score")


async def test_mot_hoc_vu_mot_muc_san_trong_lan_xet(c):
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    assert await _loi(c, CHEN_SAN, **_ts_san(c, sid, "X", diem="16.00")) == (
        "23505", "uq_admission_review_floor_session_oai"
    )


async def _doi_nam_y(c, nam=2027):
    await _x(c, "UPDATE offering_academic_info SET academic_year = :y WHERE id = :a", y=nam, a=c.info["Y"]["ai"])


async def test_san_tro_hoc_vu_khac_nam_bi_chan(c):
    """Khoá ngoại GHÉP (học vụ, năm): học vụ Y đã sang 2027 ⇒ không đặt sàn cho Y ở lần xét 2026."""
    sid = await _lan_xet(c)
    await _doi_nam_y(c)
    assert await _loi(c, CHEN_SAN, **_ts_san(c, sid, "Y")) == ("23503", "fk_admission_review_floor_oai")


async def test_san_khac_nam_lan_xet_bi_chan(c):
    """Khoá ngoại GHÉP (lần xét, năm): dòng sàn khai năm 2027 (học vụ Y năm 2027 có thật) cho lần xét năm 2026 ⇒ bị chặn."""
    sid = await _lan_xet(c)
    await _doi_nam_y(c)
    assert await _loi(c, CHEN_SAN, **_ts_san(c, sid, "Y", nam=2027)) == ("23503", "fk_admission_review_floor_session")


async def test_doi_nam_hoc_vu_dang_co_san_qua_sql_vap_khoa_ngoai(c):
    """§4.3: khoá ngoại ghép không ``ON UPDATE`` ⇒ dời năm học vụ đang có sàn bằng SQL tay vấp khoá ngoại (đường API: dịch vụ
    kiểm trước ⇒ 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` — lát L3a)."""
    sid = await _lan_xet(c)
    await _san(c, sid, "X")
    assert await _loi(
        c, "UPDATE offering_academic_info SET academic_year = 2027 WHERE id = :a", a=c.info["X"]["ai"]
    ) == ("23503", "fk_admission_review_floor_oai")


# ── Lượt chạy ──────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_tao_luot_thang_o_done_bi_chan(c):
    sid = await _lan_xet(c)
    assert await _loi(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, "
        "finished_at, duration_ms, inputs, summary, quota_view) VALUES (:s, 'evaluate', 'done', 'gd2b-1', :u, now(), now(), "
        "1, CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('{}' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    ) == (QLC03, None)


async def test_luot_di_lui_bi_chan(c):
    """``running → queued`` (cột đặt đúng dạng ``queued`` ⇒ CHECK cho qua) — chỉ trigger chặn."""
    rid = await _luot(c, await _lan_xet(c))
    assert await _loi(
        c, "UPDATE admission_review_run SET status = 'queued', started_at = NULL WHERE id = :r", r=rid
    ) == (QLC03, None)


async def test_luot_nhay_coc_queued_sang_done_bi_chan(c):
    rid = await _luot(c, await _lan_xet(c), status="queued")
    assert await _loi(
        c,
        "UPDATE admission_review_run SET status = 'done', started_at = now(), finished_at = now(), duration_ms = 1, "
        "summary = CAST('{}' AS jsonb), quota_view = CAST('{}' AS jsonb) WHERE id = :r",
        r=rid,
    ) == (QLC03, None)


@pytest.mark.parametrize("ket_thuc", [XONG, HONG], ids=["done", "failed"])
async def test_luot_da_xong_khong_sua_duoc(c, ket_thuc):
    """BT27: lượt ``done`` / ``failed`` là cuối — sửa một cột không đổi trạng thái cũng bị chặn."""
    rid = await _luot(c, await _lan_xet(c))
    await _x(c, ket_thuc, r=rid)
    assert await _loi(c, "UPDATE admission_review_run SET duration_ms = 6 WHERE id = :r", r=rid) == (QLC03, None)


async def test_luot_khong_xoa_duoc(c):
    rid = await _luot(c, await _lan_xet(c))
    await _x(c, XONG, r=rid)
    assert await _loi(c, "DELETE FROM admission_review_run WHERE id = :r", r=rid) == (QLC03, None)


async def test_hai_luot_dang_chay_cung_lan_xet_bi_chan(c):
    sid = await _lan_xet(c)
    await _luot(c, sid, status="running")
    e = await _bat(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, inputs) "
        "VALUES (:s, 'evaluate', 'queued', 'gd2b-1', :u, CAST('{}' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    )
    assert db_error_codes(e) == ("23505", "uq_admission_review_run_session_active")


async def test_chay_lai_sau_luot_da_xong_duoc(c):
    """Đối chứng của ca trên: UNIQUE chỉ áp cho lượt ``queued`` / ``running`` ⇒ lượt mới sau lượt ``done`` chèn được."""
    sid = await _lan_xet(c)
    r1 = await _luot(c, sid)
    await _x(c, XONG, r=r1)
    await _luot(c, sid)
    assert await _dem(c, "admission_review_run", "session_id", sid) == 2


async def test_luot_dang_chay_thieu_gio_bat_dau_bi_chan(c):
    sid = await _lan_xet(c)
    assert await _loi(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, inputs) "
        "VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, CAST('{}' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    ) == ("23514", "ck_admission_review_run_state_columns")


@pytest.mark.parametrize(
    "cau",
    [
        "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 5 WHERE id = :r",
        "UPDATE admission_review_run SET status = 'failed', finished_at = now(), duration_ms = 5 WHERE id = :r",
        # Đợt 1 sau Codex B3: ``done`` chỉ nhận JSON OBJECT — JSON ``null`` (khác SQL NULL) / mảng đều bị chặn.
        "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 5, "
        "summary = CAST('null' AS jsonb), quota_view = CAST('{}' AS jsonb) WHERE id = :r",
        "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 5, "
        "summary = CAST('{}' AS jsonb), quota_view = CAST('[]' AS jsonb) WHERE id = :r",
    ],
    ids=["done_thieu_ket_qua", "failed_thieu_ma_loi", "done_summary_json_null", "done_quota_view_mang"],
)
async def test_luot_ket_thuc_thieu_cot_bi_chan(c, cau):
    rid = await _luot(c, await _lan_xet(c))
    assert await _loi(c, cau, r=rid) == ("23514", "ck_admission_review_run_state_columns")


async def test_luot_chua_xong_ket_qua_json_null_bi_chan(c):
    """Codex B3 vế "SQL NULL ≠ JSON null" ở lượt CHƯA xong: ``queued`` đòi ``summary`` là SQL NULL — JSON ``null`` (ghi thẳng, không
    qua ``none_as_null``) bị chặn."""
    sid = await _lan_xet(c)
    assert await _loi(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, inputs, summary) "
        "VALUES (:s, 'evaluate', 'queued', 'gd2b-1', :u, CAST('{}' AS jsonb), CAST('null' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    ) == ("23514", "ck_admission_review_run_state_columns")


async def test_thoi_luong_am_bi_chan(c):
    rid = await _luot(c, await _lan_xet(c))
    assert await _loi(
        c,
        "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = -1, "
        "summary = CAST('{}' AS jsonb), quota_view = CAST('{}' AS jsonb) WHERE id = :r",
        r=rid,
    ) == ("23514", "ck_admission_review_run_duration")


async def test_loai_luot_la_bi_chan(c):
    sid = await _lan_xet(c)
    assert await _loi(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, inputs) "
        "VALUES (:s, 'proposal', 'queued', 'gd2b-1', :u, CAST('{}' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    ) == ("23514", "ck_admission_review_run_kind")


async def test_trang_thai_luot_la_bi_chan(c):
    """Trigger chặn trạng thái lạ trước CHECK ⇒ đo CHECK ở chế độ replica (trigger tắt, CHECK vẫn chạy)."""
    sid = await _lan_xet(c)
    await _x(c, "SET LOCAL session_replication_role = replica")
    loi = await _loi(
        c,
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, inputs) "
        "VALUES (:s, 'evaluate', 'paused', 'gd2b-1', :u, CAST('{}' AS jsonb))",
        s=sid, u=c.info["d"]["nguoi"],
    )
    await _x(c, "SET LOCAL session_replication_role = origin")
    assert loi == ("23514", "ck_admission_review_run_status")


# ── Dòng kết quả (BT27) ────────────────────────────────────────────────────────────────────────────────────────────────
async def test_chen_dong_vao_luot_da_xong_bi_chan(c):
    rid = await _luot(c, await _lan_xet(c))
    await _dong(c, rid, _dong_khong_du())
    await _x(c, XONG, r=rid)
    assert await _loi_dong(c, rid, _dong_khong_du(profile_id=9003)) == (QLC03, None)


@pytest.mark.parametrize("xong", [False, True], ids=["luot_dang_chay", "luot_da_xong"])
async def test_sua_dong_bi_chan(c, xong):
    """Dòng chỉ thêm — sửa bị chặn kể cả khi lượt CÒN ``running``."""
    rid = await _luot(c, await _lan_xet(c))
    await _dong(c, rid, _dong_khong_du())
    if xong:
        await _x(c, XONG, r=rid)
    assert await _loi(c, "UPDATE admission_review_row SET row_hash = :h WHERE run_id = :r", h="c" * 64, r=rid) == (
        QLC03, None
    )


@pytest.mark.parametrize("xong", [False, True], ids=["luot_dang_chay", "luot_da_xong"])
async def test_xoa_dong_bi_chan(c, xong):
    rid = await _luot(c, await _lan_xet(c))
    await _dong(c, rid, _dong_khong_du())
    if xong:
        await _x(c, XONG, r=rid)
    assert await _loi(c, "DELETE FROM admission_review_row WHERE run_id = :r", r=rid) == (QLC03, None)


async def test_mot_ho_so_mot_dong_trong_luot(c):
    rid = await _luot(c, await _lan_xet(c))
    await _dong(c, rid, _dong_khong_du())
    assert await _loi_dong(c, rid, _dong_khong_du(row_hash="d" * 64)) == ("23505", "uq_admission_review_row_run_profile")


#: (tên ca, dòng, ràng buộc) — mỗi dòng sai ĐÚNG MỘT điều.
CA_CHECK_DONG = [
    ("tab_la", lambda c: _dong_khong_du(tab="excluded"), "ck_admission_review_row_tab"),
    ("bam_sai_dang", lambda c: _dong_khong_du(row_hash="A" * 64), "ck_admission_review_row_hash"),
    ("dat_khong_co_nv_duoc_xep", lambda c: _dong_dat(c, considered_choice_id=None), "ck_admission_review_row_placed"),
    (
        "chua_dat_ma_co_nv_duoc_xep",
        lambda c: _dong_dat(c, tab="not_passed", reason_codes=["all_choices_failed"]),
        "ck_admission_review_row_placed",
    ),
    ("dat_thieu_tong_diem", lambda c: _dong_dat(c, review_total=None), "ck_admission_review_row_placed_fields"),
    ("dat_thieu_khoa_dem", lambda c: _dong_dat(c, considered_offering_id=None), "ck_admission_review_row_placed_fields"),
    ("can_quyet_khong_ly_do", lambda c: _dong_dat(c, tab="needs_decision"), "ck_admission_review_row_reasons"),
    ("trang_thai_uu_tien_la", lambda c: _dong_dat(c, ethnic_priority_state="unknown"), "ck_admission_review_row_ethnic_state"),
    ("nguyen_vong_khong_phai_mang", lambda c: _dong_khong_du(per_choice={}), "ck_admission_review_row_per_choice_array"),
    (
        "phat_hien_nam_truoc_khong_phai_mang",
        lambda c: _dong_dat(c, prior_year_findings={"year": 2025, "basis": "occupying_status", "status": "enrolled"}),
        "ck_admission_review_row_prior_year_findings_array",
    ),
    (
        "truot_dieu_kien_ho_so_co_trang_thai_uu_tien",
        lambda c: _dong_khong_du(ethnic_priority_state="provisional_by_commune"),
        "ck_admission_review_row_profile_condition",
    ),
    (
        "truot_dieu_kien_ho_so_co_tong_diem",
        lambda c: _dong_khong_du(review_total=Decimal("12.00")),
        "ck_admission_review_row_profile_condition",
    ),
]


@pytest.mark.parametrize("i", range(len(CA_CHECK_DONG)), ids=[x[0] for x in CA_CHECK_DONG])
async def test_check_dong(c, i):
    _, dung, rang_buoc = CA_CHECK_DONG[i]
    rid = await _luot(c, await _lan_xet(c))
    assert await _loi_dong(c, rid, dung(c)) == ("23514", rang_buoc)


async def test_dung_o_mot_nv_van_co_trang_thai_uu_tien(c):
    """Đối chứng của P2: ``ineligible`` vì DỪNG Ở MỘT NV (đã qua E1–E7, ``per_choice`` có NV ấy) được mang trạng thái ưu tiên đã
    tính — CHECK chỉ cấm khi ``per_choice`` rỗng (trượt điều kiện hồ sơ)."""
    rid = await _luot(c, await _lan_xet(c))
    await _dong(
        c, rid,
        _dong_khong_du(
            profile_status="submitted", reason_codes=["floor_missing"], ethnic_priority_state="provisional_by_commune",
            per_choice=[{"choice_id": 21, "status": "config_missing", "reason_codes": ["floor_missing"]}],
        ),
    )
    assert await _dem(c, "admission_review_row", "run_id", rid) == 1


# ── Handler: SQLSTATE trigger → lỗi API ────────────────────────────────────────────────────────────────────────────────
def _yeu_cau(path="/api/admission-config/review-sessions/1/floors"):
    return SimpleNamespace(url=SimpleNamespace(path=path), method="PUT")


async def test_loi_trigger_qlc02_qua_handler_cung_than_voi_loi_dich_vu(c):
    """Hợp đồng §1.3: lỗi trigger điểm sàn ⇒ 409 CÙNG ``error_code`` / ``reason_code`` / ``detail`` với lỗi kiểm trước ở dịch vụ,
    không có ``status``. Lỗi THẬT của trigger (không giả)."""
    from app.middleware.exception_handlers import base_app_exception_handler, database_error_handler
    from app.services.admission_review_errors import review_session_not_draft

    sid = await _lan_xet(c)
    await _huy(c, sid)
    loi = await _bat(c, CHEN_SAN, **_ts_san(c, sid, "X"))
    assert db_error_codes(loi)[0] == QLC02
    r = await database_error_handler(_yeu_cau(), loi)
    mau = await base_app_exception_handler(_yeu_cau(), review_session_not_draft())
    than = json.loads(r.body)
    assert (r.status_code, than) == (409, json.loads(mau.body))
    assert than["error_code"] == "REVIEW_SESSION_NOT_DRAFT" and than["reason_code"] == "review_session_not_draft"
    assert "status" not in than


async def test_loi_bat_bien_qlc03_khong_doi_o_handler(c):
    """``QLC03`` cố ý KHÔNG đổi ở handler (không route GĐ2-B nào tới được) ⇒ ném lại NGUYÊN lỗi ⇒ nhánh chung 500."""
    from app.middleware.exception_handlers import database_error_handler

    sid = await _lan_xet(c)
    loi = await _bat(c, "DELETE FROM admission_review_session WHERE id = :s", s=sid)
    assert db_error_codes(loi)[0] == QLC03
    with pytest.raises(DBAPIError) as e:
        await database_error_handler(_yeu_cau(), loi)
    assert e.value is loi


# ── BT37: người dùng đã thao tác trên lần xét không xoá được ───────────────────────────────────────────────────────────
async def _nguoi_chi_o_cot(c, cot):
    """Một người dùng MỚI chỉ xuất hiện ở đúng cột ``cot`` (bảng.cột) của GĐ2-B; trả id."""
    u = await _nguoi(c, "gd2b_k4_" + cot.replace(".", "_"))
    if cot == "admission_review_session.created_by_user_id":
        await _lan_xet(c, nguoi=u)
    elif cot == "admission_review_session.cancelled_by_user_id":
        await _huy(c, await _lan_xet(c), nguoi=u)
    elif cot == "admission_review_floor.updated_by_user_id":
        await _san(c, await _lan_xet(c), "X", nguoi=u)
    elif cot == "admission_review_run.requested_by_user_id":
        await _luot(c, await _lan_xet(c), nguoi=u)
    else:  # pragma: no cover
        raise AssertionError(cot)
    return u


COT_NGUOI_DUNG = [
    "admission_review_session.created_by_user_id",
    "admission_review_session.cancelled_by_user_id",
    "admission_review_floor.updated_by_user_id",
    "admission_review_run.requested_by_user_id",
]
KHOA_NGOAI_NGUOI_DUNG = {
    "admission_review_session.created_by_user_id": "fk_admission_review_session_created_by",
    "admission_review_session.cancelled_by_user_id": "fk_admission_review_session_cancelled_by",
    "admission_review_floor.updated_by_user_id": "fk_admission_review_floor_updated_by",
    "admission_review_run.requested_by_user_id": "fk_admission_review_run_requested_by",
}


@pytest.mark.parametrize("cot", COT_NGUOI_DUNG)
async def test_xoa_tai_khoan_da_thao_tac_tren_lan_xet_bi_chan_o_dich_vu(c, cot):
    """K4 (tầng chủ sở hữu = ``assert_user_deletable``): người dùng chỉ có vết ở MỘT cột GĐ2-B ⇒ 409 ``USER_HAS_ACTIVITY``."""
    from app.services.user_deletion_policy import UserNotDeletable, assert_user_deletable

    u = await _nguoi_chi_o_cot(c, cot)
    async with AsyncSession(bind=c) as db:
        with pytest.raises(UserNotDeletable) as e:
            await assert_user_deletable(db, [u], actor_id=c.info["d"]["nguoi"])
    assert e.value.error_code == "USER_HAS_ACTIVITY"


@pytest.mark.parametrize("cot", COT_NGUOI_DUNG)
async def test_xoa_tai_khoan_da_thao_tac_bang_sql_vap_khoa_ngoai_restrict(c, cot):
    """Lớp phòng thủ thêm: khoá ngoại RESTRICT — SQL tay xoá người dùng ấy cũng bị chặn, đúng khoá ngoại của cột."""
    u = await _nguoi_chi_o_cot(c, cot)
    assert await _loi(c, 'DELETE FROM "user" WHERE id = :u', u=u) == ("23503", KHOA_NGOAI_NGUOI_DUNG[cot])


# ── Hai phiên: khoá ``FOR SHARE`` của trigger ──────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def nen(setup_test_database):
    """Nền ĐÃ COMMIT: danh mục giả, bảng chỉ tiêu 2026, một lần xét nháp có sàn cho học vụ X, một lượt ``running``."""
    async with csdl.engine.begin() as conn:
        d = await danh_muc(conn)
        hv = {}
        for ten, nganh in (("X", "oto_cd"), ("Y", "duoc_cd")):
            path = d["psg"][(nganh, "cq", "g1")][0]
            hv[ten] = (
                await conn.execute(text("SELECT academic_info_id FROM admission_path WHERE id = :p"), {"p": path})
            ).scalar_one()
        await conn.execute(text("INSERT INTO admission_quota_table (academic_year) VALUES (:y)"), {"y": NAM})
        sid = (
            await conn.execute(text(CHEN_LAN_XET), {"y": NAM, "r": d["vong"], "s": 1, "u": d["nguoi"]})
        ).scalar_one()
        await conn.execute(
            text(CHEN_SAN), {"s": sid, "y": NAM, "a": hv["X"], "f": Decimal("15.00"), "u": d["nguoi"]}
        )
        rid = (
            await conn.execute(
                text(
                    "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, "
                    "started_at, inputs) VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, now(), CAST('{}' AS jsonb)) "
                    "RETURNING id"
                ),
                {"s": sid, "u": d["nguoi"]},
            )
        ).scalar_one()
    return {"nguoi": d["nguoi"], "hv": hv, "sid": sid, "rid": rid}


async def _pid(conn) -> int:
    return (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def _bi_chan_boi(pid_cho: int, pid_giu: int, viec) -> bool:
    """Hỏi CSDL từ phiên THỨ BA (``pg_blocking_pids``): phiên ``pid_cho`` có đang chờ khoá do ``pid_giu`` giữ không. Việc đã xong
    (không chờ gì) ⇒ False ngay."""
    for _ in range(100):
        await asyncio.sleep(0.05)
        if viec.done():
            return False
        async with csdl.engine.connect() as k3:
            chan = (await k3.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pid_cho})).scalar_one()
        if pid_giu in (chan or []):
            return True
    return False


async def _don(giu, cho, viec) -> None:
    """Dọn hai phiên kể cả khi ca đỏ giữa chừng: nhả phiên GIỮ khoá trước, chờ việc đang chờ xong, rồi đóng phiên chờ."""
    for k in (giu,):
        try:
            await k.rollback()
        finally:
            await k.close()
    if viec is not None:
        try:
            await asyncio.wait_for(viec, 10)
        except (Exception, asyncio.CancelledError):  # kết quả đã được ca kiểm đọc, hoặc ca đã đỏ ở bước trước
            pass
    try:
        await cho.rollback()
    finally:
        await cho.close()


async def test_hai_phien_huy_dang_do_thi_ghi_san_bang_sql_tay_phai_cho_roi_bi_chan(nen):
    """Phiên A = giao dịch huỷ (E5: dòng lần xét ``FOR UPDATE`` → xoá sàn → ``cancelled``), CHƯA commit. Phiên B = SQL tay chèn
    sàn cho học vụ Y vào CHÍNH lần xét ấy ⇒ B phải CHỜ đúng A; A commit ⇒ B đọc lại dòng lần xét (``FOR SHARE``), thấy
    ``cancelled`` ⇒ ``QLC02``. Lần xét đã huỷ còn 0 dòng sàn (P4)."""
    sid, u = nen["sid"], nen["nguoi"]
    a, b = await csdl.engine.connect(), await csdl.engine.connect()
    viec = None
    try:
        await a.begin()
        await b.begin()
        pa = await _pid(a)
        await a.execute(text("SELECT id FROM admission_review_session WHERE id = :s FOR UPDATE"), {"s": sid})
        await a.execute(text("DELETE FROM admission_review_floor WHERE session_id = :s"), {"s": sid})
        await a.execute(text(HUY), {"u": u, "s": sid})
        pb = await _pid(b)
        viec = asyncio.ensure_future(
            b.execute(text(CHEN_SAN), {"s": sid, "y": NAM, "a": nen["hv"]["Y"], "f": Decimal("14.00"), "u": u})
        )
        assert await _bi_chan_boi(pb, pa, viec), "ghi sàn KHÔNG chờ giao dịch huỷ đang dở"
        await a.commit()
        with pytest.raises(DBAPIError) as e:
            await viec
        assert db_error_codes(e.value)[0] == QLC02
    finally:
        await _don(a, b, viec)
    async with csdl.engine.connect() as k:
        assert (
            await k.execute(text("SELECT count(*) FROM admission_review_floor WHERE session_id = :s"), {"s": sid})
        ).scalar_one() == 0
        assert (
            await k.execute(text("SELECT status FROM admission_review_session WHERE id = :s"), {"s": sid})
        ).scalar_one() == "cancelled"


async def test_hai_phien_chuyen_done_dang_do_thi_chen_dong_phai_cho_roi_bi_chan(nen):
    """Phiên A chuyển lượt ``running → done`` (CHƯA commit). Phiên B chèn một dòng vào lượt ấy ⇒ B phải CHỜ đúng A (trigger dòng
    đọc lượt ``FOR SHARE``); A commit ⇒ B thấy ``done`` ⇒ ``QLC03``. Lượt đã xong không có dòng chen sau."""
    rid = nen["rid"]
    a, b = await csdl.engine.connect(), await csdl.engine.connect()
    viec = None
    try:
        await a.begin()
        await b.begin()
        pa = await _pid(a)
        await a.execute(text(XONG), {"r": rid})
        pb = await _pid(b)
        cau, ts = _cau_dong(rid, _dong_khong_du())
        viec = asyncio.ensure_future(b.execute(text(cau), ts))
        assert await _bi_chan_boi(pb, pa, viec), "chèn dòng KHÔNG chờ lệnh chuyển done đang dở"
        await a.commit()
        with pytest.raises(DBAPIError) as e:
            await viec
        assert db_error_codes(e.value)[0] == QLC03
    finally:
        await _don(a, b, viec)
    async with csdl.engine.connect() as k:
        assert (
            await k.execute(text("SELECT count(*) FROM admission_review_row WHERE run_id = :r"), {"r": rid})
        ).scalar_one() == 0


# ── B2 (Codex đợt 1): "lần xét đã huỷ còn 0 dòng sàn" ở MỌI thứ tự và mức cô lập ─────────────────────────────────────────
async def _huy_kieu_e5(conn, sid, u):
    """Đúng thứ tự E5 (đặc tả §6.8): dòng lần xét ``FOR UPDATE`` → xoá mọi sàn → chuyển ``cancelled``."""
    await conn.execute(text("SELECT id FROM admission_review_session WHERE id = :s FOR UPDATE"), {"s": sid})
    await conn.execute(text("DELETE FROM admission_review_floor WHERE session_id = :s"), {"s": sid})
    await conn.execute(text(HUY), {"u": u, "s": sid})


async def _mo(muc=None):
    """Kết nối + giao dịch ở mức cô lập ``muc`` (``None`` = mặc định ``read committed``); ĐO lại mức thật trong giao dịch."""
    k = await csdl.engine.connect()
    if muc is not None:
        await k.execution_options(isolation_level=muc)
    await k.begin()
    that = (await k.execute(text("SELECT current_setting('transaction_isolation')"))).scalar_one()
    assert that == (muc or "READ COMMITTED").lower(), that
    return k


async def _trang_thai_cuoi(sid):
    """(trạng thái lần xét, số dòng sàn của nó, số lần xét ĐÃ HUỶ còn sàn — bất biến P4, phải 0) đọc từ phiên MỚI."""
    async with csdl.engine.connect() as k:
        st = (await k.execute(text("SELECT status FROM admission_review_session WHERE id = :s"), {"s": sid})).scalar_one()
        n = (
            await k.execute(text("SELECT count(*) FROM admission_review_floor WHERE session_id = :s"), {"s": sid})
        ).scalar_one()
        mo_coi = (
            await k.execute(
                text(
                    "SELECT count(*) FROM admission_review_session s WHERE s.status = 'cancelled' "
                    "AND EXISTS (SELECT 1 FROM admission_review_floor f WHERE f.session_id = s.id)"
                )
            )
        ).scalar_one()
    return st, n, mo_coi


async def test_hai_phien_rc_chen_san_dang_do_thi_huy_cho_roi_giai_phong_ca_san_moi(nen):
    """RC, CHÈN TRƯỚC: phiên A chèn sàn (học vụ Y) CHƯA commit (giữ ``FOR SHARE`` dòng lần xét). Phiên B huỷ theo E5 ⇒ B phải CHỜ
    đúng A ở ``FOR UPDATE``; A commit ⇒ B xoá CẢ sàn mới (câu xoá lấy ảnh chụp sau khi chờ) ⇒ ``cancelled``, 0 dòng sàn."""
    sid, u = nen["sid"], nen["nguoi"]
    a, b = await _mo(), await _mo()
    viec = None
    try:
        pa = await _pid(a)
        await a.execute(text(CHEN_SAN), {"s": sid, "y": NAM, "a": nen["hv"]["Y"], "f": Decimal("14.00"), "u": u})
        pb = await _pid(b)
        viec = asyncio.ensure_future(_huy_kieu_e5(b, sid, u))
        assert await _bi_chan_boi(pb, pa, viec), "huỷ KHÔNG chờ lệnh chèn sàn đang dở"
        await a.commit()
        await viec
        await b.commit()
    finally:
        await _don(a, b, viec)
    assert await _trang_thai_cuoi(sid) == ("cancelled", 0, 0)


async def test_rr_huy_co_anh_chup_truoc_khi_san_moi_commit_thi_bi_tu_choi(nen):
    """Codex B2: phiên huỷ B ở REPEATABLE READ đã lấy ảnh chụp; phiên khác chèn sàn (học vụ Y) rồi COMMIT (chỉ giữ ``FOR SHARE`` dòng
    lần xét — không tạo phiên bản dòng mới). B chạy E5: ảnh chụp cũ không thấy sàn mới ⇒ nếu cho huỷ thì sàn mồ côi. Trigger chỉ
    cho huỷ ở ``read committed`` ⇒ ``QLC04``; lần xét vẫn nháp, sàn còn nguyên — không lần xét đã huỷ nào còn sàn."""
    sid, u = nen["sid"], nen["nguoi"]
    b = await _mo("REPEATABLE READ")
    try:
        assert (
            await b.execute(text("SELECT count(*) FROM admission_review_floor WHERE session_id = :s"), {"s": sid})
        ).scalar_one() == 1  # ảnh chụp của B: chỉ sàn X
        async with csdl.engine.begin() as k:
            await k.execute(text(CHEN_SAN), {"s": sid, "y": NAM, "a": nen["hv"]["Y"], "f": Decimal("14.00"), "u": u})
        with pytest.raises(DBAPIError) as e:
            await _huy_kieu_e5(b, sid, u)
        assert db_error_codes(e.value)[0] == QLC04
    finally:
        await b.rollback()
        await b.close()
    assert await _trang_thai_cuoi(sid) == ("draft", 2, 0)


async def test_loi_qlc04_qua_handler_la_500_ma_rieng_khong_ghi_gi(nen):
    """Codex 22-11 lượt 2 (E5): ``QLC04`` (huỷ ở mức cô lập khác ``read committed`` — lỗi lập trình) GIỮ 500 nhưng có thân CỐ ĐỊNH
    ``error_code = REVIEW_ISOLATION_UNSUPPORTED``; không lộ câu SQL / tham số; lần xét vẫn nháp, sàn còn nguyên. Lỗi THẬT của trigger.
    (Ca READ COMMITTED đo trên CHÍNH giao dịch huỷ của dịch vụ E5 — làm khi có L3a.)"""
    from app.middleware.exception_handlers import database_error_handler

    sid, u = nen["sid"], nen["nguoi"]
    b = await _mo("REPEATABLE READ")
    try:
        with pytest.raises(DBAPIError) as e:
            await _huy_kieu_e5(b, sid, u)
    finally:
        await b.rollback()
        await b.close()
    assert db_error_codes(e.value)[0] == QLC04
    r = await database_error_handler(_yeu_cau("/api/admission-config/review-sessions/%d/cancel" % sid), e.value)
    than = json.loads(r.body)
    assert r.status_code == 500, (r.status_code, than)
    assert set(than) == {"detail", "error_code"} and than["error_code"] == "REVIEW_ISOLATION_UNSUPPORTED", than
    assert "admission_review" not in than["detail"] and "QLC04" not in than["detail"], than
    assert await _trang_thai_cuoi(sid) == ("draft", 1, 0)


async def test_rr_ghi_san_khi_huy_commit_sau_anh_chup_thi_loi_tuan_tu_hoa(nen):
    """RR, HUỶ TRƯỚC: phiên A (REPEATABLE READ) đã lấy ảnh chụp; phiên B huỷ theo E5 CHƯA commit. A chèn sàn ⇒ CHỜ đúng B; B commit
    (dòng lần xét có phiên bản mới SAU ảnh chụp của A) ⇒ ``FOR SHARE`` của trigger sàn ném lỗi tuần tự hoá ``40001`` ⇒ không sàn
    nào chen vào lần xét đã huỷ."""
    sid, u = nen["sid"], nen["nguoi"]
    a = await _mo("REPEATABLE READ")
    b = await _mo()
    viec = None
    try:
        await a.execute(text("SELECT count(*) FROM admission_review_session"))  # lấy ảnh chụp của A
        pb = await _pid(b)
        await _huy_kieu_e5(b, sid, u)
        pa = await _pid(a)
        viec = asyncio.ensure_future(
            a.execute(text(CHEN_SAN), {"s": sid, "y": NAM, "a": nen["hv"]["Y"], "f": Decimal("14.00"), "u": u})
        )
        assert await _bi_chan_boi(pa, pb, viec), "chèn sàn KHÔNG chờ giao dịch huỷ đang dở"
        await b.commit()
        with pytest.raises(DBAPIError) as e:
            await viec
        assert db_error_codes(e.value)[0] == "40001"
    finally:
        await _don(b, a, viec)
    assert await _trang_thai_cuoi(sid) == ("cancelled", 0, 0)


@pytest.mark.parametrize("muc", ["REPEATABLE READ", "SERIALIZABLE"])
async def test_huy_o_muc_co_lap_khac_read_committed_bi_tu_choi(nen, muc):
    """Một phiên, không ai chen: huỷ ở mức cô lập khác ``read committed`` vẫn bị từ chối (``QLC04``) — chặn theo MỨC, không theo
    việc có tranh chấp hay không."""
    sid, u = nen["sid"], nen["nguoi"]
    b = await _mo(muc)
    try:
        with pytest.raises(DBAPIError) as e:
            await _huy_kieu_e5(b, sid, u)
        assert db_error_codes(e.value)[0] == QLC04
    finally:
        await b.rollback()
        await b.close()
    assert await _trang_thai_cuoi(sid) == ("draft", 1, 0)
