"""GĐ1b — duyệt chéo tạm thời (đặc tả bản 3.6 §6 + C9 / C11; hợp đồng API GĐ1b bản 4 §2.2).

- Admin cấp / thu hồi quyền theo TỪNG cán bộ nêu tên (C3); trần ``CROSS_REVIEW_MAX_DAYS = 14`` (6a); lý do bắt buộc; chỉ thu
  hồi, không xoá; mỗi lần cấp / thu hồi ghi sự kiện vào ``entity_audit_log`` (C9).
- ``eligibility``: CHỈ quyền còn hiệu lực của CHÍNH người gọi (Codex 68).
- Hàng đợi: phản hồi HẸP; với TỪNG thao tác chọn quyền còn hiệu lực phủ đơn vị lead VÀ cho phép ĐÚNG thao tác ấy —
  ``expires_at`` muộn nhất rồi ``id`` lớn nhất (Codex 69: quyền chỉ-từ-chối không được che quyền duyệt).
- Duyệt / từ chối lẻ: ``transition_document(via="cross", grant_id=…)`` — lõi kiểm lại dưới khoá (``clock_timestamp()``). Máy
  chủ KHÔNG tự đổi sang quyền khác: quyền sai / hết hạn / thu hồi / không cho đúng thao tác ⇒ 409 ``actor_not_authorized``
  khi người gọi còn quyền hợp lệ khác; không còn quyền nào cho đúng thao tác + đơn vị ⇒ 404 cùng thân (owner Q1, PR-B).
- Q4 (owner 20-11, PR-B): đổi vai khỏi Cán bộ / khoá tài khoản ⇒ TỰ THU HỒI mọi quyền chưa hết hạn của người ấy ở mọi đơn
  vị, CÙNG giao dịch — :func:`revoke_grants_on_account_change` (tầng chủ sở hữu; mọi đường đổi vai / trạng thái gọi nó).
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
from app.services.document_bulk_verify_service import (
    BulkBatchConflict,
    BulkVerifyUnprocessable,
    CrossReviewNotFound,
    grant_allows,
)
from app.services.document_transition import ACTOR_NOT_AUTHORIZED, DocumentTransitionConflict, RequestMeta
from app.utils.exceptions import CombinedKeyChangeAndRevokeError, PermissionDeniedError, ResourceNotFoundError

log = structlog.get_logger(__name__)

GRANT_ENTITY_TYPE = "document_cross_review_grant"

#: Q4 — nhãn vai tiếng Việt cho câu lý do tự thu hồi (vai lạ ⇒ in nguyên mã).
ROLE_LABELS_VI: Dict[str, str] = {
    UserRole.OFFICER: "Cán bộ",
    UserRole.MANAGER: "Quản lý",
    UserRole.ADMIN: "Admin",
    UserRole.ACCOUNTANT: "Kế toán",
    UserRole.COLLABORATOR: "Cộng tác viên",
    UserRole.USER: "Người dùng",
}
AUTO_REVOKE_PREFIX = "Tự thu hồi: "
AUTO_REVOKE_LOCKED = "tài khoản bị khoá"


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


#: MỘT nguồn "quyền cho phép đúng thao tác" — ``document_bulk_verify_service.grant_allows`` (bản cũ ở đây là bản chép).
_allows = grant_allows


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
    # PR-B (Q4, vá nhánh): người được cấp đọc DƯỚI khoá ``FOR SHARE`` (thứ tự người → quyền) — xung đột với đổi vai / khoá
    # tài khoản (``FOR NO KEY UPDATE``). Đọc không khoá (bản cũ) thì một lần cấp chen vào lúc tài khoản đang bị khoá / đổi
    # vai sẽ tạo quyền còn hiệu lực SAU khi lệnh tự thu hồi đã chạy ⇒ mở lại tài khoản là dùng được quyền ấy (trái Q4).
    grantee = await repo.lock_user_role_share(db, body.grantee_user_id)
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


async def _write_revocations(
    db: AsyncSession,
    grants: Sequence[models.DocumentCrossReviewGrant],
    *,
    admin_id: int,
    reason: str,
    meta: RequestMeta,
) -> None:
    """MỘT khuôn ghi thu hồi (Admin thu hồi tay + Q4 tự thu hồi): ``revoked_at`` = đồng hồ CSDL, ``revoked_by_user_id`` =
    Admin thao tác, mỗi quyền MỘT dòng ``entity_audit_log`` ``revoked`` kèm ``reason`` — cùng giao dịch người gọi, không
    commit. Dòng quyền phải ĐÃ khoá ``FOR UPDATE``. Lỗi ghi nhật ký ném ra ⇒ người gọi không commit ⇒ rollback cả thu hồi."""
    from app.services.audit_service import log_audit

    now = await repo.db_clock(db)
    for grant in grants:
        grant.revoked_at = now
        grant.revoked_by_user_id = admin_id
    await db.flush()
    for grant in grants:
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


async def revoke_grant(
    db: AsyncSession, *, admin_id: int, grant_id: int, reason: str, request_meta: Optional[RequestMeta] = None
) -> Dict[str, Any]:
    meta = request_meta or RequestMeta()
    reason = (reason or "").strip()
    if not reason:
        raise BulkVerifyUnprocessable("REASON_REQUIRED", "Thu hồi quyền duyệt chéo phải ghi lý do")
    grant = await repo.lock_grant_for_update(db, grant_id)
    if grant is None:
        raise ResourceNotFoundError(detail="Không tìm thấy quyền duyệt chéo")
    if grant.revoked_at is not None:
        raise BulkBatchConflict("GRANT_ALREADY_REVOKED", "Quyền này đã bị thu hồi")
    await _write_revocations(db, [grant], admin_id=admin_id, reason=reason, meta=meta)
    log.info("cross_review_revoked", grant_id=grant.id)
    return _grant_view(grant, False)


# ---------------------------------------------------------------------------------------------------------------------
# Q4 (owner 20-11) — đổi vai / khoá tài khoản ⇒ tự thu hồi
# ---------------------------------------------------------------------------------------------------------------------
def _role_label(role: Any) -> str:
    code = str(getattr(role, "value", role))
    return ROLE_LABELS_VI.get(code, code)


def auto_revoke_reason(
    *,
    old_role: Any,
    old_status: Optional[str],
    new_role: Any = None,
    new_status: Optional[str] = None,
) -> Optional[str]:
    """MỘT vị từ Q4 "thay đổi tài khoản này có kéo theo tự thu hồi quyền duyệt chéo không" + câu lý do (``None`` = không).
    Owner chốt 21-11 (câu 1, 2):

    - trạng thái từ ``active`` sang BẤT KỲ trạng thái khác (kể cả chờ duyệt) ⇒ "Tự thu hồi: tài khoản bị khoá";
    - vai từ Cán bộ sang vai khác ⇒ "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang <vai mới thực tế>";
    - một thao tác vừa khoá vừa đổi vai ⇒ ghi CẢ HAI câu (nối bằng "; ").

    ``new_role`` / ``new_status`` = ``None`` ⇒ không đổi. Giá trị cũ phải đọc DƯỚI khoá (``revoke_grants_on_account_change``).
    KHÔNG thu hồi (owner câu 3, 4, 5): khoá đăng nhập tạm (Redis, không đổi trạng thái), đổi đơn vị của Cán bộ, xoá tài
    khoản (K4 409)."""
    parts: List[str] = []
    if new_status is not None and old_status == "active" and new_status != "active":
        parts.append(AUTO_REVOKE_PREFIX + AUTO_REVOKE_LOCKED)
    if new_role is not None and str(old_role) == UserRole.OFFICER and str(new_role) != UserRole.OFFICER:
        parts.append(AUTO_REVOKE_PREFIX + f"tài khoản đổi vai từ {_role_label(old_role)} sang {_role_label(new_role)}")
    return "; ".join(parts) if parts else None


async def revoke_grants_on_account_change(
    db: AsyncSession,
    *,
    user_id: int,
    new_role: Any = None,
    new_status: Optional[str] = None,
    actor_id: Optional[int],
    request_meta: Optional[RequestMeta] = None,
    target_locked_for_update: bool = False,
) -> List[int]:
    """Q4 — TẦNG CHỦ SỞ HỮU của "đổi vai / khoá tài khoản ⇒ tự thu hồi". Mọi đường đổi vai / trạng thái tài khoản (PUT lẻ,
    hàng loạt, đồng bộ vai từ Casbin, gỡ vai) gọi hàm này TRONG giao dịch của chính việc đổi, TRƯỚC khi ghi vai / trạng
    thái, truyền giá trị MỚI sắp ghi (``None`` = không đổi).

    Thứ tự khoá (toàn cục, đầu ``document_bulk_verify_service``): dòng ``user`` ``FOR NO KEY UPDATE`` (= khoá của lệnh
    ``UPDATE "user"`` sắp chạy) → MỌI quyền chưa thu hồi, chưa hết hạn của người ấy ``FOR UPDATE`` (id tăng) → ghi thu hồi
    + nhật ký (:func:`_write_revocations`). Vai / trạng thái CŨ đọc DƯỚI khoá dòng ``user`` (PR-B lượt 2 — cùng khuôn điểm
    chặn 4 của Codex: không quyết bằng bản đọc từ đầu yêu cầu, vì giữa đó tài khoản có thể vừa được trả vai / mở khoá và
    cấp quyền mới). Không commit; mọi lỗi ném ra ⇒ người gọi KHÔNG commit ⇒ rollback CẢ việc đổi vai / khoá LẪN việc thu
    hồi. Quyền đã thu hồi không bao giờ được khôi phục (mở khoá / trả vai ⇒ Admin cấp mới). Trả id các quyền vừa thu hồi.

    ``target_locked_for_update`` (PR-B lượt 8, owner 23-11 "chặn gộp, làm 2 bước"): người gọi đang giữ dòng người ``FOR
    UPDATE`` (lần lưu ĐỔI cột khoá — email / tên đăng nhập, ``user_deletion_policy.USER_KEY_COLUMNS``). Khi ấy thay đổi mà
    kéo theo thu hồi (lý do tính DƯỚI khoá bằng :func:`auto_revoke_reason`) ⇒ ``CombinedKeyChangeAndRevokeError`` (409)
    TRƯỚC khi khoá dòng quyền — luật "không giữ dòng người ``FOR UPDATE`` rồi đi chờ dòng quyền" (lô chéo §5.4 giữ dòng quyền
    ``FOR SHARE`` rồi xin người bấm ``FOR KEY SHARE`` ⇒ vòng chờ). Không ghi gì: người gọi không commit."""
    if new_role is None and new_status is None:
        return []
    with db.no_autoflush:  # đọc dòng TRONG CSDL (giá trị cũ), không xả trước thay đổi đang chờ của chính người ấy
        locked = await repo.lock_user_no_key_update(db, user_id)
    if locked is None:
        return []
    reason = auto_revoke_reason(old_role=locked.role, old_status=locked.status, new_role=new_role, new_status=new_status)
    if reason is None:
        return []
    if target_locked_for_update:
        raise CombinedKeyChangeAndRevokeError()
    if actor_id is None:
        # Không có người thao tác thì không ghi được ``revoked_by_user_id`` đúng khuôn — fail-closed.
        raise RuntimeError("revoke_grants_on_account_change: thiếu người thao tác")
    grants = await repo.lock_active_grants_of_user_for_update(db, user_id)
    if grants:
        await _write_revocations(db, grants, admin_id=actor_id, reason=reason, meta=request_meta or RequestMeta())
        log.info("cross_review_auto_revoked", user_id=user_id, grant_ids=[g.id for g in grants])
    return [g.id for g in grants]


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
    db: AsyncSession, *, actor: Any, grant_id: Optional[int], action: str
) -> models.DocumentCrossReviewGrant:
    """Quyền ĐÚNG ``grant_id`` của người gọi, còn hiệu lực, cho phép ĐÚNG thao tác (kiểm sớm cho xem trước lô chéo; dưới khoá
    kiểm lại bằng ``_recheck_preview_grant``). Không đạt ⇒ owner câu 9 (Codex lượt 2 PR-B, điểm chặn 4a), xét ở ĐƠN VỊ ghi
    trên chính quyền được gửi (quyền của người gọi, mọi trạng thái): còn quyền KHÁC hợp lệ cho đúng thao tác ở đúng đơn vị ấy
    ⇒ 409 ``actor_not_authorized`` (làm mới, máy chủ không tự chọn quyền thay thế); không còn — kể cả khi chỉ còn quyền ở đơn
    vị khác — hay mã quyền không phải của người gọi ⇒ 404 cùng thân (``cross_denial``, MỘT vị từ)."""
    from app.services.document_bulk_verify_service import cross_denial, unit_scope

    unit_id = None
    if grant_id is not None:
        for g in await repo.active_grants_for_user(db, actor.id):
            if g.id == grant_id and _allows(g, action):
                return g
        unit_id = await repo.own_grant_unit_id(db, grant_id, actor.id)
    if unit_id is None:
        raise CrossReviewNotFound()
    raise await cross_denial(db, actor, action, unit_scope(unit_id))


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
    except CrossReviewNotFound:
        raise
    except ResourceNotFoundError:
        # Owner Q1: hồ sơ / lead / dòng giấy không còn (phát hiện dưới khoá) ⇒ CÙNG thân 404 với cổng vào.
        raise CrossReviewNotFound()
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
