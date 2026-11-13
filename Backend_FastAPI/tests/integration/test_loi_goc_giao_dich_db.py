# -*- coding: utf-8 -*-
"""D.2 (Codex lần 16) — ca CANH THƯ VIỆN cho :func:`quota_occupancy_service.loi_goc_giao_dich`, chỗ DUY NHẤT đọc thuộc
tính RIÊNG ``_rollback_exception`` của SQLAlchemy (ghim 2.0.44). Tạo lỗi flush THẬT trên PostgreSQL (khoá ngoại trỏ
tới dòng không có ⇒ SQLSTATE 23503) trong SAVEPOINT và trong giao dịch ngoài; helper phải trả ĐÚNG lỗi gốc ấy.
Nâng SQLAlchemy mà thuộc tính riêng đổi tên / đổi nghĩa ⇒ ca này đỏ TRƯỚC khi đường 409 "thử lại" âm thầm thành 500."""
import pytest
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import ma_loi_csdl
from app.services import quota_occupancy_service as qos

pytestmark = pytest.mark.integration

GIAI_DOAN_KHONG_CO = "khong_ton_tai_d2"


def _dong_loi():
    # stage_id trỏ tới giai đoạn KHÔNG tồn tại ⇒ flush vi phạm khoá ngoại (23503) ngay ở câu INSERT.
    return models.ConsultationStatus(id="d2_canh", name="d2", color_code="#000000", stage_id=GIAI_DOAN_KHONG_CO)


async def test_loi_goc_trong_savepoint(setup_test_database):
    async with AsyncSessionLocal() as db:
        async with db.begin():
            sp = None
            with pytest.raises(IntegrityError) as bat:
                async with db.begin_nested() as sp:
                    assert qos.loi_goc_giao_dich(sp) is None  # còn sống ⇒ None
                    db.add(_dong_loi())
                    await db.flush()
            goc = qos.loi_goc_giao_dich(sp)
            assert goc is not None, "SQLAlchemy không còn ghi lỗi flush vào savepoint — xem lại helper"
            assert ma_loi_csdl(goc)[0] == "23503", ma_loi_csdl(goc)
            assert ma_loi_csdl(bat.value)[0] == "23503"
            await db.rollback()


async def test_loi_goc_giao_dich_ngoai_khi_lop_duoi_nuot_loi(setup_test_database):
    # Như ``publish_result``: lớp dưới BẮT lỗi flush ("fail-soft") ⇒ lỗi chỉ còn lộ qua giao dịch đã chết.
    async with AsyncSessionLocal() as db:
        await db.begin()
        db.add(_dong_loi())
        try:
            await db.flush()
        except IntegrityError:
            pass  # lớp dưới nuốt
        gd = db.sync_session.get_transaction()
        assert gd is not None and not gd.is_active
        goc = qos.loi_goc_giao_dich(gd)
        assert goc is not None, "SQLAlchemy không còn ghi lỗi flush vào giao dịch — xem lại helper"
        assert ma_loi_csdl(goc)[0] == "23503", ma_loi_csdl(goc)
        await db.rollback()


def test_loi_goc_none_va_gd_none():
    assert qos.loi_goc_giao_dich(None) is None
