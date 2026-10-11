"""Đổi "thông tư áp dụng" của một hồ sơ tuyển sinh bằng tay (V3 C5).

Owner chốt (11-10-2026):
* T2c — manager + admin được đổi, có lịch sử;
* Q3 "Như ấn định KV" — cùng ma trận trạng thái với ``priority_override_service.override_kv``: trước công bố
  manager/admin; sau công bố CHỈ admin và phải xác nhận ``acknowledge_post_publish``; cấm hẳn ở các trạng thái
  rút/loại; lý do bắt buộc;
* Q4 "Chỉ lý do" — không đòi minh chứng.

Ba tập trạng thái và ngưỡng độ dài lý do được IMPORT từ ``priority_override_service`` — không chép (một nguồn;
``tests/api/test_applicable_circular_endpoint.py`` khoá bằng phép so ``is``).

Phân quyền route ở Casbin (``v3circ20261011b``: manager/admin allow, accountant deny, officer không có dòng);
IDOR ở ``get_admission_for_user``. Phép kiểm vai trò ở đây là phòng thủ chiều sâu, như ``override_kv``.

Không phát thông báo: owner chỉ đòi "có lịch sử" — hàng ``priority_audit_log`` ``circular_changed`` là lịch sử ấy.
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..constants.admission_circular import CIRCULAR_SOURCE_MANUAL, CIRCULARS
from ..utils.exceptions import BusinessRuleViolation, ConflictError
from .priority_override_service import (
    _HARD_DENIED_STATUS,
    _MAX_REASON_LEN,
    _MIN_REASON_LEN,
    _POST_PUBLISH_STATUS,
)

log = structlog.get_logger(__name__)

_VAI_TRO_DUOC_DOI = frozenset({"admin", "manager"})


async def change_applicable_circular(
    db: AsyncSession,
    profile: models.AdmissionProfile,
    *,
    circular: str,
    reason: str,
    expected_version: int,
    actor: models.User,
    acknowledge_post_publish: bool = False,
    now: Optional[datetime] = None,
) -> models.AdmissionProfile:
    """Ghi thông tư mới + MỘT hàng nhật ký ``circular_changed`` + tăng version, trong giao dịch của caller.

    Raises:
        ConflictError (409): ``expected_version`` lệch.
        PermissionError (router → 403): vai trò không phải manager/admin; hoặc manager trên hồ sơ sau công bố.
        BusinessRuleViolation (400): trạng thái bị cấm; admin thiếu xác nhận sau công bố; lý do sai độ dài;
            mã thông tư lạ; đổi sang đúng giá trị đang có.
    """
    if expected_version != profile.version:
        raise ConflictError(
            "Hồ sơ vừa được người khác sửa (phiên bản %s, hiện tại %s). Vui lòng tải lại."
            % (expected_version, profile.version)
        )

    if actor.role not in _VAI_TRO_DUOC_DOI:
        raise PermissionError("Chỉ quản lý hoặc quản trị được đổi thông tư áp dụng của hồ sơ.")

    if circular not in CIRCULARS:
        raise BusinessRuleViolation("Mã thông tư không hợp lệ: %r" % (circular,))

    ly_do = (reason or "").strip()
    if not _MIN_REASON_LEN <= len(ly_do) <= _MAX_REASON_LEN:
        raise BusinessRuleViolation(
            "Lý do phải dài %d–%d ký tự (nhận %d)." % (_MIN_REASON_LEN, _MAX_REASON_LEN, len(ly_do))
        )

    if profile.status in _HARD_DENIED_STATUS:
        raise BusinessRuleViolation(
            "Không đổi được thông tư áp dụng ở trạng thái '%s'." % profile.status
        )

    sau_cong_bo = profile.status in _POST_PUBLISH_STATUS
    if sau_cong_bo:
        if actor.role != "admin":
            raise PermissionError(
                "Hồ sơ đã công bố ('%s'): chỉ quản trị được đổi thông tư áp dụng." % profile.status
            )
        if not acknowledge_post_publish:
            raise BusinessRuleViolation(
                "Hồ sơ đã công bố ('%s'). Gửi acknowledge_post_publish=true để xác nhận; việc này được ghi "
                "vào nhật ký." % profile.status
            )

    cu = profile.applicable_circular
    if cu == circular:
        raise BusinessRuleViolation("Hồ sơ đã áp dụng %s — không có gì để đổi." % circular)

    luc = now or datetime.now(timezone.utc)
    nguon_cu = profile.applicable_circular_source
    profile.applicable_circular = circular
    profile.applicable_circular_source = CIRCULAR_SOURCE_MANUAL
    profile.applicable_circular_set_at = luc
    profile.applicable_circular_set_by_id = actor.id
    db.add(
        models.PriorityAuditLog(
            profile_id=profile.id,
            action_type="circular_changed",
            actor_id=actor.id,
            old_value={"applicable_circular": cu, "applicable_circular_source": nguon_cu},
            new_value={"applicable_circular": circular, "reason": ly_do},
            audit_metadata={
                "actor_role": actor.role,
                "profile_status": profile.status,
                "acknowledged_post_publish": bool(acknowledge_post_publish) if sau_cong_bo else None,
            },
        )
    )
    profile.version += 1
    await db.flush()

    log.info(
        "applicable_circular_service.changed",
        profile_id=profile.id,
        actor_id=actor.id,
        actor_role=actor.role,
        old=cu,
        new=circular,
        version_after=profile.version,
    )
    return profile
