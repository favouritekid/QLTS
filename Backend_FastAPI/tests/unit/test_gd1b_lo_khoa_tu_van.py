"""GĐ1b lô — sổ khoá tư vấn, hằng số, schema (không CSDL). Đặc tả bản 3.6 §5.2, §5.3, §6, §9, §13.3; hợp đồng bản 4 §2.1.

``test_tham_so_k1_da_do`` ĐỎ CÓ CHỦ ĐÍCH cho tới khi Claude điền số đo V3 (N của K1 + ``lock_timeout``) — §13.3: "tham số
chưa có số để trống ⇒ CI đỏ, không có mặc định cho chạy".
"""
from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core import advisory_lock_keys as keys
from app.schemas import document_bulk as sch
from app.services import document_bulk_verify_service as svc

GOC = Path(__file__).resolve().parents[2]
TEP_LO = (
    "app/core/advisory_lock_keys.py",
    "app/repositories/document_bulk_repository.py",
    "app/services/document_bulk_verify_service.py",
    "app/services/document_cross_review_service.py",
    "app/routers/document_bulk_verify.py",
    "app/routers/document_cross_review.py",
    "app/schemas/document_bulk.py",
)


# ---------------------------------------------------------------------------------------------------- tham số chưa đo
def test_tham_so_k1_da_do():
    """ĐỎ CÓ CHỦ ĐÍCH tới khi có số đo V3 (§13.3, §16 V3). KHÔNG điền số giả để làm xanh."""
    assert svc.BULK_VERIFY_MAX_DOCUMENTS is not None, "N của K1 chưa đo (V3)"
    assert svc.BULK_VERIFY_LOCK_TIMEOUT_MS is not None, "lock_timeout §5.4 chưa đo (V3)"


def test_hang_so_lo_da_chot():
    assert svc.BULK_VERIFY_MAX_PROFILES == 100  # K1
    assert svc.BULK_VERIFY_PREVIEW_TTL == timedelta(minutes=30)  # TTL kỹ thuật (Codex 64)
    assert svc.BULK_VERIFY_MAX_LIVE_PREVIEWS == 3  # ≤ 3 bản xem trước chưa chạy / người
    assert svc.BULK_VERIFY_LIST_WINDOW_DAYS == 30  # X3 — owner chốt 17-11
    assert svc.BULK_VERIFY_LIST_PAGE_SIZE == 20


def test_tran_duyet_cheo_14_ngay():
    from app.models.admission_config.document_review import CROSS_REVIEW_MAX_DAYS

    assert CROSS_REVIEW_MAX_DAYS == 14  # 6a — owner chốt


# ---------------------------------------------------------------------------------------------------- sổ khoá tư vấn
def test_vung_khoa_moi_la_int4_duong_va_khac_nhau():
    ns = keys.REGISTERED_NAMESPACES
    assert len(set(ns)) == len(ns)
    assert all(isinstance(x, int) and 0 < x <= keys.INT4_MAX for x in ns)
    assert keys.BULK_VERIFY_BATCH_NS != keys.BULK_VERIFY_PREVIEW_NS


def test_so_khoa_ghi_dung_cac_vung_hai_khoa_dang_co():
    from app.repositories.council_document_repository import BUILD_LOCK_KEY
    from app.services.invoice_service import InvoiceService
    from app.services.public_lead_intake_service import _INTAKE_ADVISORY_NS

    assert _INTAKE_ADVISORY_NS in keys.EXISTING_INT_NAMESPACES
    assert BUILD_LOCK_KEY in keys.EXISTING_HASHTEXT_NAMESPACES
    assert f"invoice_number:{InvoiceService._INVOICE_PREFIX}" in keys.EXISTING_HASHTEXT_NAMESPACES
    assert not set(keys.REGISTERED_NAMESPACES) & set(keys.EXISTING_INT_NAMESPACES)


@pytest.mark.parametrize(
    "ma, mong",
    [
        ("00000000-0000-4000-8000-000000000000", 0),
        ("ffffffff-ffff-4fff-bfff-ffffffffffff", 0x7FFFFFFF),
        ("12345678-9abc-4def-8123-456789abcdef", 0x12345678),
        ("9a345678-9abc-4def-8123-456789abcdef", 0x1A345678),
    ],
)
def test_anh_xa_ma_lo_sang_khoa_duong_31_bit(ma, mong):
    k = keys.batch_lock_key(UUID(ma))
    assert k == mong and 0 <= k <= keys.INT4_MAX


def test_moi_loi_goi_khoa_tu_van_moi_dung_tham_so_khong_so_cung():
    """Lời gọi ``pg_*advisory*`` trong mã lô chỉ truyền vùng qua tham số ``:ns`` (giá trị lấy từ sổ), không số cứng."""
    import ast

    goi = re.compile(r"pg_(?:try_)?advisory_(?:xact_)?(?:un)?lock\(([^)]*)\)")
    thay = 0
    for tep in TEP_LO:
        cay = ast.parse((GOC / tep).read_text(encoding="utf-8"))
        for nut in ast.walk(cay):
            # Chỉ câu SQL thật: đối số chuỗi của ``text(...)``.
            if not (isinstance(nut, ast.Call) and getattr(nut.func, "id", None) == "text" and nut.args):
                continue
            if not (isinstance(nut.args[0], ast.Constant) and isinstance(nut.args[0].value, str)):
                continue
            for m in goi.finditer(nut.args[0].value):
                thay += 1
                dau = m.group(1).split(",")[0].strip()
                assert dau == ":ns", f"{tep}: {m.group(0)}"
    assert thay >= 4  # thử khoá phiên, nhả khoá phiên, thử khoá giao dịch, khoá giao dịch theo người
    nguon = (GOC / "app/services/document_bulk_verify_service.py").read_text(encoding="utf-8")
    assert "BULK_VERIFY_BATCH_NS" in nguon and "BULK_VERIFY_PREVIEW_NS" in nguon


def test_engine_khoa_lo_la_nullpool_rieng():
    from sqlalchemy.pool import NullPool

    import app.database as csdl
    from app.repositories import document_bulk_repository as repo

    e = repo.lock_engine()
    assert isinstance(e.pool, NullPool)
    assert e is not csdl.engine


# ---------------------------------------------------------------------------------------------------- schema
def test_than_execute_khong_co_truong_muc():
    assert set(sch.BulkVerifyExecuteRequest.model_fields) == {"confirmation_text"}
    with pytest.raises(PydanticValidationError):
        sch.BulkVerifyExecuteRequest(confirmation_text="ok", items=[{"document_row_id": 1}])


def test_xem_truoc_dung_mot_trong_hai_nguon():
    with pytest.raises(PydanticValidationError):
        sch.BulkVerifyPreviewRequest(profile_ids=[1], filter={})
    with pytest.raises(PydanticValidationError):
        sch.BulkVerifyPreviewRequest()
    assert sch.BulkVerifyPreviewRequest(profile_ids=[3, 1, 3]).profile_ids == [1, 3]


def test_bo_loc_thanh_toan_khop_danh_sach():
    from app.routers.admissions import ALLOWED_PAYMENT_STATUSES

    assert tuple(get_args(sch.PaymentStatusFilter)) == tuple(ALLOWED_PAYMENT_STATUSES)


def test_bo_loc_cung_ten_tham_so_voi_danh_sach_ho_so():
    from app.routers.admissions import list_admission_profiles

    ds = set(inspect.signature(list_admission_profiles).parameters) - {
        "request", "sort_by", "order", "page", "page_size", "db", "current_user"
    }
    assert set(sch.BulkVerifyFilter.model_fields) == ds


def test_ten_truong_moi_tieng_anh_snake_case():
    from pydantic import BaseModel

    mau = re.compile(r"^[a-z][a-z0-9_]*$")
    for ten, lop in vars(sch).items():
        if isinstance(lop, type) and issubclass(lop, BaseModel) and lop.__module__ == sch.__name__:
            for f in lop.model_fields:
                assert mau.match(f) and f.isascii(), f"{ten}.{f}"


def test_ma_loi_va_trang_thai_moi_tieng_anh():
    mau = re.compile(r"^[a-z_]+$")
    for x in (*sch.BATCH_VIEW_STATUSES, *sch.BATCH_ITEM_VIEW_RESULTS, svc.PROFILE_OVER_DOCUMENT_CAP, svc.PROFILE_BUSY,
              svc.SYSTEM_ERROR, svc.ACTOR_NOT_AUTHORIZED):
        assert mau.match(x), x


def test_cap_quyen_cheo_bat_buoc_co_mui_gio_va_mot_thao_tac():
    han = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(PydanticValidationError):
        sch.CrossReviewGrantCreate(grantee_user_id=1, unit_id=1, allow_verify=False, allow_reject=False, expires_at=han,
                                   reason="x")
    with pytest.raises(PydanticValidationError):
        sch.CrossReviewGrantCreate(grantee_user_id=1, unit_id=1, allow_verify=True, expires_at=han.replace(tzinfo=None),
                                   reason="x")
    with pytest.raises(PydanticValidationError):
        sch.CrossReviewGrantCreate(grantee_user_id=1, unit_id=1, allow_verify=True, expires_at=han, reason="   ")


# ---------------------------------------------------------------------------------------------------- chọn quyền theo thao tác
def test_chon_quyen_theo_tung_thao_tac_khong_de_quyen_tu_choi_che_quyen_duyet():
    """Codex 69 (đơn vị): G1 chỉ ``reject`` hạn XA, G2 chỉ ``verify`` hạn gần ⇒ verify = G2, reject = G1."""
    from app.services.document_cross_review_service import pick_grant_for_action

    now = datetime.now(timezone.utc)
    g1 = SimpleNamespace(id=1, unit_id=7, allow_verify=False, allow_reject=True, expires_at=now + timedelta(days=10))
    g2 = SimpleNamespace(id=2, unit_id=7, allow_verify=True, allow_reject=False, expires_at=now + timedelta(days=2))
    g3 = SimpleNamespace(id=3, unit_id=8, allow_verify=True, allow_reject=True, expires_at=now + timedelta(days=13))
    assert pick_grant_for_action([g1, g2, g3], 7, "verify") == 2
    assert pick_grant_for_action([g1, g2, g3], 7, "reject") == 1
    assert pick_grant_for_action([g1, g2, g3], 9, "verify") is None


def test_chon_quyen_cung_han_lay_id_lon_nhat():
    from app.services.document_cross_review_service import pick_grant_for_action

    han = datetime.now(timezone.utc) + timedelta(days=3)
    gs = [SimpleNamespace(id=i, unit_id=1, allow_verify=True, allow_reject=False, expires_at=han) for i in (4, 9, 6)]
    assert pick_grant_for_action(gs, 1, "verify") == 9
