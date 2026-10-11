"""Khoá ``app/constants/admission_circular.py`` — mốc giờ Việt Nam và tập trạng thái sau nộp.

Mỗi ca canh MỘT bất biến. Đột biến đã thử (đều làm đúng ca tương ứng đỏ) ghi trong docstring từng ca.
Không đụng CSDL ⇒ Tier 5.
"""

from collections import deque
from datetime import date, datetime, timedelta, timezone

import pytest

from app.constants import admission_circular as ac
from app.services.admission_state_machine import ALLOWED_TRANSITIONS, AdmissionStatus

pytestmark = pytest.mark.unit

_UTC = timezone.utc


def _loi_cua(ham, *a):
    """Gọi ``ham(*a)``; trả lỗi nếu có, ``None`` nếu không. Ca tự ``assert`` trên kết quả — để đột biến gỡ phép
    kiểm làm ca đỏ bằng ASSERTION trong thân ca, không phải ``DID NOT RAISE``."""
    try:
        ham(*a)
    except Exception as loi:  # noqa: BLE001 — ca kiểm đúng loại lỗi ngay sau đó
        return loi
    return None


# --- B1: ngày lịch giờ Việt Nam, không phải ngày UTC ---------------------------------------------


def test_b1_ngay_lich_vn_khong_phai_ngay_utc():
    """23:59:59.999999 ngày 02-11 giờ VN là TT05; 00:00:00 ngày 03-11 giờ VN là TT76.

    Đột biến: ``vn_calendar_date`` trả ``moment.date()`` (ngày UTC) ⇒ 17:00Z ngày 02-11 bị tính là 02-11.
    """
    truoc = datetime(2026, 11, 2, 16, 59, 59, 999999, tzinfo=_UTC)
    dung_moc = datetime(2026, 11, 2, 17, 0, 0, tzinfo=_UTC)
    assert ac.vn_calendar_date(truoc) == date(2026, 11, 2)
    assert ac.vn_calendar_date(dung_moc) == date(2026, 11, 3)
    assert ac.default_circular_for(ac.vn_calendar_date(truoc)) == ac.TT05_2021
    assert ac.default_circular_for(ac.vn_calendar_date(dung_moc)) == ac.TT76_2026


def test_b1_thoi_diem_khong_mui_gio_bi_tu_choi():
    """Thời điểm không múi giờ ⇒ ValueError, không ngầm hiểu theo giờ máy chủ.

    Đột biến: bỏ phép kiểm ``tzinfo`` ⇒ ``astimezone`` hiểu theo giờ máy và trả một ngày.
    """
    assert isinstance(_loi_cua(ac.vn_calendar_date, datetime(2026, 11, 2, 17, 0, 0)), ValueError)


def test_b1_default_circular_tu_choi_datetime():
    """Truyền thẳng một ``datetime`` (lớp con của ``date``) ⇒ TypeError.

    Đột biến: bỏ phép kiểm ``isinstance(day, datetime)`` ⇒ so ``datetime`` với ``date`` ném TypeError
    KHÁC loại thông điệp — ca này khoá thông điệp hướng dẫn qua ``vn_calendar_date``.
    """
    loi = _loi_cua(ac.default_circular_for, datetime(2026, 11, 3, 0, 0, tzinfo=_UTC))
    assert isinstance(loi, TypeError) and "vn_calendar_date" in str(loi)


# --- B2: mốc gồm chính ngày 03-11 -------------------------------------------------------------------


def test_b2_moc_gom_chinh_ngay_03_11():
    """03-11 ⇒ TT76; 02-11 ⇒ TT05.

    Đột biến: ``>`` thay ``>=`` ⇒ 03-11 thành TT05.
    """
    assert ac.CIRCULAR_CUTOVER_DATE == date(2026, 11, 3)
    assert ac.default_circular_for(date(2026, 11, 3)) == ac.TT76_2026
    assert ac.default_circular_for(date(2026, 11, 2)) == ac.TT05_2021


def test_b2_moc_doc_lap_gio_he_thong(monkeypatch):
    """Ngày VN không phụ thuộc biến ``TZ`` của tiến trình.

    Đột biến: dùng ``astimezone()`` không đối số (giờ máy) thay ``VN_TZ``.
    """
    import time

    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        assert ac.vn_calendar_date(datetime(2026, 11, 2, 17, 0, tzinfo=_UTC)) == date(2026, 11, 3)
    finally:
        monkeypatch.undo()
        if hasattr(time, "tzset"):
            time.tzset()


def test_b2_mui_gio_khac_cung_quy_ve_gio_vn():
    """Một thời điểm mang múi giờ +09:00 vẫn quy về ngày lịch VN.

    Đột biến: ``moment.date()`` (ngày theo múi giờ của chính giá trị) ⇒ 01:30+09:00 ngày 03-11 bị tính
    là 03-11, trong khi giờ VN là 23:30 ngày 02-11.
    """
    plus9 = timezone(timedelta(hours=9))
    assert ac.vn_calendar_date(datetime(2026, 11, 3, 1, 30, tzinfo=plus9)) == date(2026, 11, 2)


# --- I3: POST_SUBMIT là một nguồn, tính được từ máy trạng thái ---------------------------------------


def _chua_tung_nop_toi_duoc():
    """Trạng thái tới được từ DRAFT mà KHÔNG đi qua SUBMITTED (BFS bỏ nút SUBMITTED)."""
    seen = {AdmissionStatus.DRAFT}
    q = deque([AdmissionStatus.DRAFT])
    while q:
        cur = q.popleft()
        for nxt in ALLOWED_TRANSITIONS.get(cur, set()):
            if nxt == AdmissionStatus.SUBMITTED or nxt in seen:
                continue
            seen.add(nxt)
            q.append(nxt)
    return {s.value for s in seen}


def test_i3_post_submit_tinh_tu_allowed_transitions():
    """Hằng = mọi trạng thái trừ những trạng thái tới được từ DRAFT mà không qua SUBMITTED.

    Đột biến: thêm cạnh ``DRAFT → REVIEWING`` vào máy trạng thái ⇒ REVIEWING rời tập tính được.
    """
    tat_ca = {s.value for s in AdmissionStatus}
    tinh = tat_ca - _chua_tung_nop_toi_duoc()
    assert ac.POST_SUBMIT_STATUSES == frozenset(tinh)


def test_i3_ba_trang_thai_chua_tung_nop():
    """Đúng ba trạng thái hồ sơ chưa từng nộp có thể đứng.

    Đột biến: bỏ ``withdrawal_pending`` khỏi tập ⇒ hằng có 13 phần tử.
    """
    tat_ca = {s.value for s in AdmissionStatus}
    assert tat_ca - ac.POST_SUBMIT_STATUSES == {"draft", "withdrawn", "withdrawal_pending"}


# --- Giá trị owner chốt -------------------------------------------------------------------------------


def test_q11_ca_hai_thong_tu_tam():
    """Q11 (owner, 11-10-2026) "Cả hai tạm" ⇒ mọi hồ sơ hiện cảnh báo danh mục KV.

    Đột biến: đổi một thông tư sang ``confirmed``.
    """
    assert dict(ac.KV_CATALOG_STATUS) == {
        ac.TT05_2021: ac.KV_CATALOG_PROVISIONAL,
        ac.TT76_2026: ac.KV_CATALOG_PROVISIONAL,
    }


def test_kv_catalog_status_khong_sua_duoc_luc_chay():
    """Bảng trạng thái chỉ đọc — đổi giá trị phải qua sửa mã, không qua gán lúc chạy.

    Đột biến: khai bằng ``dict`` thường.
    """

    def _gan():
        ac.KV_CATALOG_STATUS[ac.TT76_2026] = ac.KV_CATALOG_CONFIRMED  # type: ignore[index]

    assert isinstance(_loi_cua(_gan), TypeError)


def test_nguon_co_ngay_la_tap_con_dung():
    """``missing_evidence`` là nguồn DUY NHẤT không mang ngày.

    Đột biến: thêm ``missing_evidence`` vào tập có ngày (mở đường lấp ngày giả).
    """
    assert set(ac.FIRST_SUBMITTED_SOURCES) - set(ac.FIRST_SUBMITTED_SOURCES_WITH_DATE) == {
        ac.FIRST_SUBMITTED_SOURCE_MISSING
    }


# --- B4 + I3: bản chép đông cứng trong migration = hằng ứng dụng = ràng buộc model --------------------

import importlib.util  # noqa: E402
import pathlib  # noqa: E402
import re  # noqa: E402

from app.models.admission import AdmissionProfile  # noqa: E402

_DUONG_M1 = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "v3circ20261011_first_submission_applicable_circular.py"
)


@pytest.fixture(scope="module")
def m1():
    spec = importlib.util.spec_from_file_location("_v3circ20261011_cau_truc", _DUONG_M1)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gon(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def test_b4_moc_trong_migration_bang_hang_ung_dung(m1):
    """Mốc + múi giờ + mã thông tư chép trong migration = hằng ứng dụng.

    Đột biến: sửa ``CUTOVER_DATE_FROZEN`` thành ``2026-11-04``.
    """
    assert m1.CUTOVER_DATE_FROZEN == ac.CIRCULAR_CUTOVER_DATE.isoformat()
    assert m1.VN_TZ_FROZEN == ac.VN_TZ.key
    assert m1.CIRCULARS_FROZEN == ac.CIRCULARS


def test_i3_tap_trang_thai_trong_migration_bang_hang(m1):
    """POST_SUBMIT / PRE_SUBMIT chép trong migration = hằng ứng dụng.

    Đột biến: bớt ``waitlisted`` khỏi ``POST_SUBMIT_FROZEN``.
    """
    assert frozenset(m1.POST_SUBMIT_FROZEN) == ac.POST_SUBMIT_STATUSES
    assert set(m1.PRE_SUBMIT_FROZEN) == {s.value for s in AdmissionStatus} - ac.POST_SUBMIT_STATUSES


def test_i3_tap_nguon_trong_migration_bang_hang(m1):
    """Tập nguồn chép trong migration = hằng ứng dụng.

    Đột biến: thêm ``updated_at`` vào ``FIRST_SUBMITTED_SOURCES_WITH_DATE_FROZEN``.
    """
    assert m1.FIRST_SUBMITTED_SOURCES_FROZEN == ac.FIRST_SUBMITTED_SOURCES
    assert m1.FIRST_SUBMITTED_SOURCES_WITH_DATE_FROZEN == ac.FIRST_SUBMITTED_SOURCES_WITH_DATE
    assert m1.CIRCULAR_SOURCES_FROZEN == ac.CIRCULAR_SOURCES


def _check_model():
    return {
        c.name: _gon(c.sqltext)
        for c in AdmissionProfile.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint" and c.name
    }


def test_i3_check_model_bang_check_migration(m1):
    """CK1–CK4 khai ở model = chuỗi migration (CSDL test dựng từ model, production từ migration).

    Đột biến: đổi một giá trị trong CHECK của model (vd bỏ ``'manual'``).
    """
    cua_model = _check_model()
    can = dict(m1.CHECKS_TRUOC_BACKFILL)
    can[m1.CK4_NAME] = m1.CK4_SQL
    for ten, bieu_thuc in can.items():
        assert cua_model.get(ten) == _gon(bieu_thuc), ten


def test_ck5_chi_o_migration(m1):
    """CK5 KHÔNG khai ở model — hàng trăm fixture tạo hồ sơ thẳng ở ``submitted``. Tầng chủ sở hữu bất biến là
    ``transition()``; CK5 là lưới production. Ca này khoá quyết định ấy để ai đổi thì đổi có chủ đích.
    """
    assert m1.CK5_NAME not in _check_model()
    assert _gon(m1.CK5_SQL) == _gon(
        "status IN (%s) OR first_submitted_source IS NOT NULL" % ", ".join("'%s'" % s for s in m1.PRE_SUBMIT_FROZEN)
    )


class _GhiLoiGoiOp:
    def __init__(self):
        self.goi = []

    def __getattr__(self, ten):
        def _ghi(*a, **k):
            self.goi.append((ten, a, k))

        return _ghi


def test_upgrade_la_mot_cau_do_duy_nhat(m1, monkeypatch):
    """``upgrade()`` gửi ĐÚNG MỘT lệnh: ``alembic/env.py`` chạy AUTOCOMMIT, tách lệnh là khối kiểm RAISE sau khi
    backfill đã commit.

    Đột biến: ``upgrade()`` chạy từng câu của ``BACKFILL_SQL`` bằng ``op.execute`` riêng.
    """
    ghi = _GhiLoiGoiOp()
    monkeypatch.setattr(m1, "op", ghi)
    m1.upgrade()
    assert ghi.goi == [("execute", (m1.UPGRADE_DO_SQL,), {})]
    assert m1.UPGRADE_DO_SQL.startswith("DO $m1$")
    for phan in (*m1.DDL_TRUOC_SQL, *m1.BACKFILL_SQL, m1.GUARD_SQL, *m1.DDL_SAU_SQL):
        assert phan.strip() in m1.UPGRADE_DO_SQL


def test_upgrade_goi_khoi_kiem_truoc_ck4_ck5(m1):
    """Thứ tự trong câu DO: backfill → khối kiểm → CK4/CK5.

    Đột biến: đặt ``DDL_SAU_SQL`` trước khối kiểm.
    """
    s = m1.UPGRADE_DO_SQL
    vi_tri_kiem = s.index(m1.guard_perform_sql())
    assert s.index(m1.BACKFILL_SQL[-1].strip()) < vi_tri_kiem
    for cau in m1.DDL_SAU_SQL:
        assert s.index(cau) > vi_tri_kiem


def test_downgrade_la_mot_cau_do_duy_nhat(m1, monkeypatch):
    """``downgrade()`` kiểm hàng ``manual`` và bỏ cột trong CÙNG một lệnh.

    Đột biến: tách phép kiểm thành ``op.execute`` riêng rồi ``op.drop_column`` từng cột.
    """
    ghi = _GhiLoiGoiOp()
    monkeypatch.setattr(m1, "op", ghi)
    m1.downgrade()
    assert ghi.goi == [("execute", (m1.DOWNGRADE_DO_SQL,), {})]


def test_sql_migration_khong_co_ky_tu_phan_tram(m1):
    """Không dùng ký tự phần trăm trong SQL: cách driver thoát nó khác nhau.

    Đột biến: quay lại ``RAISE EXCEPTION '…%…', v``.
    """
    for ten in ("UPGRADE_DO_SQL", "DOWNGRADE_DO_SQL"):
        assert "%" not in getattr(m1, ten), ten
