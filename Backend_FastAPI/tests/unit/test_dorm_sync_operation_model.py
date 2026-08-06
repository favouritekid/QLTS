"""Bốn trạng thái của ``dorm_sync_operations`` được khai ở BA nơi — ràng chúng lại.

Hằng số Python, CHECK constraint trên model, và CHECK trong migration Alembic là
ba bản chép của cùng một danh sách. Không có ca nào nối chúng thì lần sửa đầu
tiên sẽ làm chúng lệch, và kiểu lệch đó không nổ ra lúc chạy: model cho phép ghi
một trạng thái mà database từ chối, hoặc ngược lại — database nhận một trạng
thái mà không nhánh xử lý nào biết đến.

``outcome_unknown`` là trạng thái dễ bị đánh rơi nhất vì nó hiếm, nên nó được
kiểm đích danh.
"""

from pathlib import Path

import pytest

from app.models.dorm_sync_operation import (
    CAC_TRANG_THAI,
    TRANG_THAI_OUTCOME_UNKNOWN,
    DormSyncOperation,
)

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "dsync20260807001_dorm_sync_operations.py"
)


def test_dung_bon_trang_thai_khong_thua_khong_thieu():
    assert set(CAC_TRANG_THAI) == {
        "running",
        "completed",
        "failed",
        "outcome_unknown",
    }


def test_outcome_unknown_ton_tai_rieng_khong_gop_vao_failed():
    """Gộp hai trạng thái này sẽ mời người vận hành chạy lại một lượt có thể đã
    ghi xong bên KTX — mà lượt hạ cờ thì không có đường lùi."""
    assert TRANG_THAI_OUTCOME_UNKNOWN in CAC_TRANG_THAI
    assert TRANG_THAI_OUTCOME_UNKNOWN != "failed"


def test_check_constraint_tren_model_liet_ke_du_bon():
    check = next(
        c
        for c in DormSyncOperation.__table__.constraints
        if getattr(c, "name", None) == "ck_dorm_sync_operations_status"
    )
    dieu_kien = str(check.sqltext)

    for trang_thai in CAC_TRANG_THAI:
        assert f"'{trang_thai}'" in dieu_kien, (
            f"CHECK trên model thiếu {trang_thai!r} — database sẽ từ chối một "
            "trạng thái mà mã Python coi là hợp lệ"
        )


def test_migration_khai_dung_bon_trang_thai_nhu_model():
    """🔴 Vế nối. Sửa hằng số Python mà quên migration thì ca này đỏ."""
    noi_dung = _MIGRATION.read_text(encoding="utf-8")

    for trang_thai in CAC_TRANG_THAI:
        assert f"'{trang_thai}'" in noi_dung, (
            f"migration thiếu {trang_thai!r} trong CHECK — model và database "
            "sẽ hiểu khác nhau về tập trạng thái hợp lệ"
        )


def test_operation_id_la_UNIQUE():
    """Hàng rào chống replay. Mất UNIQUE thì hai apply cùng operation_id đều
    chèn được, và ``ON CONFLICT DO NOTHING`` không còn gì để đụng."""
    cot = DormSyncOperation.__table__.columns["operation_id"]
    co_unique = cot.unique or any(
        "operation_id" in [c.name for c in getattr(rb, "columns", [])]
        for rb in DormSyncOperation.__table__.constraints
        if rb.__class__.__name__ == "UniqueConstraint"
    )
    assert co_unique


def test_migration_giu_UNIQUE_va_FK_RESTRICT():
    noi_dung = _MIGRATION.read_text(encoding="utf-8")

    assert "uq_dorm_sync_operations_operation_id" in noi_dung
    # RESTRICT chứ không CASCADE: xoá người bấm là mất dấu vết của một thao tác
    # đã đổi dữ liệu bên KTX.
    assert 'ondelete="RESTRICT"' in noi_dung
