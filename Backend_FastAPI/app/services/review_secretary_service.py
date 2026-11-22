# app/services/review_secretary_service.py
"""GĐ2-C C1 — quyền "Thư ký Hội đồng" (QĐB:26; thiết kế GĐ2-C 22-11 §2.2, §4, §6 hàng C1; owner C1 22-11, C2 22-11).

Luật (đã chốt):

* Admin gán / thu hồi / xem theo TỪNG người nêu tên; lý do bắt buộc ở cả gán lẫn thu hồi; chỉ thu hồi, không xoá; gán lại
  sau khi thu hồi = dòng mới. Mỗi lần gán / thu hồi ghi một dòng ``entity_audit_log`` (khuôn quyền duyệt chéo GĐ1b).
* **Không hết hạn** (owner C1 "Không hết hạn, giữ tới khi Admin thu hồi"): quyền chỉ hết khi Admin thu hồi, hoặc khi tài
  khoản bị khoá / đổi sang vai không còn được gán — tự thu hồi CÙNG giao dịch, cùng tầng chủ sở hữu với quyền duyệt chéo
  (``document_cross_review_service.revoke_grants_on_account_change`` gọi :func:`revoke_on_account_change`). Xoá tài khoản
  đã từng được gán ⇒ K4 409 (``user_deletion_policy``), không thu hồi.
* Gán cho ai: Quản lý hoặc Cán bộ đang hoạt động (thiết kế §4: "Casbin mở ``manager``, ``officer``").
* **Admin LUÔN là Thư ký** (owner 22-11, ``gd2c/c1/QUYET-DINH-OWNER-GD2C-C1-4-CAU-2026-11-22.md`` câu 1): Admin ĐANG HOẠT ĐỘNG
  qua cổng mà không cần (và không được) gán. ⚠️ Luật "người đề xuất ≠ người khoá" của GĐ2-C (ĐT3.2 T15b, thiết kế §4) VẪN áp
  cho Admin: là Thư ký KHÔNG có nghĩa Admin được vừa đề xuất vừa khoá cùng một lần xét — máy chủ kiểm lúc khoá (C4 / C5b),
  so ``proposed_by_user_id`` với người khoá, KHÔNG miễn cho vai nào.
* Phạm vi: TOÀN TRƯỜNG (owner C2 22-11) ⇒ bảng quyền không có cột đơn vị.
* Cổng ``deps.require_review_secretary`` (:func:`require_secretary_access`): đọc vai + trạng thái của người gọi và quyền gán
  còn hiệu lực TRONG giao dịch của chính yêu cầu, khoá ``FOR SHARE`` ⇒ thu hồi / khoá tài khoản / đổi vai chen giữa hai lần
  bấm thì lần bấm sau bị chặn (T17). Không đạt ⇒ 404.

Thứ tự khoá (cùng chiều K4 / PR-B): dòng ``user`` theo id TĂNG qua ``user_deletion_policy.lock_users_in_id_order`` TRƯỚC
mọi câu ghi → dòng quyền. Gán: người được gán ``FOR NO KEY UPDATE`` (đọc vai / trạng thái dưới khoá; hai lần gán cùng
người, gán ‖ đổi vai / khoá tài khoản xếp hàng) + Admin bấm ``FOR KEY SHARE`` (khoá ngoại ``granted_by_user_id`` + nhật ký).
Thu hồi tay: Admin bấm ``FOR KEY SHARE`` (khoá ngoại ``revoked_by_user_id`` + nhật ký) → dòng quyền ``FOR UPDATE``.

Dịch vụ thuần: không import FastAPI, ném lỗi miền, chỉ ``flush`` (router commit). Log chỉ id — không họ tên.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.repositories import review_secretary_repository as repo
from app.services.document_transition import RequestMeta
from app.utils.exceptions import ConflictError, ResourceNotFoundError, ValidationError

log = structlog.get_logger(__name__)

GRANT_ENTITY_TYPE = "admission_review_secretary_grant"

#: Vai được GÁN Thư ký Hội đồng (thiết kế GĐ2-C §4). Đổi tập này ⇒ đổi luôn luật tự thu hồi (:func:`auto_revoke_reason`),
#: cổng (:func:`require_secretary_access`) và danh sách ứng viên (:func:`list_candidates`) — cả bốn đọc ĐÚNG hằng này.
SECRETARY_ELIGIBLE_ROLES = frozenset({UserRole.MANAGER.value, UserRole.OFFICER.value})
#: Vai LUÔN là Thư ký, không qua bảng quyền gán (owner 22-11 câu 1). Không được gán (``create_grant`` từ chối).
ALWAYS_SECRETARY_ROLE = UserRole.ADMIN.value
#: Trần số ứng viên một lần tìm (ô tìm của màn hình gán).
CANDIDATE_LIMIT_MAX = 50

#: Thân 404 của cổng Thư ký (không có quyền gán / quyền vừa bị thu hồi) — khuôn ``deps.CROSS_REVIEW_NOT_FOUND_DETAIL``.
NOT_GRANTED_DETAIL = "Không tìm thấy"

# ── Mã lý do (``reason_code``) — khuôn hợp đồng API GĐ2-B §1.3 ───────────────────────────────────────────────────────────
REASON_REQUIRED = "review_secretary_reason_required"
GRANTEE_NOT_ELIGIBLE = "review_secretary_grantee_not_eligible"
ALREADY_ACTIVE = "review_secretary_already_active"
GRANT_NOT_FOUND = "review_secretary_grant_not_found"
GRANT_ALREADY_REVOKED = "review_secretary_grant_already_revoked"

MESSAGES: Dict[str, str] = {
    REASON_REQUIRED: "Phải ghi lý do.",
    GRANTEE_NOT_ELIGIBLE: "Người được gán phải là Quản lý hoặc Cán bộ đang hoạt động.",
    ALREADY_ACTIVE: "Người này đang là Thư ký Hội đồng — thu hồi quyền cũ trước nếu muốn gán lại.",
    GRANT_NOT_FOUND: "Không tìm thấy quyền Thư ký Hội đồng.",
    GRANT_ALREADY_REVOKED: "Quyền này đã bị thu hồi.",
}


class ReviewSecretaryValidationError(ValidationError):
    """400 — ``error_code = "VALIDATION_ERROR"`` + ``reason_code``."""

    def __init__(self, reason_code: str):
        super().__init__(detail=MESSAGES[reason_code], public_payload={"reason_code": reason_code})
        self.reason_code = reason_code


class ReviewSecretaryConflict(ConflictError):
    """409 — ``error_code = reason_code`` viết hoa; payload chỉ id."""

    def __init__(self, reason_code: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(detail=MESSAGES[reason_code], public_payload={"reason_code": reason_code, **(payload or {})})
        self.reason_code = reason_code
        self.error_code = reason_code.upper()


class ReviewSecretaryGrantNotFound(ResourceNotFoundError):
    """404 của route Admin thu hồi — mã quyền không tồn tại."""

    def __init__(self):
        super().__init__(detail=MESSAGES[GRANT_NOT_FOUND], public_payload={"reason_code": GRANT_NOT_FOUND})


class ReviewSecretaryNotGranted(ResourceNotFoundError):
    """404 của CỔNG Thư ký — không có quyền còn hiệu lực (kể cả khi phát hiện DƯỚI khoá: vừa bị thu hồi). Thân cố định,
    không ``reason_code``: route lần xét không lộ lần xét có tồn tại hay không (thiết kế §4)."""

    detail = NOT_GRANTED_DETAIL
    error_code = "RESOURCE_NOT_FOUND"


def _role_code(role: Any) -> str:
    return str(getattr(role, "value", role))


def is_eligible_role(role: Any) -> bool:
    return _role_code(role) in SECRETARY_ELIGIBLE_ROLES


def _summary_view(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    uid, username, full_name, role, status = row
    return {"id": uid, "username": username, "full_name": full_name, "role": _role_code(role), "status": status}


def _grant_view(grant: models.AdmissionReviewSecretaryGrant, user_row: Optional[Any]) -> Dict[str, Any]:
    return {
        "id": grant.id,
        "user_id": grant.user_id,
        "user": _summary_view(user_row),
        "granted_by_user_id": grant.granted_by_user_id,
        "granted_at": grant.granted_at,
        "reason": grant.reason,
        "revoked_at": grant.revoked_at,
        "revoked_by_user_id": grant.revoked_by_user_id,
        "revoke_reason": grant.revoke_reason,
        "is_active": grant.revoked_at is None,
    }


# ---------------------------------------------------------------------------------------------------------------------
# Admin gán / thu hồi / liệt kê
# ---------------------------------------------------------------------------------------------------------------------
async def create_grant(
    db: AsyncSession, *, admin_id: int, user_id: int, reason: str, request_meta: Optional[RequestMeta] = None
) -> Dict[str, Any]:
    from app.services.audit_service import log_audit
    from app.services.user_deletion_policy import lock_users_in_id_order

    meta = request_meta or RequestMeta()
    reason = (reason or "").strip()
    if not reason:
        raise ReviewSecretaryValidationError(REASON_REQUIRED)
    # Khoá TRƯỚC mọi câu ghi, theo id TĂNG: người được gán FOR NO KEY UPDATE (vai / trạng thái đọc DƯỚI khoá, giữ tới
    # commit — đổi vai / khoá tài khoản (``revoke_grants_on_account_change``) và lần gán thứ hai cho cùng người phải CHỜ),
    # Admin bấm FOR KEY SHARE (khoá ngoại ``granted_by_user_id`` + nhật ký). Cùng chiều K4 ⇒ không vòng chờ với xoá lô.
    locked = await lock_users_in_id_order(db, target_ids=[user_id], referenced_ids=[admin_id])
    target = locked.get(user_id)
    if target is None or not is_eligible_role(target.role) or target.status != "active":
        raise ReviewSecretaryValidationError(GRANTEE_NOT_ELIGIBLE)
    existing = await repo.active_grant_for_user(db, user_id)
    if existing is not None:
        raise ReviewSecretaryConflict(ALREADY_ACTIVE, {"grant_id": existing.id})
    now = await repo.db_clock(db)
    grant = models.AdmissionReviewSecretaryGrant(
        user_id=user_id, granted_by_user_id=admin_id, granted_at=now, reason=reason
    )
    db.add(grant)
    await db.flush()
    await log_audit(
        db,
        GRANT_ENTITY_TYPE,
        grant.id,
        "granted",
        actor_user_id=admin_id,
        new_value={"user_id": user_id},
        reason=reason,
        source="api",
        ip_address=meta.ip_address,
        user_agent=meta.user_agent or None,  # cột tự cắt theo độ dài (TruncatedString, PR-D F12)
    )
    log.info("review_secretary_granted", grant_id=grant.id, user_id=user_id)
    return _grant_view(grant, await repo.user_summary(db, user_id))


async def _write_revocations(
    db: AsyncSession,
    grants: Sequence[models.AdmissionReviewSecretaryGrant],
    *,
    actor_id: int,
    reason: str,
    meta: RequestMeta,
) -> None:
    """MỘT khuôn ghi thu hồi (Admin thu hồi tay + tự thu hồi): ``revoked_at`` = đồng hồ CSDL, ``revoked_by_user_id`` = người
    thao tác, ``revoke_reason``; mỗi quyền MỘT dòng ``entity_audit_log`` ``revoked``. Dòng quyền phải ĐÃ khoá ``FOR UPDATE``
    và chưa thu hồi (trigger CSDL chặn ghi thu hồi lần hai). Không commit; lỗi ⇒ người gọi không commit ⇒ rollback cả."""
    from app.services.audit_service import log_audit

    now = await repo.db_clock(db)
    for grant in grants:
        grant.revoked_at = now
        grant.revoked_by_user_id = actor_id
        grant.revoke_reason = reason
    await db.flush()
    for grant in grants:
        await log_audit(
            db,
            GRANT_ENTITY_TYPE,
            grant.id,
            "revoked",
            actor_user_id=actor_id,
            old_value={"revoked_at": None},
            new_value={"revoked_at": now},
            reason=reason,
            source="api",
            ip_address=meta.ip_address,
            user_agent=meta.user_agent or None,
        )


async def revoke_grant(
    db: AsyncSession, *, admin_id: int, grant_id: int, reason: str, request_meta: Optional[RequestMeta] = None
) -> Dict[str, Any]:
    from app.services.user_deletion_policy import lock_users_in_id_order

    meta = request_meta or RequestMeta()
    reason = (reason or "").strip()
    if not reason:
        raise ReviewSecretaryValidationError(REASON_REQUIRED)
    # Người → quyền: Admin bấm FOR KEY SHARE (khoá ngoại ``revoked_by_user_id`` + nhật ký) TRƯỚC dòng quyền — không lấy khoá
    # dòng ``user`` nào khi đã giữ dòng quyền.
    await lock_users_in_id_order(db, target_ids=[], referenced_ids=[admin_id])
    grant = await repo.lock_grant_for_update(db, grant_id)
    if grant is None:
        raise ReviewSecretaryGrantNotFound()
    if grant.revoked_at is not None:
        raise ReviewSecretaryConflict(GRANT_ALREADY_REVOKED, {"grant_id": grant.id})
    await _write_revocations(db, [grant], actor_id=admin_id, reason=reason, meta=meta)
    log.info("review_secretary_revoked", grant_id=grant.id)
    return _grant_view(grant, await repo.user_summary(db, grant.user_id))


async def list_grants(db: AsyncSession, *, active: Optional[bool], user_id: Optional[int]) -> List[Dict[str, Any]]:
    return [_grant_view(g, row) for g, row in await repo.list_grants(db, active=active, user_id=user_id)]


# ---------------------------------------------------------------------------------------------------------------------
# Tự thu hồi khi tài khoản bị khoá / đổi vai (cùng luật, cùng chỗ với quyền duyệt chéo GĐ1b — owner C1 22-11)
# ---------------------------------------------------------------------------------------------------------------------
def auto_revoke_reason(
    *,
    old_role: Any,
    old_status: Optional[str],
    new_role: Any = None,
    new_status: Optional[str] = None,
) -> Optional[str]:
    """MỘT vị từ "thay đổi tài khoản này có kéo theo tự thu hồi quyền Thư ký không" + câu lý do (``None`` = không). Cùng luật
    và CÙNG câu với quyền duyệt chéo (``document_cross_review_service.auto_revoke_reason`` — owner 21-11 câu 1, 2); chỉ khác
    tập vai được giữ quyền (:data:`SECRETARY_ELIGIBLE_ROLES` thay cho riêng Cán bộ):

    - trạng thái từ ``active`` sang BẤT KỲ trạng thái khác ⇒ "Tự thu hồi: tài khoản bị khoá";
    - vai từ một vai được gán sang vai KHÔNG được gán ⇒ "Tự thu hồi: tài khoản đổi vai từ <cũ> sang <mới>" (Quản lý ↔ Cán
      bộ vẫn giữ quyền);
    - cả hai ⇒ ghi cả hai câu (nối "; ").

    ``new_role`` / ``new_status`` = ``None`` ⇒ không đổi. Giá trị cũ phải đọc DƯỚI khoá dòng ``user``."""
    from app.services.document_cross_review_service import AUTO_REVOKE_LOCKED, AUTO_REVOKE_PREFIX, _role_label

    parts: List[str] = []
    if new_status is not None and old_status == "active" and new_status != "active":
        parts.append(AUTO_REVOKE_PREFIX + AUTO_REVOKE_LOCKED)
    if new_role is not None and is_eligible_role(old_role) and not is_eligible_role(new_role):
        parts.append(AUTO_REVOKE_PREFIX + f"tài khoản đổi vai từ {_role_label(old_role)} sang {_role_label(new_role)}")
    return "; ".join(parts) if parts else None


async def revoke_on_account_change(
    db: AsyncSession,
    *,
    user_id: int,
    actor_id: int,
    reason: str,
    request_meta: Optional[RequestMeta] = None,
) -> List[int]:
    """Thu hồi MỌI quyền Thư ký chưa thu hồi của ``user_id`` (``FOR UPDATE``, id tăng) + nhật ký, cùng giao dịch người gọi.
    CHỈ gọi từ ``revoke_grants_on_account_change`` (tầng chủ sở hữu "đổi vai / khoá tài khoản ⇒ tự thu hồi"), SAU khi dòng
    ``user`` đã khoá ``FOR NO KEY UPDATE`` và ``reason`` đã tính bằng :func:`auto_revoke_reason` trên giá trị đọc dưới khoá.
    Trả id các quyền vừa thu hồi."""
    grants = await repo.lock_active_grants_of_user_for_update(db, user_id)
    if grants:
        await _write_revocations(db, grants, actor_id=actor_id, reason=reason, meta=request_meta or RequestMeta())
        log.info("review_secretary_auto_revoked", user_id=user_id, grant_ids=[g.id for g in grants])
    return [g.id for g in grants]


# ---------------------------------------------------------------------------------------------------------------------
# Cổng Thư ký (``deps.require_review_secretary``)
# ---------------------------------------------------------------------------------------------------------------------
async def require_secretary_access(db: AsyncSession, *, user: Any) -> Optional[models.AdmissionReviewSecretaryGrant]:
    """Người gọi có quyền Thư ký không — quyết TRONG giao dịch ``db`` (phiên của chính yêu cầu; FastAPI dùng chung
    ``database.get_db`` cho cổng và route). Không đạt ⇒ :class:`ReviewSecretaryNotGranted` (404).

    1. Dòng ``user`` của người gọi ``FOR SHARE`` (``document_bulk_repository.lock_user_role_share``): vai + trạng thái đọc DƯỚI
       khoá, giữ tới commit. Khoá tài khoản / đổi vai (``FOR NO KEY UPDATE``) chen giữa thì hoặc CHỜ lần bấm này commit, hoặc
       lần bấm CHỜ nó rồi thấy giá trị mới — không quyết bằng bản đọc lúc xác thực. Dòng không còn / không ``active`` ⇒ 404.
    2. Vai :data:`ALWAYS_SECRETARY_ROLE` (Admin) ⇒ ĐẠT, không đọc bảng quyền, trả ``None`` (owner 22-11 câu 1). Luật "người đề
       xuất ≠ người khoá" KHÔNG nằm ở cổng này và vẫn áp cho Admin (C4 / C5b).
    3. Vai ngoài :data:`SECRETARY_ELIGIBLE_ROLES` ⇒ 404.
    4. Quyền gán còn hiệu lực ``FOR SHARE`` (thứ tự người → quyền, cùng chiều tự thu hồi). Không có ⇒ 404; ``revoked_at`` kiểm
       lại trên giá trị đọc DƯỚI khoá. Trả dòng quyền."""
    from app.repositories import document_bulk_repository as bulk_repo

    row = await bulk_repo.lock_user_role_share(db, user.id)
    if row is None or row.status != "active":
        raise ReviewSecretaryNotGranted()
    role = _role_code(row.role)
    if role == ALWAYS_SECRETARY_ROLE:
        return None
    if role not in SECRETARY_ELIGIBLE_ROLES:
        raise ReviewSecretaryNotGranted()
    grant = await repo.lock_active_grant_share(db, user.id)
    if grant is None or grant.revoked_at is not None:
        raise ReviewSecretaryNotGranted()
    return grant


# ---------------------------------------------------------------------------------------------------------------------
# Ứng viên cho ô tìm của màn hình gán (owner 22-11 câu 3)
# ---------------------------------------------------------------------------------------------------------------------
async def list_candidates(db: AsyncSession, *, q: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Quản lý / Cán bộ ĐANG HOẠT ĐỘNG, CHƯA có quyền Thư ký còn hiệu lực, khớp ``q`` theo họ tên (bỏ dấu) / tên đăng nhập /
    email — tối đa ``limit`` (≤ :data:`CANDIDATE_LIMIT_MAX`). Trả TỐI THIỂU: id, tên đăng nhập, họ tên, email, vai. Chỉ là
    danh sách GỢI Ý: lúc gán máy chủ vẫn kiểm vai + trạng thái dưới khoá (:func:`create_grant`)."""
    rows = await repo.search_candidates(
        db, roles=sorted(SECRETARY_ELIGIBLE_ROLES), q=q, limit=min(int(limit), CANDIDATE_LIMIT_MAX)
    )
    return [
        {"id": r[0], "username": r[1], "full_name": r[2], "email": r[3], "role": _role_code(r[4])} for r in rows
    ]
