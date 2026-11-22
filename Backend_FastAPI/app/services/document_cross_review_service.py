"""GĐ1b — duyệt chéo tạm thời (đặc tả bản 3.6 §6 + C9 / C11; hợp đồng API GĐ1b bản 4 §2.2).

- Admin cấp / thu hồi quyền theo TỪNG cán bộ nêu tên (C3); trần ``CROSS_REVIEW_MAX_DAYS = 14`` (6a); lý do bắt buộc; chỉ thu
  hồi, không xoá; mỗi lần cấp / thu hồi ghi sự kiện vào ``entity_audit_log`` (C9).
- ``eligibility``: CHỈ quyền còn hiệu lực của CHÍNH người gọi (Codex 68).
- Hàng đợi: phản hồi HẸP; với TỪNG thao tác chọn quyền còn hiệu lực phủ đơn vị lead VÀ cho phép ĐÚNG thao tác ấy —
  ``expires_at`` muộn nhất rồi ``id`` lớn nhất (Codex 69: quyền chỉ-từ-chối không được che quyền duyệt).
- Duyệt / từ chối lẻ: ``transition_document(via="cross", grant_id=…)`` — lõi kiểm lại dưới khoá (``clock_timestamp()``). Máy
  chủ KHÔNG tự đổi sang quyền khác: quyền sai / hết hạn / thu hồi / không cho đúng thao tác ⇒ 409 ``actor_not_authorized``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.models.admission_config.document_review import CROSS_REVIEW_MAX_DAYS
from app.repositories import document_bulk_repository as repo
from app.services import document_review_rules as rules
from app.services import document_transition
from app.services.document_bulk_verify_service import BulkBatchConflict, BulkVerifyUnprocessable
from app.services.document_transition import ACTOR_NOT_AUTHORIZED, DocumentTransitionConflict, RequestMeta
from app.utils.exceptions import PermissionDeniedError, ResourceNotFoundError

log = structlog.get_logger(__name__)

GRANT_ENTITY_TYPE = "document_cross_review_grant"


def _grant_view(grant: models.DocumentCrossReviewGrant, is_active: bool) -> Dict[str, Any]:
    return {
        "id": grant.id,
        "grantee_user_id": grant.grantee_user_id,
        "unit_id": grant.unit_id,
        "allow_verify": grant.allow_verify,
        "allow_reject": grant.allow_reject,
        "granted_by_user_id": grant.granted_by_user_id,
        "granted_at": grant.granted_at,
        "expires_at": grant.expires_at,
        "reason": grant.reason,
        "revoked_at": grant.revoked_at,
        "revoked_by_user_id": grant.revoked_by_user_id,
        "is_active": is_active,
    }


def _allows(grant: models.DocumentCrossReviewGrant, action: str) -> bool:
    if action == rules.ACTION_VERIFY:
        return bool(grant.allow_verify)
    if action == rules.ACTION_REJECT:
        return bool(grant.allow_reject)
    return False


def pick_grant_for_action(
    grants: Sequence[models.DocumentCrossReviewGrant], unit_id: int, action: str
) -> Optional[int]:
    """MỘT nguồn cho ``grant_id_by_action``: trong các quyền còn hiệu lực PHỦ đơn vị lead VÀ CHO PHÉP ĐÚNG thao tác — chọn
    ``expires_at`` muộn nhất, rồi ``id`` lớn nhất. Không có ⇒ ``None``."""
    cands = [g for g in grants if g.unit_id == unit_id and _allows(g, action)]
    if not cands:
        return None
    return max(cands, key=lambda g: (g.expires_at, g.id)).id


# ---------------------------------------------------------------------------------------------------------------------
# Admin cấp / thu hồi / liệt kê
# ---------------------------------------------------------------------------------------------------------------------
async def create_grant(
    db: AsyncSession, *, admin_id: int, body: Any, request_meta: Optional[RequestMeta] = None
) -> Dict[str, Any]:
    from app.services.audit_service import log_audit

    meta = request_meta or RequestMeta()
    reason = body.reason.strip()
    if not reason:
        raise BulkVerifyUnprocessable("REASON_REQUIRED", "Cấp quyền duyệt chéo phải ghi lý do")
    grantee = (
        await db.execute(select(models.User).where(models.User.id == body.grantee_user_id))
    ).scalar_one_or_none()
    if grantee is None or grantee.role != UserRole.OFFICER or grantee.status != "active":
        raise BulkVerifyUnprocessable(
            "GRANTEE_NOT_ELIGIBLE", "Người được cấp phải là Cán bộ đang hoạt động"
        )
    unit = (
        await db.execute(select(models.OrganizationUnit.id).where(models.OrganizationUnit.id == body.unit_id))
    ).scalar_one_or_none()
    if unit is None:
        raise BulkVerifyUnprocessable("UNIT_NOT_FOUND", "Không tìm thấy đơn vị")
    now = await repo.db_clock(db)
    if body.expires_at <= now:
        raise BulkVerifyUnprocessable("EXPIRES_AT_INVALID", "Hạn quyền phải ở tương lai")
    if body.expires_at - now > timedelta(days=CROSS_REVIEW_MAX_DAYS):
        raise BulkVerifyUnprocessable(
            "GRANT_TOO_LONG",
            f"Một lần cấp tối đa {CROSS_REVIEW_MAX_DAYS} ngày — hết hạn thì cấp lại có lý do",
            {"max_days": CROSS_REVIEW_MAX_DAYS},
        )
    grant = models.DocumentCrossReviewGrant(
        grantee_user_id=body.grantee_user_id,
        unit_id=body.unit_id,
        allow_verify=bool(body.allow_verify),
        allow_reject=bool(body.allow_reject),
        granted_by_user_id=admin_id,
        granted_at=now,
        expires_at=body.expires_at,
        reason=reason,
    )
    db.add(grant)
    await db.flush()
    await log_audit(
        db,
        GRANT_ENTITY_TYPE,
        grant.id,
        "granted",
        actor_user_id=admin_id,
        new_value={
            "grantee_user_id": grant.grantee_user_id,
            "unit_id": grant.unit_id,
            "allow_verify": grant.allow_verify,
            "allow_reject": grant.allow_reject,
            "expires_at": grant.expires_at,
        },
        reason=reason,
        source="api",
        ip_address=meta.ip_address,
        user_agent=meta.user_agent or None,  # cột tự cắt theo độ dài (TruncatedString, PR-D F12)
    )
    log.info("cross_review_granted", grant_id=grant.id, grantee_user_id=grant.grantee_user_id, unit_id=grant.unit_id)
    return _grant_view(grant, True)


async def revoke_grant(
    db: AsyncSession, *, admin_id: int, grant_id: int, reason: str, request_meta: Optional[RequestMeta] = None
) -> Dict[str, Any]:
    from app.services.audit_service import log_audit

    meta = request_meta or RequestMeta()
    reason = (reason or "").strip()
    if not reason:
        raise BulkVerifyUnprocessable("REASON_REQUIRED", "Thu hồi quyền duyệt chéo phải ghi lý do")
    grant = await repo.lock_grant_for_update(db, grant_id)
    if grant is None:
        raise ResourceNotFoundError(detail="Không tìm thấy quyền duyệt chéo")
    if grant.revoked_at is not None:
        raise BulkBatchConflict("GRANT_ALREADY_REVOKED", "Quyền này đã bị thu hồi")
    now = await repo.db_clock(db)
    grant.revoked_at = now
    grant.revoked_by_user_id = admin_id
    await db.flush()
    await log_audit(
        db,
        GRANT_ENTITY_TYPE,
        grant.id,
        "revoked",
        actor_user_id=admin_id,
        old_value={"revoked_at": None},
        new_value={"revoked_at": now},
        reason=reason,
        source="api",
        ip_address=meta.ip_address,
        user_agent=meta.user_agent or None,  # cột tự cắt theo độ dài (TruncatedString, PR-D F12)
    )
    log.info("cross_review_revoked", grant_id=grant.id)
    return _grant_view(grant, False)


async def list_grants(
    db: AsyncSession, *, active: Optional[bool], grantee_user_id: Optional[int], unit_id: Optional[int]
) -> List[Dict[str, Any]]:
    return [
        _grant_view(g, is_active)
        for g, is_active in await repo.list_grants(db, active=active, grantee_user_id=grantee_user_id, unit_id=unit_id)
    ]


# ---------------------------------------------------------------------------------------------------------------------
# Người gọi: eligibility + hàng đợi
# ---------------------------------------------------------------------------------------------------------------------
async def eligibility(db: AsyncSession, *, user_id: int, role: str) -> Dict[str, Any]:
    if role != UserRole.OFFICER:
        return {"eligible": False, "grants": []}
    grants = await repo.active_grants_for_user(db, user_id)
    return {
        "eligible": bool(grants),
        "grants": [
            {
                "grant_id": g.id,
                "unit_id": g.unit_id,
                "allow_verify": g.allow_verify,
                "allow_reject": g.allow_reject,
                "expires_at": g.expires_at,
            }
            for g in grants
        ],
    }


async def require_grant_for_action(
    db: AsyncSession, *, actor_id: int, grant_id: Optional[int], action: str
) -> models.DocumentCrossReviewGrant:
    """Quyền ĐÚNG ``grant_id`` của người gọi, còn hiệu lực, cho phép ĐÚNG thao tác — không thì 409 ``actor_not_authorized``.
    (Kiểm sớm cho xem trước lô chéo; khi ghi, lõi kiểm lại dưới khoá.)"""
    if grant_id is None:
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    for g in await repo.active_grants_for_user(db, actor_id):
        if g.id == grant_id and _allows(g, action):
            return g
    raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)


async def queue(db: AsyncSession, *, actor: models.User, page: int, page_size: int) -> Dict[str, Any]:
    from app.services.admission_document_policy import DocumentActionPolicy
    from app.services.document_bulk_verify_service import _doc_rule_facts

    actor_id = actor.id
    grants = await repo.active_grants_for_user(db, actor_id)
    rows = await repo.cross_queue_candidates(
        db, unit_ids=sorted({g.unit_id for g in grants}), actor_id=actor_id, statuses=rules.PENDING_PROFILE_STATUSES
    )
    items: List[Dict[str, Any]] = []
    for doc, profile, lead in rows:
        if doc.document_type is None:
            continue
        code, is_extra, _is_mandatory, facts = _doc_rule_facts(profile, doc)
        policy = DocumentActionPolicy.for_(profile, actor)
        by_action: Dict[str, Optional[int]] = {}
        for action in (rules.ACTION_VERIFY, rules.ACTION_REJECT):
            gid = pick_grant_for_action(grants, lead.unit_id, action)
            if gid is not None:
                decision = rules.decide(
                    action, rules.VIA_CROSS, policy=policy, actor_id=actor_id, profile_status=profile.status,
                    doc=facts, grant_actions=frozenset({action}),
                )
                if not decision.allowed:
                    gid = None
            by_action[action] = gid
        if by_action[rules.ACTION_VERIFY] is None and by_action[rules.ACTION_REJECT] is None:
            continue
        items.append(
            {
                "profile_id": profile.id,
                "document_row_id": doc.id,
                "document_type_code": code,
                "row_version": doc.row_version,
                "actual_submission_format": doc.actual_submission_format,
                "profile_status": profile.status,
                "grant_id_by_action": by_action,
            }
        )
    start = (page - 1) * page_size
    return {"items": items[start : start + page_size], "page": page, "page_size": page_size, "total_count": len(items)}


# ---------------------------------------------------------------------------------------------------------------------
# Duyệt / từ chối lẻ
# ---------------------------------------------------------------------------------------------------------------------
async def cross_action(
    db: AsyncSession,
    *,
    actor_id: int,
    action: str,
    grant_id: int,
    profile_id: int,
    document_row_id: int,
    expected_row_version: int,
    reason: Optional[str],
    request_meta: Optional[RequestMeta] = None,
):
    """Trả ``(kết quả, finalize)`` — router commit rồi gọi ``finalize(True)``."""
    if action not in (rules.ACTION_VERIFY, rules.ACTION_REJECT):
        raise ValueError(action)
    reason = (reason or "").strip() or None
    if action == rules.ACTION_REJECT and not reason:
        raise BulkVerifyUnprocessable("REASON_REQUIRED", "Từ chối giấy phải ghi lý do")
    try:
        res = await document_transition.transition_document(
            db,
            profile_id=profile_id,
            document_row_id=document_row_id,
            action=action,
            actor_id=actor_id,
            via=rules.VIA_CROSS,
            expected_row_version=expected_row_version,
            grant_id=grant_id,
            reason=reason,
            request_meta=request_meta,
        )
    except PermissionDeniedError:
        # Đường chéo: ``decide`` chỉ trả ``not_permitted`` khi quyền KHÔNG cho đúng thao tác ⇒ 409 actor_not_authorized
        # (hợp đồng §2.2 — giao diện làm mới hàng đợi, máy chủ không tự đổi quyền).
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    return (
        {
            "profile_id": res.profile_id,
            "document_row_id": res.document_row_id,
            "action": res.action,
            "new_status": res.new_status,
            "row_version": res.row_version,
        },
        res.finalize,
    )
