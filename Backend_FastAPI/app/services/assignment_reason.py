"""Single source of truth cho ``AssignmentLog.reason`` phục vụ phân loại
self-sourced (officer tự tuyển).

``assignment_service._self_sourced_subquery`` phân loại "officer TỰ TUYỂN" bằng
cách match ``SELF_SOURCED_REASON_TOKEN`` trong ``reason``. ``reason`` được sinh bởi
``build_assignment_reason()`` ở lead_service (create+direct-assign / assign tay).

Gộp CẢ builder LẪN token ở MỘT nơi để producer (lead_service) và matcher
(assignment_service) KHÔNG THỂ drift âm thầm — nếu drift, feature exclude-self-
sourced sẽ no-op im lặng khi bật flag. Ghim bởi
``test_self_sourced_reason_token_contract`` (assert builder-output-cho-officer
CHỨA token). Refactor thuần: output byte-identical chuỗi reason cũ ⇒ dữ liệu prod
hiện có vẫn khớp.
"""
from typing import TYPE_CHECKING

from ..core.constants import UserRole

if TYPE_CHECKING:
    from .. import models

# Substring CÓ MẶT trong reason khi người-gán là OFFICER (UserRole StrEnum ⇒
# ``f"{UserRole.OFFICER}"`` = "officer" ⇒ token = "by officer "). Đây là thứ
# ``_self_sourced_subquery`` match: ``reason ILIKE '%<token>%'``.
SELF_SOURCED_REASON_TOKEN = f"by {UserRole.OFFICER} "


def build_assignment_reason(prefix: str, actor: "models.User | None") -> str:
    """Dựng ``AssignmentLog.reason`` dạng ``{prefix} by {role} {username}``
    (``actor=None`` ⇒ ``{prefix} by system``).

    Khi ``actor`` là OFFICER, kết quả CHỨA ``SELF_SOURCED_REASON_TOKEN`` ⇒
    _self_sourced_subquery xếp là tự tuyển. Đổi shape ``... by <role> <name>``
    (vd bỏ chữ "by", đảo thứ tự) BẮT BUỘC cập nhật ``SELF_SOURCED_REASON_TOKEN`` +
    pattern subquery cùng lúc — nếu quên, test contract sẽ đỏ.
    """
    who = f"{actor.role} {actor.username}" if actor is not None else "system"
    return f"{prefix} by {who}"
