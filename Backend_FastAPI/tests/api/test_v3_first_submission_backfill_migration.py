"""Nhóm A — backfill M1 (``v3circ20261011``): lần nộp đầu + thông tư áp dụng, phân loại theo LỊCH SỬ.

Chạy CHÍNH các hằng SQL của tệp migration (nạp bằng ``spec_from_file_location``), không chép tay — migration
đổi mà test không đổi thì test vẫn phải thấy.

Leg Tier 4i: các câu backfill chạm TOÀN BẢNG ``admission_profile``, và hai ca dựng ràng buộc tạm (A10) /
chạy câu ``DO`` của downgrade (A9) là DDL cấp bảng — cùng lý do cách ly với ``test_adm_024``.

Khối kiểm liệt kê MÃ vi phạm. Mỗi ca nhóm A8 cấp một backfill hỏng có chủ đích và đòi tập mã RAISE đúng
bằng MỘT mã — vừa chứng minh mã ấy bắt được lỗi của nó, vừa chứng minh ca chỉ vi phạm một bất biến.
"""

import importlib.util
import itertools
import pathlib
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import models
from app.constants import admission_circular as ac
from app.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio

_DUONG_M1 = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "v3circ20261011_first_submission_applicable_circular.py"
)


def _nap_m1():
    spec = importlib.util.spec_from_file_location("_v3circ20261011_cho_test", _DUONG_M1)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M1 = _nap_m1()

#: Mốc chạy migration giả định: TRƯỚC 03-11 (giờ VN), như kế hoạch deploy.
RUN_TRUOC_MOC = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
_DEM = itertools.count(1)


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


async def _ho_so(status, lich_su=(), **cot):
    """Tạo lead + hồ sơ ở ``status`` + các hàng lịch sử ``(from, to, occurred_at)``. Trả id hồ sơ."""
    so = next(_DEM)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="V3 M1 %d" % so,
                phone="09%08d" % so,
                email="v3m1-%d@example.com" % so,
                source="website",
                unit_id=1,
            )
            s.add(lead)
            await s.flush()
            p = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id="079%09d" % so,
                version=1,
                applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
                academic_year=2026,
                **cot,
            )
            s.add(p)
            await s.flush()
            for tu, toi, luc in lich_su:
                s.add(
                    models.AdmissionProfileStatusHistory(
                        profile_id=p.id,
                        from_status=tu,
                        to_status=toi,
                        transitioned_by_role="system",
                        actor_actual_role="system",
                        effective_transition_role="system",
                        occurred_at=luc,
                        metadata_={"source": "test_v3_m1"},
                    )
                )
            return p.id


async def _chay(backfill=None, run_at=RUN_TRUOC_MOC, mui_gio_phien="UTC"):
    """Chạy backfill + khối kiểm trong MỘT giao dịch, phiên ở ``mui_gio_phien``."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(text("SET LOCAL TimeZone = '%s'" % mui_gio_phien))
            for cau in M1.BACKFILL_SQL if backfill is None else backfill:
                await s.execute(text(cau))
            await s.execute(text(M1.GUARD_SQL))
            await s.execute(text("SELECT pg_temp.v3_m1_guard(:run_at)"), {"run_at": run_at})


async def _doc(pid):
    async with AsyncSessionLocal() as s:
        p = (
            await s.execute(select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid))
        ).scalar_one()
        return {
            "at": p.first_submitted_at,
            "src": p.first_submitted_source,
            "tt": p.applicable_circular,
            "tt_src": p.applicable_circular_source,
        }


async def _loi_cua(coro):
    """Chờ ``coro``; trả lỗi CSDL nếu có, ``None`` nếu không. Ca tự ``assert`` trên kết quả — để đột biến gỡ guard
    làm ca đỏ bằng ASSERTION trong thân ca, không phải ``DID NOT RAISE``."""
    try:
        await coro
    except DBAPIError as loi:
        return loi
    return None


def _ma_vi_pham(loi) -> set:
    """Tập mã của khối kiểm V3M1 trong thông điệp lỗi; rỗng nếu không có lỗi hoặc lỗi không phải của khối kiểm."""
    m = re.search(r"V3M1 khoi kiem DO: ([a-z0-9= ]+)", str(loi)) if loi is not None else None
    return {tung.split("=")[0] for tung in m.group(1).split()} if m else set()


# --- A1–A6: phân loại đúng --------------------------------------------------------------------------


async def test_a1_da_nop_roi_ve_nhap_la_da_nop(seed_lead_dependencies):
    """Đang ``draft`` lúc backfill nhưng lịch sử có nộp ⇒ ngày = hàng nộp đầu, nguồn ``status_history``.

    Đột biến: phân loại theo trạng thái hiện tại (``status <> 'draft'``) ⇒ hồ sơ này NULL.
    """
    pid = await _ho_so(
        "draft",
        [("draft", "submitted", _utc(2026, 10, 1, 3, 0)), ("submitted", "draft", _utc(2026, 10, 5, 3, 0))],
    )
    await _chay()
    assert await _doc(pid) == {
        "at": _utc(2026, 10, 1, 3, 0),
        "src": ac.FIRST_SUBMITTED_SOURCE_HISTORY,
        "tt": ac.TT05_2021,
        "tt_src": ac.CIRCULAR_SOURCE_BACKFILL,
    }


async def test_a1b_lay_lan_nop_DAU_khong_phai_gan_nhat(seed_lead_dependencies):
    """Nộp hai lần ⇒ ngày là lần ĐẦU.

    Đột biến: ``MAX(occurred_at)`` thay ``MIN`` trong ``PHAN_LOAI_SQL``.
    """
    pid = await _ho_so(
        "submitted",
        [
            ("draft", "submitted", _utc(2026, 10, 1, 3, 0)),
            ("submitted", "draft", _utc(2026, 10, 2, 3, 0)),
            ("draft", "submitted", _utc(2026, 10, 3, 3, 0)),
        ],
    )
    await _chay()
    assert (await _doc(pid))["at"] == _utc(2026, 10, 1, 3, 0)


async def test_a3_co_lich_su_ma_chua_tung_nop_la_null(seed_lead_dependencies):
    """``draft → withdrawal_pending → draft`` ⇒ chưa từng nộp ⇒ cả hai cột NULL.

    Đột biến: "có hàng lịch sử bất kỳ ⇒ đã nộp".
    """
    pid = await _ho_so(
        "draft",
        [
            ("draft", "withdrawal_pending", _utc(2026, 9, 1, 3, 0)),
            ("withdrawal_pending", "draft", _utc(2026, 9, 2, 3, 0)),
        ],
    )
    await _chay()
    assert await _doc(pid) == {"at": None, "src": None, "tt": None, "tt_src": None}


async def test_a4_rut_tu_nhap_la_null(seed_lead_dependencies):
    """Rút thẳng từ nháp (63 ca thật) ⇒ NULL, không gán thông tư.

    Đột biến: "khác draft ⇒ TT05".
    """
    pid = await _ho_so("withdrawn", [("draft", "withdrawn", _utc(2026, 8, 1, 3, 0))])
    await _chay()
    assert await _doc(pid) == {"at": None, "src": None, "tt": None, "tt_src": None}


async def test_a5_thieu_chung_cu_la_nhan_khong_doan_ngay(seed_lead_dependencies):
    """Đã qua nộp mà không có hàng nộp ⇒ ``missing_evidence``, NGÀY TRỐNG, TT05 nguồn backfill_missing_evidence.

    Đột biến: điền ngày bằng ``updated_at`` (hoặc ``now()``) cho ca này.
    """
    pid = await _ho_so("reviewing", [("submitted", "reviewing", _utc(2026, 9, 10, 3, 0))])
    await _chay()
    assert await _doc(pid) == {
        "at": None,
        "src": ac.FIRST_SUBMITTED_SOURCE_MISSING,
        "tt": ac.TT05_2021,
        "tt_src": ac.CIRCULAR_SOURCE_BACKFILL_MISSING,
    }


async def test_a6_ranh_gioi_gio_vn_trong_sql(seed_lead_dependencies):
    """16:59:59Z ngày 02-11 ⇒ TT05; 17:00:00Z ⇒ TT76, khi PHIÊN ở UTC.

    Đột biến: ``first_submitted_at::date`` trong ``circular_formula_sql`` — phiên UTC tính 17:00Z là 02-11.
    """
    truoc = await _ho_so("submitted", [("draft", "submitted", _utc(2026, 11, 2, 16, 59, 59))])
    sau = await _ho_so("submitted", [("draft", "submitted", _utc(2026, 11, 2, 17, 0, 0))])
    await _chay(mui_gio_phien="UTC")
    assert (await _doc(truoc))["tt"] == ac.TT05_2021
    assert (await _doc(sau))["tt"] == ac.TT76_2026


async def test_a11_dau_hieu_sau_nop_som_hon_hang_nop_la_thieu_chung_cu(seed_lead_dependencies):
    """Hàng khởi tạo ``NULL → submitted`` (kiểu phase1_10) SỚM HƠN hàng nộp đầu ⇒ MIN của hàng nộp không phải
    lần nộp đầu ⇒ ``missing_evidence``, ngày trống.

    Đột biến: bỏ điều kiện ``d.dau_hieu >= n.nop`` ⇒ ca này thành ``status_history`` ngày 10-01.
    """
    pid = await _ho_so(
        "submitted",
        [
            (None, "submitted", _utc(2026, 5, 1, 3, 0)),
            ("submitted", "draft", _utc(2026, 6, 1, 3, 0)),
            ("draft", "submitted", _utc(2026, 10, 1, 3, 0)),
        ],
    )
    await _chay()
    d = await _doc(pid)
    assert (d["src"], d["at"]) == (ac.FIRST_SUBMITTED_SOURCE_MISSING, None)


# --- A7: chặn chạy từ mốc khi có ca thiếu chứng cứ ---------------------------------------------------


async def test_a7_truoc_moc_thi_qua(seed_lead_dependencies):
    """Có ``missing_evidence``, chạy lúc 23:59 ngày 02-11 giờ VN ⇒ khối kiểm qua.

    Cặp với ca dưới: đột biến ``>`` thay ``>=`` ở điều (b) làm ca dưới xanh sai.
    """
    await _ho_so("reviewing", [("submitted", "reviewing", _utc(2026, 9, 10, 3, 0))])
    loi = await _loi_cua(_chay(run_at=_utc(2026, 11, 2, 16, 59)))
    assert loi is None, str(loi)


async def test_a7_tu_moc_thi_chan(seed_lead_dependencies):
    """Có ``missing_evidence``, chạy lúc 00:00 ngày 03-11 giờ VN ⇒ RAISE đúng mã ``b``.

    Đột biến: bỏ điều (b) khỏi ``GUARD_SQL``.
    """
    await _ho_so("reviewing", [("submitted", "reviewing", _utc(2026, 9, 10, 3, 0))])
    loi = await _loi_cua(_chay(run_at=_utc(2026, 11, 2, 17, 0)))
    assert _ma_vi_pham(loi) == {"b"}


# --- A8: mỗi điều của khối kiểm bắt đúng một lỗi backfill -------------------------------------------

_S1, _S2 = M1.BACKFILL_SQL
_CONG_THUC_DUNG = M1.circular_formula_sql("c.nop")
_CONG_THUC_UTC = "CASE WHEN c.nop::date >= DATE '2026-11-03' THEN 'TT76_2026' ELSE 'TT05_2021' END"
assert _S1.count(_CONG_THUC_DUNG) == 1
assert _S1.count("SET first_submitted_at = c.nop,") == 1
_GAN_SAI_THONG_TU = (
    "UPDATE admission_profile SET applicable_circular = 'TT05_2021', "
    "applicable_circular_source = 'backfill_missing_evidence', applicable_circular_set_at = now() "
    "WHERE first_submitted_source IS NULL AND status <> 'draft'"
)

assert _S1.count("first_submitted_source = 'status_history',") == 1
_S1_DAN_NHAM_NHAN = _S1.replace("SET first_submitted_at = c.nop,", "SET first_submitted_at = NULL,").replace(
    "first_submitted_source = 'status_history',", "first_submitted_source = 'missing_evidence',"
)

_CA_A8 = {
    # mục 1 dán NHẦM nhãn thiếu chứng cứ (ngày trống) cho hồ sơ có hàng nộp hợp lệ.
    # (Bỏ hẳn mục 1 thì nguồn ở NULL ⇒ a1, c, g CÙNG đỏ — không phải ca một-bất-biến.)
    "a1": (
        ("submitted", [("draft", "submitted", _utc(2026, 10, 1, 3, 0))]),
        (_S1_DAN_NHAM_NHAN, _S2),
    ),
    # ngày lệch khỏi lần nộp đầu (thông tư vẫn TT05 nên chỉ a2 đỏ)
    "a2": (
        ("submitted", [("draft", "submitted", _utc(2026, 10, 1, 3, 0))]),
        (_S1.replace("SET first_submitted_at = c.nop,", "SET first_submitted_at = c.nop + interval '1 day',"), _S2),
    ),
    # mục 2 chỉ xét dấu hiệu trong lịch sử, quên trạng thái hiện tại
    "c": (
        ("submitted", []),
        (_S1, _S2.rstrip() + " AND c.dau_hieu IS NOT NULL"),
    ),
    # công thức thông tư theo ngày của PHIÊN (UTC), không theo ngày VN
    "e": (
        ("submitted", [("draft", "submitted", _utc(2026, 11, 2, 17, 0, 0))]),
        (_S1.replace(_CONG_THUC_DUNG, _CONG_THUC_UTC), _S2),
    ),
    # gán thông tư cho hồ sơ chưa từng nộp
    "f": (
        ("withdrawn", [("draft", "withdrawn", _utc(2026, 8, 1, 3, 0))]),
        (_S1, _S2, _GAN_SAI_THONG_TU),
    ),
    # mục 2 chỉ xét trạng thái hiện tại, quên hồ sơ đang nháp từng bị trả về
    "g": (
        ("draft", [("submitted", "draft", _utc(2026, 9, 1, 3, 0))]),
        (_S1, _S2.rstrip() + " AND p.status <> 'draft'"),
    ),
}


async def _chay_ca_a8(ma):
    (status, lich_su), backfill = _CA_A8[ma]
    await _ho_so(status, lich_su)
    return await _loi_cua(_chay(backfill=backfill))


# Mỗi ca: backfill hỏng có chủ đích ⇒ RAISE với ĐÚNG MỘT mã. Đột biến (mỗi mã một lượt): gỡ điều tương ứng
# khỏi ``GUARD_SQL`` (``v_<mã>`` không bao giờ > 0). Ca tách riêng (không tham số hoá) để khung lỗi là thân ca.


async def test_a8_a1_nhan_sai_cho_ho_so_co_hang_nop(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("a1")) == {"a1"}


async def test_a8_a2_ngay_khac_lan_nop_dau(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("a2")) == {"a2"}


async def test_a8_c_trang_thai_sau_nop_nguon_null(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("c")) == {"c"}


async def test_a8_e_thong_tu_lech_cong_thuc_ngay_vn(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("e")) == {"e"}


async def test_a8_f_gan_thong_tu_cho_ho_so_chua_nop(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("f")) == {"f"}


async def test_a8_g_ho_so_nhap_tung_bi_tra_ve_nguon_null(seed_lead_dependencies):
    assert _ma_vi_pham(await _chay_ca_a8("g")) == {"g"}


async def test_a8_du_ca_cho_moi_ma():
    """Mỗi mã của khối kiểm (trừ ``b`` — có cặp A7 riêng) có đúng một ca A8.

    Đột biến: thêm một điều mới vào ``GUARD_SQL`` mà không thêm ca.
    """
    ma_trong_guard = set(re.findall(r"IF v_([a-z0-9]+) +> 0 THEN", M1.GUARD_SQL))
    assert ma_trong_guard - {"b"} == set(_CA_A8)


async def test_a8_backfill_dung_thi_khoi_kiem_qua(seed_lead_dependencies):
    """Đối chứng: cùng dữ liệu của mọi ca A8, backfill ĐÚNG ⇒ không RAISE.

    Đột biến: một điều của khối kiểm báo nhầm trên dữ liệu hợp lệ (vd đảo dấu so sánh ở a2).
    """
    for (status, lich_su), _ in _CA_A8.values():
        await _ho_so(status, lich_su)
    loi = await _loi_cua(_chay())
    assert loi is None, str(loi)


# --- A9, A10, A13: downgrade, CK5, một câu DO --------------------------------------------------------


async def test_a9_downgrade_khong_nuot_thay_doi_tay(seed_lead_dependencies):
    """Còn hàng ``manual`` ⇒ câu DO của downgrade RAISE trước khi bỏ cột.

    Đột biến: bỏ phép kiểm ⇒ câu DO đi tiếp và đổ ở ``DROP CONSTRAINT`` (lỗi KHÁC, ca này đỏ vì thông điệp).
    """
    await _ho_so(
        "draft",
        applicable_circular=ac.TT05_2021,
        applicable_circular_source=ac.CIRCULAR_SOURCE_MANUAL,
    )

    async def _ha_cap():
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text(M1.DOWNGRADE_DO_SQL))

    loi = await _loi_cua(_ha_cap())
    assert "V3M1 downgrade bi chan" in str(loi)


async def test_a10_ck5_chan_trang_thai_sau_nop_khong_dau(seed_lead_dependencies):
    """CK5 (chỉ ở migration) chặn ``UPDATE status='submitted'`` khi nguồn ngày nộp NULL.

    Dựng CK5 TẠM trong giao dịch của ca (rollback cuối ca). Đột biến: nới ``CK5_SQL`` (vd bỏ vế nguồn).
    """
    pid = await _ho_so("draft")

    async def _nop_khong_dau():
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(
                    text("ALTER TABLE admission_profile ADD CONSTRAINT %s CHECK (%s)" % (M1.CK5_NAME, M1.CK5_SQL))
                )
                await s.execute(
                    text("UPDATE admission_profile SET status = 'submitted' WHERE id = :pid"), {"pid": pid}
                )

    loi = await _loi_cua(_nop_khong_dau())
    assert M1.CK5_NAME in str(loi)


async def test_a13_raise_trong_cau_do_lui_ca_backfill(seed_lead_dependencies):
    """Câu DO của upgrade: khối kiểm RAISE ⇒ backfill ĐÃ CHẠY trong cùng câu cũng bị lùi.

    ``alembic/env.py`` chạy AUTOCOMMIT: nếu khối kiểm ở lệnh riêng, backfill đã commit trước khi nó RAISE.
    Đột biến: bỏ lời gọi khối kiểm khỏi ``build_upgrade_do`` ⇒ không RAISE và hồ sơ bị ghi.
    """
    co_hang_nop = await _ho_so("submitted", [("draft", "submitted", _utc(2026, 10, 1, 3, 0))])
    await _ho_so("reviewing", [("submitted", "reviewing", _utc(2026, 9, 10, 3, 0))])
    cau_do = M1.build_upgrade_do(
        ddl_truoc=(),
        backfill=M1.BACKFILL_SQL,
        ddl_sau=(),
        run_at_sql="make_timestamptz(2026, 11, 3, 0, 0, 0, 'Asia/Ho_Chi_Minh')",
    )

    async def _chay_do():
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text(cau_do))

    loi = await _loi_cua(_chay_do())
    assert _ma_vi_pham(loi) == {"b"}
    assert (await _doc(co_hang_nop))["src"] is None
