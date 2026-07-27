"""Lock-in: phạm vi phí HK1 chỉ có MỘT nguồn.

Bộ ba ``fee_type='tuition'`` + ``semester_no == 1`` + ``status <> 'cancelled'``
từng được viết lại bằng tay ở hai bản SQL độc lập (danh sách hồ sơ và giảm trừ
tải phân công lead). Hai bản lệch nhau nghĩa là bảng "điểm bận" và danh sách hồ
sơ nói hai con số khác nhau về cùng một hồ sơ — hỏng âm thầm, không có lỗi nào
nổ ra.

Các test dưới đây so khớp SQL đã biên dịch, nên chúng ĐỎ ngay khi một call site
tự viết lại vị từ thay vì gọi ``constants/hk1_fee``.

Thuần biên dịch SQLAlchemy — không cần database.
"""

import pytest
from sqlalchemy.dialects import postgresql

from app.constants.hk1_fee import (
    confirmed_paid_hk1_conditions,
    hk1_fee_scope_conditions,
)

pytestmark = pytest.mark.unit


def _sql(clause) -> str:
    """Biên dịch một mệnh đề thành SQL literal để so khớp chuỗi."""
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _sql_of_each(conditions) -> list:
    return [_sql(c) for c in conditions]


# ---------------------------------------------------------------------------
# Tầng phạm vi
# ---------------------------------------------------------------------------


def test_scope_has_exactly_the_three_hk1_conditions():
    """Phạm vi HK1 = đúng ba điều kiện, không hơn không kém.

    Đặc biệt KHÔNG được có ``paid_amount`` — các subquery cộng tiền trong
    ``admission_repository`` (Σ paid / Σ remaining / Σ final) dùng chung tầng này;
    lọc theo đã-thu ở đây sẽ khiến "còn phải thu" báo thiếu.
    """
    sqls = _sql_of_each(hk1_fee_scope_conditions())

    assert len(sqls) == 3
    joined = " AND ".join(sqls)
    assert "fee.fee_type = 'tuition'" in joined
    assert "fee.semester_no = 1" in joined
    assert "fee.status != 'cancelled'" in joined
    assert "paid_amount" not in joined
    assert "waived_amount" not in joined


def test_scope_adds_join_condition_only_when_profile_expr_given():
    """Có JOIN sẵn thì gọi không tham số; dạng correlated thì truyền biểu thức."""
    from app import models

    without = _sql_of_each(hk1_fee_scope_conditions())
    with_expr = _sql_of_each(hk1_fee_scope_conditions(models.AdmissionProfile.id))

    assert len(with_expr) == len(without) + 1
    assert with_expr[0] == "fee.admission_profile_id = admission_profile.id"


# ---------------------------------------------------------------------------
# Tầng đã-thu-tiền
# ---------------------------------------------------------------------------


def test_confirmed_paid_is_scope_plus_paid_amount_only():
    """Tầng cohort = tầng phạm vi + đúng MỘT điều kiện ``paid_amount > 0``.

    Ghim quan hệ giữa hai tầng: nếu ai đó thêm điều kiện vào tầng trên mà quên
    tầng dưới (hoặc ngược lại), test này đỏ.
    """
    scope = _sql_of_each(hk1_fee_scope_conditions())
    paid = _sql_of_each(confirmed_paid_hk1_conditions())

    assert paid[: len(scope)] == scope
    assert paid[len(scope) :] == ["fee.paid_amount > 0"]


def test_confirmed_paid_ignores_waived_amount():
    """Miễn giảm KHÔNG phải "đã đóng" — ca miễn toàn phần đi đường sts10."""
    assert "waived_amount" not in " AND ".join(
        _sql_of_each(confirmed_paid_hk1_conditions())
    )


# ---------------------------------------------------------------------------
# Lock-in hai call site SQL
# ---------------------------------------------------------------------------


def test_admission_repository_predicate_uses_shared_scope():
    """``_hk1_fee_predicate`` phải sinh đúng phạm vi dùng chung (dạng correlated)."""
    from sqlalchemy import and_

    from app import models
    from app.repositories.admission_repository import _hk1_fee_predicate

    expected = _sql(and_(*hk1_fee_scope_conditions(models.AdmissionProfile.id)))
    assert _sql(_hk1_fee_predicate()) == expected


def test_assignment_service_exists_contains_shared_scope():
    """``_hk1_fee_exists`` phải chứa NGUYÊN VĂN cả ba điều kiện phạm vi."""
    from app.services.assignment_service import _hk1_fee_exists

    rendered = _sql(_hk1_fee_exists())
    for condition_sql in _sql_of_each(hk1_fee_scope_conditions()):
        assert condition_sql in rendered


def test_assignment_service_and_repository_agree_on_hk1_scope():
    """Hai bản SQL độc lập phải nói CÙNG một phạm vi HK1.

    Đây là test nối hai bản: chừng nào còn tồn tại hai đường dẫn SQL riêng biệt
    thì phải có một chỗ buộc chúng khớp nhau.
    """
    from app.repositories.admission_repository import _hk1_fee_predicate
    from app.services.assignment_service import _hk1_fee_exists

    repo_sql = _sql(_hk1_fee_predicate())
    svc_sql = _sql(_hk1_fee_exists())

    for token in ("fee_type = 'tuition'", "semester_no = 1", "status != 'cancelled'"):
        assert token in repo_sql, f"thiếu {token!r} ở admission_repository"
        assert token in svc_sql, f"thiếu {token!r} ở assignment_service"


def test_tuition_payment_confirmed_matches_confirmed_paid_layer():
    """Vị từ "đã xác nhận thu tiền" của phân công phải khớp tầng cohort.

    ``_tuition_payment_confirmed_subquery`` và ``confirmed_paid_hk1_conditions``
    là hai đường tới cùng một khái niệm (HK1 đã có tiền vào, một phần hay đủ).
    Test này là sợi dây nối chúng.
    """
    from app.services.assignment_service import (
        _tuition_payment_confirmed_subquery,
    )

    rendered = _sql(_tuition_payment_confirmed_subquery())
    for condition_sql in _sql_of_each(confirmed_paid_hk1_conditions()):
        assert condition_sql in rendered


def test_scope_layer_is_not_accidentally_the_paid_layer():
    """Chống hợp nhất nhầm hai tầng thành một."""
    assert _sql_of_each(hk1_fee_scope_conditions()) != _sql_of_each(
        confirmed_paid_hk1_conditions()
    )


# ---------------------------------------------------------------------------
# Lock-in CẤU TRÚC — call site có THỰC SỰ gọi helper không
# ---------------------------------------------------------------------------
#
# Các test so khớp SQL ở trên chỉ chứng minh hai bên nói cùng một câu SQL. Chúng
# vẫn xanh nếu ai đó gỡ lời gọi helper rồi chép tay lại đúng ba điều kiện — tức
# là nợ "nhiều nguồn" quay lại mà không ai biết.
#
# Nhóm test dưới đây thay helper bằng một điều kiện SENTINEL và đòi call site
# phải nhả ra chính sentinel đó. Chép tay = không có sentinel = ĐỎ.
#
# ⚠️ Vá ở HAI CẤP KHÁC NHAU, có chủ đích:
#   * ``admission_repository`` và ``assignment_service`` import helper BÊN TRONG
#     thân hàm → tra cứu lại mỗi lần gọi → vá trên module ``constants.hk1_fee``.
#   * ``dorm_export_repository`` import ở đầu file → tên đã gắn vào namespace của
#     chính nó → phải vá trên module đó. Vá nhầm chỗ sẽ khiến test xanh giả.

_SENTINEL = "SENTINEL_HK1_SCOPE_4b7e"
_SENTINEL_PAID = "SENTINEL_HK1_PAID_4b7e"


def _sentinel_scope(profile_id_expr=None):
    from app.models.finance import Fee

    return [Fee.notes == _SENTINEL]


def _sentinel_paid(profile_id_expr=None):
    from app.models.finance import Fee

    return [Fee.notes == _SENTINEL_PAID]


def test_repository_predicate_really_calls_the_helper(monkeypatch):
    from app.constants import hk1_fee as hk1_fee_module
    from app.repositories.admission_repository import _hk1_fee_predicate

    monkeypatch.setattr(hk1_fee_module, "hk1_fee_scope_conditions", _sentinel_scope)
    assert _SENTINEL in _sql(_hk1_fee_predicate())


def test_assignment_exists_really_calls_the_helper(monkeypatch):
    from app.constants import hk1_fee as hk1_fee_module
    from app.services.assignment_service import _hk1_fee_exists

    monkeypatch.setattr(hk1_fee_module, "hk1_fee_scope_conditions", _sentinel_scope)
    assert _SENTINEL in _sql(_hk1_fee_exists())


def test_dorm_cohort_really_calls_the_paid_helper(monkeypatch):
    """Cohort KTX phải ăn tầng ``confirmed_paid_hk1_conditions``, không tự viết.

    Vá trên chính ``dorm_export_repository`` vì nó import ở đầu file (xem ghi chú
    khối trên).
    """
    from app.repositories import dorm_export_repository as dorm_repo

    monkeypatch.setattr(dorm_repo, "confirmed_paid_hk1_conditions", _sentinel_paid)
    assert _SENTINEL_PAID in _sql(dorm_repo.select_paid_hk1_cohort(2026))


def test_sentinel_patch_actually_takes_effect():
    """Chốt an toàn cho chính bộ test: không vá thì không có sentinel.

    Nếu test này đỏ nghĩa là sentinel rò rỉ từ chỗ khác và ba test trên trở nên
    vô nghĩa (luôn xanh).
    """
    from app.repositories.admission_repository import _hk1_fee_predicate

    assert _SENTINEL not in _sql(_hk1_fee_predicate())
