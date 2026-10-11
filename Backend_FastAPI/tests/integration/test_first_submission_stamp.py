"""Đóng dấu LẦN NỘP ĐẦU trong ``admission_state_service.transition()`` (V3 C4) — nộp lại, về nháp, thiếu ngày nộp.

Tầng chủ sở hữu: ``transition()`` — nơi duy nhất ghi ``profile.status``. Mỗi ca canh MỘT bất biến; đột biến tương
ứng ghi trong docstring. Ca chuyển trạng thái chạy thật trên CSDL test (Tier 4s), đồng hồ của module được thay
bằng đồng hồ giả để đặt thời điểm quanh nửa đêm 03-11 giờ VN.
"""

import importlib.util
import itertools
import pathlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text

from app import models
from app.constants import admission_circular as ac
from app.database import AsyncSessionLocal
from app.models.priority_audit import PriorityAuditLog
from app.services import admission_state_service

pytestmark = pytest.mark.asyncio

_DEM = itertools.count(1)


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class _DongHo:
    """Thay ``datetime`` trong ``admission_state_service``: mỗi lần ``now()`` trả mốc kế tiếp, hết mốc thì giữ mốc cuối."""

    def __init__(self, *moc):
        self._moc = list(moc)

    def now(self, tz=None):
        return self._moc.pop(0) if len(self._moc) > 1 else self._moc[0]


async def _ho_so(status="draft", lich_su=(), **cot):
    so = next(_DEM)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="V3 dong dau %d" % so,
                phone="08%08d" % so,
                email="v3dd-%d@example.com" % so,
                source="website",
                unit_id=1,
            )
            s.add(lead)
            await s.flush()
            p = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id="080%09d" % so,
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
                        metadata_={"source": "test_v3_dong_dau"},
                    )
                )
            return p.id


async def _chuyen(monkeypatch, pid, toi, *moc):
    """``transition()`` thật, đồng hồ giả trả lần lượt ``moc``."""
    monkeypatch.setattr(admission_state_service, "datetime", _DongHo(*moc))
    async with AsyncSessionLocal() as s:
        async with s.begin():
            p = (
                await s.execute(select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid))
            ).scalar_one()
            await admission_state_service.transition(
                s, p, toi, actor=None, source="system", skip_audit=True, skip_dispatch=True
            )
    monkeypatch.undo()


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


async def _so_hang_mac_dinh(pid):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(PriorityAuditLog)
                .where(PriorityAuditLog.profile_id == pid, PriorityAuditLog.action_type == "circular_defaulted")
            )
        ).scalar_one()


# Mốc quanh nửa đêm 03-11 giờ VN (= 17:00Z ngày 02-11).
_TRUOC_MOC = _utc(2026, 11, 2, 16, 59, 59, 999999)
_SAU_MOC = _utc(2026, 11, 2, 17, 0, 0, 1)
_NGAY_20_10 = _utc(2026, 10, 20, 3, 0)
_NGAY_05_11 = _utc(2026, 11, 5, 3, 0)


async def test_c0_nop_lan_dau_sau_moc_mac_dinh_tt76(seed_lead_dependencies, monkeypatch):
    """Nộp lần đầu 00:00:00.000001 ngày 03-11 giờ VN ⇒ TT76 mặc định + đúng một hàng ``circular_defaulted``.

    Đột biến: bỏ gán thông tư mặc định trong ``_dong_dau_lan_nop_dau``.
    """
    pid = await _ho_so()
    await _chuyen(monkeypatch, pid, "submitted", _SAU_MOC)
    assert await _doc(pid) == {
        "at": _SAU_MOC,
        "src": ac.FIRST_SUBMITTED_SOURCE_TRANSITION,
        "tt": ac.TT76_2026,
        "tt_src": ac.CIRCULAR_SOURCE_DEFAULT,
    }
    assert await _so_hang_mac_dinh(pid) == 1


async def test_b3_dong_dau_dung_now_cua_hang_lich_su(seed_lead_dependencies, monkeypatch):
    """Ngày nộp đầu = ``occurred_at`` của hàng lịch sử; đồng hồ đọc lần hai (sau nửa đêm) KHÔNG được dùng.

    Đột biến: ``_dong_dau_lan_nop_dau`` tự gọi ``datetime.now()`` thay vì nhận ``now``.
    """
    pid = await _ho_so()
    await _chuyen(monkeypatch, pid, "submitted", _TRUOC_MOC, _SAU_MOC)
    async with AsyncSessionLocal() as s:
        luc_lich_su = (
            await s.execute(
                select(models.AdmissionProfileStatusHistory.occurred_at).where(
                    models.AdmissionProfileStatusHistory.profile_id == pid,
                    models.AdmissionProfileStatusHistory.to_status == "submitted",
                )
            )
        ).scalar_one()
    d = await _doc(pid)
    assert (d["at"], d["tt"]) == (luc_lich_su, ac.TT05_2021)


async def test_c1_nop_lai_sau_yeu_cau_bo_sung_khong_doi_gi(seed_lead_dependencies, monkeypatch):
    """Nộp 20-10 → yêu cầu bổ sung → nộp lại 05-11: ngày nộp đầu và thông tư GIỮ NGUYÊN.

    Đột biến: đóng dấu ở mọi cạnh vào ``submitted``/``resubmitted`` mà không xét cột đã có.
    """
    pid = await _ho_so()
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "revision_requested", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "resubmitted", _NGAY_05_11)
    d = await _doc(pid)
    assert (d["at"], d["tt"]) == (_NGAY_20_10, ac.TT05_2021)


async def test_c2_ve_nhap_roi_nop_lai_sau_moc_giu_tt05(seed_lead_dependencies, monkeypatch):
    """Nộp 20-10 → admin đưa về nháp → nộp lại 05-11 ⇒ vẫn TT05, ngày 20-10 (Q2 "lần nộp đầu").

    Đột biến: điều kiện đóng dấu chỉ là ``old_status == 'draft'`` (bỏ vế nguồn NULL).
    """
    pid = await _ho_so()
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "draft", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_05_11)
    d = await _doc(pid)
    assert (d["at"], d["tt"]) == (_NGAY_20_10, ac.TT05_2021)


async def test_c3_dat_tay_truoc_khi_nop_duoc_giu(seed_lead_dependencies, monkeypatch):
    """Manager đặt TT05 trên hồ sơ chưa nộp, nộp 05-11 ⇒ giữ TT05 ``manual``, ngày 05-11, 0 hàng mặc định.

    Đột biến: đóng dấu ghi đè thông tư cả khi nguồn là ``manual``.
    """
    pid = await _ho_so(
        applicable_circular=ac.TT05_2021,
        applicable_circular_source=ac.CIRCULAR_SOURCE_MANUAL,
        applicable_circular_set_at=_NGAY_20_10,
    )
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_05_11)
    d = await _doc(pid)
    assert (d["at"], d["tt"], d["tt_src"], await _so_hang_mac_dinh(pid)) == (
        _NGAY_05_11,
        ac.TT05_2021,
        ac.CIRCULAR_SOURCE_MANUAL,
        0,
    )


async def test_c4_dong_bang_snapshot_khong_dong_dau(seed_lead_dependencies):
    """Lần nộp HỎNG vẫn đóng băng snapshot (``submitted_T1``) mà hồ sơ ở nháp ⇒ KHÔNG được đóng dấu ngày nộp.

    Đột biến: đóng dấu trong ``freeze_priority_snapshot``.
    """
    from app.services.priority_service import freeze_priority_snapshot

    pid = await _ho_so()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            p = (
                await s.execute(select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid))
            ).scalar_one()
            await freeze_priority_snapshot(p, s, "submitted_T1")
            sau_dong_bang = (p.first_submitted_at, p.first_submitted_source, p.applicable_circular)
            await s.rollback()
    assert sau_dong_bang == (None, None, None)


async def test_c5_circular_defaulted_dung_mot_lan(seed_lead_dependencies, monkeypatch):
    """Nộp → về nháp → nộp lại ⇒ đúng MỘT hàng ``circular_defaulted``.

    Đột biến: ghi hàng nhật ký mặc định ở mọi lần nộp (kể cả khi thông tư đã có).
    """
    pid = await _ho_so()
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "draft", _NGAY_20_10)
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_05_11)
    assert await _so_hang_mac_dinh(pid) == 1


async def test_d2_thieu_chung_cu_nop_lai_khong_thanh_lan_dau(seed_lead_dependencies, monkeypatch):
    """Hồ sơ ``missing_evidence`` về nháp rồi nộp 05-11 ⇒ vẫn thiếu chứng cứ, ngày TRỐNG, TT05.

    Đột biến: điều kiện đóng dấu là ``first_submitted_at IS NULL`` thay vì nguồn NULL.
    """
    pid = await _ho_so(
        first_submitted_source=ac.FIRST_SUBMITTED_SOURCE_MISSING,
        applicable_circular=ac.TT05_2021,
        applicable_circular_source=ac.CIRCULAR_SOURCE_BACKFILL_MISSING,
    )
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_05_11)
    assert await _doc(pid) == {
        "at": None,
        "src": ac.FIRST_SUBMITTED_SOURCE_MISSING,
        "tt": ac.TT05_2021,
        "tt_src": ac.CIRCULAR_SOURCE_BACKFILL_MISSING,
    }


_DUONG_M1 = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "v3circ20261011_first_submission_applicable_circular.py"
)


def _nap_m1():
    spec = importlib.util.spec_from_file_location("_v3circ20261011_cho_c4", _DUONG_M1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_a2_backfill_roi_nop_lai_sau_moc_van_tt05(seed_lead_dependencies, monkeypatch):
    """Ca F20 trọn vẹn: nộp 01-10, về nháp 05-10, migration chạy, nộp lại 05-11 ⇒ TT05, ngày 01-10.

    Đột biến: điều kiện đóng dấu chỉ là ``old_status == 'draft'`` (hồ sơ đã backfill bị đóng dấu lại).
    """
    m1 = _nap_m1()
    pid = await _ho_so(
        "draft",
        [("draft", "submitted", _utc(2026, 10, 1, 3, 0)), ("submitted", "draft", _utc(2026, 10, 5, 3, 0))],
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for cau in m1.BACKFILL_SQL:
                await s.execute(text(cau))
            await s.execute(text(m1.GUARD_SQL))
            await s.execute(text("SELECT pg_temp.v3_m1_guard(:r)"), {"r": _utc(2026, 10, 20, 3, 0)})
    await _chuyen(monkeypatch, pid, "submitted", _NGAY_05_11)
    d = await _doc(pid)
    assert (d["at"], d["src"], d["tt"]) == (
        _utc(2026, 10, 1, 3, 0),
        ac.FIRST_SUBMITTED_SOURCE_HISTORY,
        ac.TT05_2021,
    )
