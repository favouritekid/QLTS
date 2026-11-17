"""GĐ1b — ``transition_document``: nơi DUY NHẤT đổi trạng thái giấy thường (``category = 'path'``) theo thao tác duyệt / từ
chối / Đặt lại (đặc tả GĐ1b bản 3.6 §4, sha256 ``9ef02da2…4e2e``).

Nhận ID, không nhận đối tượng nạp sẵn: mọi thứ cần kiểm được ĐỌC LẠI SAU KHI LẤY KHOÁ (§4.5), theo thứ tự chung:

    (dòng lô — người gọi lô giữ) → quyền chéo FOR SHARE → hồ sơ FOR UPDATE → lead FOR SHARE
    → dòng giấy FOR UPDATE → người thao tác FOR SHARE (cuối cùng)

Luật quyết định: :mod:`app.services.document_review_rules` (MỘT nguồn với cờ máy chủ §4.7). Ghi có điều kiện
``WHERE id AND row_version`` — đúng 1 hàng. Mỗi thao tác đúng MỘT dòng ``document_audit_log`` cùng giao dịch; duyệt giấy có
tệp ghi thêm MỘT dòng ``document_evidence_file`` (sha256 tính dưới khoá; tệp không còn ⇒ ``file_missing_on_disk``, không duyệt).
Hàm này KHÔNG commit (dịch vụ chỉ flush — router / lô commit).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.services import document_review_rules as rules
from app.utils.exceptions import (
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationError,
)

log = structlog.get_logger(__name__)

VERSION_CHANGED = "version_changed"
FILE_MISSING_ON_DISK = "file_missing_on_disk"
ACTOR_NOT_AUTHORIZED = "actor_not_authorized"
REASON_REQUIRED = "reason_required"

VERIFIED_FORMATS = ("original", "certified_copy", "photo")

#: Câu báo cho người dùng (tiếng Việt) theo mã lý do (tiếng Anh).
MESSAGES: Dict[str, str] = {
    VERSION_CHANGED: (
        "Giấy này đã được xử lý ở lô khác hoặc thao tác khác sau khi bạn xem — hãy tải lại / xem trước lại"
    ),
    rules.OWN_SUBMISSION: "Người nhận / người tải giấy không tự duyệt, từ chối hay Đặt lại giấy đã duyệt của mình",
    rules.UNKNOWN_SUBMITTER: (
        "Không rõ người nhận giấy — nút lẻ cần cam kết kèm lý do; giấy này không vào lô / duyệt chéo"
    ),
    rules.MISSING_FORMAT: "Chưa ghi hình thức lúc nhận — duyệt từng giấy",
    rules.OUTSIDE_CONFIG: "Giấy ngoài cấu hình hiện tại — chỉ Quản lý / Admin Đặt lại được",
    rules.NOT_PENDING: "Hồ sơ hoặc giấy không ở trạng thái chờ xét",
    rules.CROSS_NO_RESET: "Duyệt chéo không có thao tác Đặt lại",
    rules.NOT_RESETTABLE: "Giấy chưa nộp — không có gì để Đặt lại",
    FILE_MISSING_ON_DISK: "Tệp của giấy không còn trên ổ lưu trữ — không duyệt được",
    ACTOR_NOT_AUTHORIZED: "Người thao tác không còn quyền thực hiện thao tác này",
}


class DocumentTransitionConflict(ConflictError):
    """409 — thao tác bị từ chối vì trạng thái / luật nghiệp vụ; ``reason_code`` là mã lý do của mục lô."""

    def __init__(self, reason_code: str, detail: Optional[str] = None):
        super().__init__(detail=detail or MESSAGES.get(reason_code, reason_code), public_payload={"reason_code": reason_code})
        self.reason_code = reason_code
        self.error_code = reason_code.upper()


@dataclass(frozen=True)
class RequestMeta:
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


async def _noop_finalize(committed: bool) -> None:
    return None


@dataclass
class TransitionResult:
    document_row_id: int
    profile_id: int
    action: str
    new_status: str
    row_version: int
    audit_id: int
    evidence_id: Optional[int] = None
    #: Gọi SAU commit (``True``) / sau rollback (``False``). Đặt lại: xoá tệp cũ trừ khi là bằng chứng.
    finalize: Callable[[bool], Awaitable[None]] = field(default=_noop_finalize)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolved_file(profile_id: int, file_path: Optional[str]) -> Optional[str]:
    """Đường tuyệt đối của tệp giấy nếu nằm đúng thư mục hồ sơ VÀ đang tồn tại; ngược lại None."""
    if not file_path:
        return None
    from app.services.admission_service import _resolve_under

    abs_path = _resolve_under(f"uploads/admissions/{profile_id}", file_path)
    if abs_path is None or not os.path.isfile(abs_path):
        return None
    return abs_path


async def _lock_grant(db: AsyncSession, grant_id: int, actor_id: int) -> models.DocumentCrossReviewGrant:
    """Dòng quyền chéo FOR SHARE; hạn so với ``clock_timestamp()`` SAU khi có khoá (§6, §9: giao dịch bắt đầu trước hạn mà
    chờ khoá qua hạn vẫn bị chặn)."""
    row = (
        await db.execute(
            select(
                models.DocumentCrossReviewGrant,
                (models.DocumentCrossReviewGrant.expires_at > text("clock_timestamp()")).label("still_valid"),
            )
            .where(models.DocumentCrossReviewGrant.id == grant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    grant, still_valid = row
    if grant.grantee_user_id != actor_id or grant.revoked_at is not None or not still_valid:
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    return grant


async def transition_document(
    db: AsyncSession,
    *,
    profile_id: int,
    document_row_id: int,
    action: str,
    actor_id: int,
    via: str,
    expected_row_version: int,
    batch_id: Optional[UUID] = None,
    grant_id: Optional[int] = None,
    verified_format: Optional[str] = None,
    reason: Optional[str] = None,
    unknown_submitter_ack: bool = False,
    request_meta: Optional[RequestMeta] = None,
) -> TransitionResult:
    from app.services.admission_document_policy import DocumentActionPolicy
    from app.services.admission_service import _lock_profile_for_document_write
    from app.services.document_audit_service import log_document_action

    if via not in rules.VIAS:
        raise ValueError(via)
    meta = request_meta or RequestMeta()
    reason = (reason or "").strip() or None

    # 1. Quyền chéo (nếu có).
    grant = None
    if via == rules.VIA_CROSS:
        if grant_id is None:
            raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
        grant = await _lock_grant(db, grant_id, actor_id)

    # 2. Hồ sơ FOR UPDATE (+ làm mới các dòng giấy đã nạp).
    profile = await _lock_profile_for_document_write(db, profile_id)

    # 3. Lead FOR SHARE — đơn vị, người tư vấn, chưa xoá mềm.
    lead = (
        await db.execute(
            select(models.Lead)
            .where(models.Lead.id == profile.lead_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if lead is None or lead.deleted_at is not None:
        raise ResourceNotFoundError("Admission profile not found")
    if grant is not None and lead.unit_id != grant.unit_id:
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)

    # 4. Dòng giấy FOR UPDATE.
    doc = (
        await db.execute(
            select(models.ProfileDocument)
            .where(
                models.ProfileDocument.id == document_row_id,
                models.ProfileDocument.profile_id == profile_id,
            )
            .options(selectinload(models.ProfileDocument.document_type))
            .with_for_update(of=models.ProfileDocument)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if doc is None or doc.category != "path" or doc.document_type is None:
        raise ResourceNotFoundError("Document not found")

    # 5. Người thao tác FOR SHARE — CUỐI CÙNG.
    actor = (
        await db.execute(
            select(models.User)
            .where(models.User.id == actor_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if actor is None or actor.status != "active":
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    if grant is not None and lead.assigned_officer_id == actor_id:
        # §4.5 / §9: lead đổi người tư vấn sang CHÍNH cán bộ chéo giữa chừng ⇒ không duyệt chéo hồ sơ mình phụ trách.
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)

    # 6a. Phiên bản dòng — TRƯỚC luật quyết định (§5.9, §9 "hai tab"): người gửi một bản đã cũ (lô / tab khác đã xử lý
    #     giấy) nhận `version_changed` để làm mới, KHÔNG nhận lỗi của trạng thái mới mà họ chưa thấy (`not_pending` ở lô;
    #     `not_permitted` ⇒ 404 ở nút lẻ, vì `policy.authorize` của nút lẻ phụ thuộc trạng thái). Không lộ gì: tới được đây
    #     là đã qua cổng phạm vi (`deps`) hoặc quyền chéo dưới khoá, và `row_version` có sẵn trong phản hồi họ đọc được.
    if doc.row_version != expected_row_version:
        raise DocumentTransitionConflict(VERSION_CHANGED)

    # 6b. Quyết định — trạng thái ĐỌC LẠI dưới khoá, cùng luật với cờ máy chủ.
    doc_code = doc.document_type.code
    is_extra, requires_upload = rules.config_facts(profile.applied_rules, doc_code, has_file=bool(doc.file_path))
    facts = rules.DocFacts.from_row(doc, requires_upload=requires_upload, is_extra=is_extra)
    policy = DocumentActionPolicy.for_(profile, actor)
    grant_actions = frozenset()
    if grant is not None:
        grant_actions = frozenset(
            a for a, ok in ((rules.ACTION_VERIFY, grant.allow_verify), (rules.ACTION_REJECT, grant.allow_reject)) if ok
        )
    decision = rules.decide(
        action, via, policy=policy, actor_id=actor_id, profile_status=profile.status, doc=facts,
        grant_actions=grant_actions,
    )
    if not decision.allowed:
        if decision.block_reason == rules.NOT_PERMITTED:
            raise PermissionDeniedError(f"Action '{action}' not permitted on document '{doc_code}'")
        raise DocumentTransitionConflict(decision.block_reason)
    if decision.requires_ack and not (unknown_submitter_ack and reason):
        raise DocumentTransitionConflict(rules.UNKNOWN_SUBMITTER)
    if action in (rules.ACTION_RESET, rules.ACTION_REJECT) and not reason:
        raise ValidationError("Lý do là bắt buộc")

    now = datetime.now(timezone.utc)
    old_status = doc.status
    old_file_path = doc.file_path
    file_sha = None
    values: Dict[str, Any]
    extra: Dict[str, Any] = {
        "via": "extra_cleanup" if (is_extra and action == rules.ACTION_RESET) else via,
        "batch_id": str(batch_id) if batch_id else None,
        "grant_id": grant_id,
        "reason": reason,
        "unknown_submitter_ack": bool(decision.requires_ack and unknown_submitter_ack),
    }

    if action == rules.ACTION_VERIFY:
        if via == rules.VIA_SINGLE:
            fmt = verified_format or doc.actual_submission_format
        else:
            fmt = doc.actual_submission_format  # §4.6: lô / chéo duyệt ĐÚNG hình thức lúc nhận
        if not fmt:
            raise DocumentTransitionConflict(rules.MISSING_FORMAT)
        if fmt not in VERIFIED_FORMATS:
            raise ValidationError("Hình thức không hợp lệ")
        if facts.has_file:
            abs_path = _resolved_file(profile_id, doc.file_path)
            if abs_path is None:
                raise DocumentTransitionConflict(FILE_MISSING_ON_DISK)
            file_sha = _sha256_file(abs_path)
        values = {"status": "verified", "verified_format": fmt, "verified_at": now, "verified_by": actor_id}
        extra["declared_format"] = doc.actual_submission_format
    elif action == rules.ACTION_REJECT:
        values = {
            "status": "rejected",
            "rejection_reason": reason,
            "rejected_at": now,
            "rejected_by": actor_id,
            "graduation_proof_kind": None,
            "supplement_due_date": None,
        }
    else:  # reset
        abs_path = _resolved_file(profile_id, doc.file_path)
        extra["before"] = {
            "status": old_status,
            "verified_by": doc.verified_by,
            "verified_at": doc.verified_at.isoformat() if doc.verified_at else None,
            "verified_format": doc.verified_format,
            "receiver_id": facts.receiver_id,
            "receiver_unknown": facts.receiver_unknown,
            "actual_submission_format": doc.actual_submission_format,
            "file_path": doc.file_path,
            "file_sha256": _sha256_file(abs_path) if abs_path else None,
        }
        values = {
            "status": "missing",
            "file_path": None,
            "actual_submission_format": None,
            "verified_format": None,
            "uploaded_at": None,
            "verified_at": None,
            "verified_by": None,
            "paper_submitted_at": None,
            "paper_submitted_by": None,
            "rejected_at": None,
            "rejected_by": None,
            "rejection_reason": None,
            "graduation_proof_kind": None,
            "supplement_due_date": None,
            "uploaded_by": None,
            "uploaded_by_unknown": False,
            "paper_submitted_by_unknown": False,
        }
    extra["file_sha256"] = file_sha
    values["updated_at"] = now

    # 8. Ghi có điều kiện — đúng 1 hàng (trigger tăng row_version).
    res = await db.execute(
        update(models.ProfileDocument)
        .where(
            models.ProfileDocument.id == document_row_id,
            models.ProfileDocument.row_version == expected_row_version,
        )
        .values(**values)
        .returning(models.ProfileDocument.row_version)
        .execution_options(synchronize_session=False)
    )
    new_version = res.scalar_one_or_none()
    if new_version is None:
        raise DocumentTransitionConflict(VERSION_CHANGED)
    await db.execute(
        select(models.ProfileDocument)
        .where(models.ProfileDocument.id == document_row_id)
        .options(selectinload(models.ProfileDocument.document_type))
        .execution_options(populate_existing=True)
    )

    # 9. Nhật ký — đúng một dòng, old_status thật.
    audit = await log_document_action(
        db=db,
        profile_document_id=document_row_id,
        action={"verify": "verified", "reject": "rejected", "reset": "reset"}[action],
        actor_user_id=actor_id,
        old_status=old_status,
        new_status=values["status"],
        old_file_path=old_file_path if action == rules.ACTION_RESET else None,
        reason=reason,
        declared_format=extra.get("declared_format"),
        verified_format=values.get("verified_format"),
        extra_data=extra,
        ip_address=meta.ip_address,
        user_agent=meta.user_agent,
    )

    # 10. Bằng chứng (duyệt giấy có tệp).
    evidence_id = None
    if action == rules.ACTION_VERIFY and file_sha is not None:
        ev = models.DocumentEvidenceFile(
            profile_document_id=document_row_id,
            verification_audit_id=audit.id,
            profile_id=profile_id,
            file_path=old_file_path,
            sha256=file_sha,
            verified_by_user_id=actor_id,
            verified_at=now,
        )
        db.add(ev)
        await db.flush()
        evidence_id = ev.id

    # 11. Đặt lại: tệp cũ xoá SAU commit, trừ khi là bằng chứng (danh sách chốt TRONG giao dịch).
    finalize = _noop_finalize
    if action == rules.ACTION_RESET and old_file_path:
        from app.services.document_file_guard import delete_document_file_unless_evidence, protected_evidence_paths

        protected = await protected_evidence_paths(db, paths=[old_file_path])

        async def finalize(committed: bool) -> None:  # noqa: F811
            if committed:
                delete_document_file_unless_evidence(old_file_path, protected, profile_id=profile_id)

    log.info(
        "document transition",
        profile_id=profile_id,
        document_row_id=document_row_id,
        action=action,
        via=via,
        actor_id=actor_id,
        old_status=old_status,
        new_status=values["status"],
    )
    return TransitionResult(
        document_row_id=document_row_id,
        profile_id=profile_id,
        action=action,
        new_status=values["status"],
        row_version=new_version,
        audit_id=audit.id,
        evidence_id=evidence_id,
        finalize=finalize,
    )
