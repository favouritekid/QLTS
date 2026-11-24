# -*- coding: utf-8 -*-
"""GĐ2-B (lát L1) — ``app/repositories/admission_review_repository.py`` trên PostgreSQL thật (dữ liệu GIẢ trong một giao dịch, lùi
khi ra — fixture ``c`` của ``test_quota_occupancy_db.py``). Chỉ kiểm phần truy cập dữ liệu mà các lát sau dựa vào: số thứ tự lớn
nhất, xoá sàn trả danh sách đã giải phóng, lần xét đang giữ một học vụ, chèn dòng theo lô, thứ tự + lọc của E9 (hợp đồng §2 E9),
lượt mới nhất. Không luật nghiệp vụ (repository không có). Mỗi ca kiểm một hành vi.
"""
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import admission_review_repository as repo
from tests.integration.test_gd2b_rang_buoc_db import XONG, _lan_xet, _luot
from tests.integration.test_quota_occupancy_db import _x, c  # noqa: F401

pytestmark = pytest.mark.integration

NAM = 2026


async def test_so_thu_tu_lon_nhat_va_tao_lan_xet(c):
    async with AsyncSession(bind=c) as db:
        await _x(c, "INSERT INTO admission_quota_table (academic_year) VALUES (:y)", y=NAM)
        assert await repo.max_seq_no(db, NAM) == 0
        d = c.info["d"]
        s = await repo.insert_session(
            db, academic_year=NAM, admission_round_id=d["vong"], seq_no=1, created_by_user_id=d["nguoi"]
        )
        assert (s.status, s.version, s.seq_no) == ("draft", 1, 1)
        assert await repo.max_seq_no(db, NAM) == 1
        assert await repo.read_session_year(db, s.id) == NAM
        assert (await repo.lock_session(db, s.id)).id == s.id
        assert await repo.read_session_year(db, s.id + 1000) is None


async def test_xoa_san_tra_danh_sach_da_giai_phong_tang_dan(c):
    sid = await _lan_xet(c)
    x, y = c.info["X"]["ai"], c.info["Y"]["ai"]
    async with AsyncSession(bind=c) as db:
        await repo.insert_floors(
            db, session_id=sid, academic_year=NAM, floors=[(y, Decimal("14.50")), (x, Decimal("15.00"))],
            updated_by_user_id=c.info["d"]["nguoi"],
        )
        assert [r.offering_academic_info_id for r in await repo.list_floors(db, sid)] == sorted([x, y])
        assert await repo.floor_counts(db, [sid]) == {sid: 2}
        da_xoa = await repo.delete_floors(db, sid)
        assert da_xoa == sorted([(x, Decimal("15.00")), (y, Decimal("14.50"))])
        assert await repo.list_floors(db, sid) == []


async def test_lan_xet_dang_giu_hoc_vu_sap_theo_so_thu_tu(c):
    s2 = await _lan_xet(c, so=2)
    s1 = await _lan_xet(c, so=1)
    x = c.info["X"]["ai"]
    async with AsyncSession(bind=c) as db:
        for sid in (s2, s1):
            await repo.insert_floors(
                db, session_id=sid, academic_year=NAM, floors=[(x, Decimal("15.00"))],
                updated_by_user_id=c.info["d"]["nguoi"],
            )
        rows = await repo.sessions_with_floor_for_academic_info(db, x)
    assert [(r.session_id, r.seq_no, r.status) for r in rows] == [(s1, 1, "draft"), (s2, 2, "draft")]


def _dong(c, profile_id, tab, **them):
    """Một dòng ĐỦ mọi cột của ``repo.ROW_INSERT_COLUMNS`` (đúng hình ``ReviewRow.column_values`` của luật L2): cột không áp dụng
    là ``None`` — ``insert_rows`` đòi đủ khoá."""
    x = c.info["X"]
    co_nv = tab in ("auto", "needs_decision")
    d = {k: None for k in repo.ROW_INSERT_COLUMNS}
    d.update(
        profile_id=profile_id, profile_status="submitted", tab=tab, reason_codes=[], flags=[], decision_hints=[],
        per_choice=[{"choice_id": profile_id}] if tab != "ineligible" else [], prior_year_findings=[],
        row_hash="%064x" % profile_id,
    )
    if co_nv:
        d.update(
            considered_choice_id=profile_id, considered_display_order=1, considered_offering_academic_info_id=x["ai"],
            considered_offering_id=x["off"], considered_admission_path_id=x["path"], considered_major_code="A",
            review_total=Decimal("15.00"),
        )
    d.update(them)
    return d


async def test_dong_ket_qua_sap_dung_thu_tu_e9_va_loc(c):
    """Thứ tự E9: tab (auto, needs_decision, not_passed, ineligible) → mã ngành → học vụ → ``review_total`` GIẢM → ``profile_id``
    TĂNG. Lọc ``reason_code`` / ``flag`` khớp NGUYÊN mã trong mảng; ``tab_counts`` của cả lượt."""
    rid = await _luot(c, await _lan_xet(c))
    dong = [
        _dong(c, 5, "ineligible", reason_codes=["status_not_in_pool"], profile_status="revision_requested"),
        _dong(c, 3, "auto", considered_major_code="B", review_total=Decimal("18.00")),
        _dong(c, 4, "auto", review_total=Decimal("17.00")),
        _dong(c, 6, "auto", review_total=Decimal("19.00"), flags=["residence_proof_missing"]),
        _dong(c, 2, "needs_decision", review_total=Decimal("19.00"), reason_codes=["over_major_quota"]),
        _dong(c, 1, "not_passed", reason_codes=["all_choices_failed", "quota_closed"], flags=["quota_closed"]),
    ]
    async with AsyncSession(bind=c) as db:
        await repo.insert_rows(db, rid, dong)
        items, total = await repo.list_rows(db, rid)
        assert total == 6
        assert [r.profile_id for r in items] == [6, 4, 3, 2, 1, 5]
        trang2, _ = await repo.list_rows(db, rid, offset=2, limit=2)
        assert [r.profile_id for r in trang2] == [3, 2]
        assert [r.profile_id for r in (await repo.list_rows(db, rid, reason_code="quota_closed"))[0]] == [1]
        assert [r.profile_id for r in (await repo.list_rows(db, rid, reason_code="quota"))[0]] == []
        assert [r.profile_id for r in (await repo.list_rows(db, rid, flag="quota_closed"))[0]] == [1]
        assert [r.profile_id for r in (await repo.list_rows(db, rid, tab="auto", flag="residence_proof_missing"))[0]] == [6]
        hv = c.info["X"]["ai"]
        assert [r.profile_id for r in (await repo.list_rows(db, rid, offering_academic_info_id=hv))[0]] == [6, 4, 3, 2]
        assert await repo.tab_counts(db, rid) == {"auto": 3, "needs_decision": 1, "not_passed": 1, "ineligible": 1}


async def test_luot_moi_nhat_va_luot_xong_moi_nhat(c):
    sid = await _lan_xet(c)
    r1 = await _luot(c, sid)
    await _x(c, XONG, r=r1)
    r2 = await _luot(c, sid)
    async with AsyncSession(bind=c) as db:
        assert (await repo.latest_runs(db, [sid]))[sid].id == r2
        assert await repo.latest_done_run_ids(db, [sid]) == {sid: r1}
        items, total = await repo.list_runs(db, sid)
        assert ([r.id for r in items], total) == ([r2, r1], 2)
        assert await repo.get_run(db, sid, r1) is not None
        assert await repo.get_run(db, sid + 1000, r1) is None  # lượt không thuộc lần xét ⇒ như không có


def _lo_xen_ke(c, n, goc=1000):
    """``n`` dòng XEN KẼ: hồ sơ được xếp (``auto`` — đủ ``considered_*`` + điểm) và hồ sơ thiếu điều kiện (``ineligible`` — mọi
    cột NV / điểm ``None``) — đúng ca làm đường bulk ORM tách thành nhiều câu (Codex B1)."""
    ra = []
    for i in range(n):
        if i % 2 == 0:
            ra.append(_dong(c, goc + i, "auto", review_total=Decimal("16.00"), floor_score=Decimal("15.00")))
        else:
            ra.append(_dong(c, goc + i, "ineligible", reason_codes=["thieu_ma_ho_so"], profile_status="submitted"))
    return ra


async def _dem_cau_khi_ghi(c, rows):
    """Số câu SQL THẬT gửi xuống driver (listener ``before_cursor_execute`` trên kết nối) trong MỘT lần ``insert_rows`` qua
    ``AsyncSession`` (đường của lượt chạy). Trả danh sách (đầu câu, executemany)."""
    from sqlalchemy import event

    cau = []

    def nghe(conn, cursor, statement, parameters, context, executemany):
        cau.append((" ".join(statement.split()[:3]), executemany))

    ket_noi = c.sync_engine  # listener cấp engine: áp cho MỌI kết nối của engine (ca này chỉ dùng kết nối của ``c``)
    event.listen(ket_noi, "before_cursor_execute", nghe)
    try:
        rid = await _luot(c, await _lan_xet(c, so=len(rows)))
        cau.clear()  # chỉ đếm phần ghi dòng
        async with AsyncSession(bind=c) as db:
            await repo.insert_rows(db, rid, rows)
    finally:
        event.remove(ket_noi, "before_cursor_execute", nghe)
    so_dong = (await _x(c, "SELECT count(*) FROM admission_review_row WHERE run_id = :r", r=rid)).scalar_one()
    return cau, so_dong


@pytest.mark.parametrize("n", [10, 200])
async def test_bt35_ghi_lo_xen_ke_mot_cau_sql_khong_tang_theo_so_ho_so(c, n):
    """BT35 / K1 — phần đo được ở ĐỢT 1 (tầng repository): ghi ``n`` dòng xen kẽ được xếp / thiếu điều kiện = ĐÚNG MỘT câu
    ``INSERT`` ở cả 10 và 200 dòng (đo bằng listener, không suy từ một lần gọi hàm). Phép đo nghiệm thu BT35 TOÀN lượt chạy (đọc
    ảnh chụp + tính lại KV F231 + ghi run / dòng — đặc tả bản 4 :617, owner K1) cần ``run_evaluate`` của L3b ⇒ ĐỢT 2."""
    cau, so_dong = await _dem_cau_khi_ghi(c, _lo_xen_ke(c, n))
    assert so_dong == n
    # Đợt 2 (Codex 22-11 mục D P1): một lần gọi driver bằng ``executemany`` vẫn có thể là N lần thực thi phía máy chủ ⇒ đòi MỘT câu
    # nhiều dòng THẬT: đúng một câu, ``executemany`` = False.
    assert cau == [("INSERT INTO admission_review_row", False)], cau


async def test_dong_thieu_hoac_thua_cot_bi_tu_choi_truoc_khi_ghi(c):
    """Mọi dòng phải đủ ĐÚNG tập cột (một hình câu duy nhất) — thiếu một khoá ⇒ ``RowColumnsMismatch``, không câu nào gửi đi.
    Dòng THIẾU đứng ĐẦU lô: không có phép kiểm thì câu Core dựng theo khoá của dòng đầu và lô ghi được ÂM THẦM (cột thiếu = NULL)."""
    rid = await _luot(c, await _lan_xet(c))
    thieu = _dong(c, 1, "ineligible", reason_codes=["thieu_ma_ho_so"])
    del thieu["document_gaps"]
    async with AsyncSession(bind=c) as db:
        with pytest.raises(repo.RowColumnsMismatch):
            await repo.insert_rows(db, rid, [thieu, _dong(c, 2, "ineligible", reason_codes=["thieu_ma_ho_so"])])
    assert (await _x(c, "SELECT count(*) FROM admission_review_row WHERE run_id = :r", r=rid)).scalar_one() == 0


def test_cot_chen_dong_bang_cot_cua_luat_l2():
    """``ROW_INSERT_COLUMNS`` (repository L1) == khoá của ``ReviewRow.column_values`` (luật L2) — hai đầu của MỘT lô ghi."""
    from app.services import admission_review_rules as R

    mau = R.ReviewRow(
        profile_id=1, profile_status="submitted", tab=R.TAB_INELIGIBLE, reason_codes=("x",), flags=(), decision_hints=(),
        document_gaps=None, considered=None, scores=None, floor_score=None, rank_in_major=None, within_seats=None,
        ethnic_priority_state=None, per_choice=(), prior_year_findings=(), row_hash="0" * 64,
    )
    assert set(mau.column_values()) == set(repo.ROW_INSERT_COLUMNS)


async def test_document_gaps_none_qua_orm_luu_sql_null(c):
    """``document_gaps = None`` ghi qua ĐÚNG đường chèn lô của repository ⇒ SQL NULL (``IS NULL``), không phải JSON ``null``."""
    rid = await _luot(c, await _lan_xet(c))
    async with AsyncSession(bind=c) as db:
        await repo.insert_rows(db, rid, [_dong(c, 7, "ineligible", reason_codes=["thieu_ma_ho_so"], document_gaps=None)])
    assert (
        await _x(c, "SELECT document_gaps IS NULL FROM admission_review_row WHERE run_id = :r AND profile_id = 7", r=rid)
    ).scalar_one() is True


async def test_luot_queued_ghi_tuong_minh_summary_quota_view_none_khong_vi_pham_check(c):
    """Tạo lượt ``queued`` qua ORM, truyền TƯỜNG MINH ``summary=None, quota_view=None`` ⇒ SQL NULL ⇒ CHECK theo trạng thái cho qua."""
    from app import models

    sid = await _lan_xet(c)
    async with AsyncSession(bind=c) as db:
        r = models.AdmissionReviewRun(
            session_id=sid, kind="evaluate", status="queued", rule_version="gd2b-1",
            requested_by_user_id=c.info["d"]["nguoi"], inputs={"academic_year": NAM}, summary=None, quota_view=None,
        )
        db.add(r)
        await db.flush()
        rid = r.id
    assert tuple(
        (
            await _x(c, "SELECT summary IS NULL, quota_view IS NULL FROM admission_review_run WHERE id = :r", r=rid)
        ).one()
    ) == (True, True)


async def test_cap_nhat_lan_xet_chi_dung_cot_dua_vao(c):
    sid = await _lan_xet(c)
    async with AsyncSession(bind=c) as db:
        await repo.update_session(db, sid, {"version": 2})
        s = await repo.get_session(db, sid)
        assert (s.version, s.status) == (2, "draft")
        items, total = await repo.list_sessions(db, academic_year=NAM, status="draft")
        assert ([i.id for i in items], total) == ([sid], 1)
