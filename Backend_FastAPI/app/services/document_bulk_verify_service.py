"""GĐ1b — lô duyệt giấy (Quản lý / Admin, ``review_mode = batch``) và lô duyệt chéo (``review_mode = cross``).

Đặc tả ``DAC-TA-GD1B-DUYET-GIAY-NHANH-BAN3-6-2026-11-17.md`` (sha256 ``9ef02da2…4e2e``) §5.2–§5.8; hợp đồng API GĐ1b bản 4
(sha256 ``45b718f6…adad``) §2.1. Mọi bước theo ĐÚNG thứ tự của đặc tả:

- ``preview_batch`` (§5.2): khoá theo người ``(ns_preview, user_id)`` → dọn bản xem trước của CHÍNH người bấm → đếm lại
  (≥ 3 ⇒ 409 ``TOO_MANY_PREVIEWS``) → tính tập giấy (luật ``document_review_rules.decide``, một nguồn với cổng ghi) → giới hạn
  (422, không tự cắt) → chèn dòng lô ``previewed`` + dòng mục. Router commit.
- ``execute_batch`` (§5.3–§5.5): người tạo đã được kiểm TRƯỚC khoá (deps) → ``pg_try_advisory_lock`` trên kết nối L riêng →
  một giao dịch đổi ``processing`` (kiểm lại người tạo dưới khoá) → MỖI HỒ SƠ MỘT GIAO DỊCH (khoá dòng lô trước, kiểm sống
  khoá, kiểm lại quyền người bấm, ``transition_document`` từng giấy trong SAVEPOINT, dòng kết quả cùng giao dịch) → kết thúc
  rồi MỚI nhả khoá (``finally``, shield + 5 s).
- ``get_batch`` (§5.6), ``finalize_batch`` (§5.7 — chỉ kết luận ``BATCH_NOT_STARTED`` khi ĐÃ giữ khoá), ``list_batches``
  (§5.8, cửa sổ 30 ngày, con trỏ).

Ngoại lệ có chủ ý với luật "router commit": người chạy lô commit TỪNG hồ sơ (đặc tả §1 "mỗi hồ sơ một giao dịch"); callback
sau commit (``TransitionResult.finalize``) chỉ chạy cho hồ sơ ĐÃ commit. Dịch vụ không import FastAPI.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.advisory_lock_keys import BULK_VERIFY_BATCH_NS, BULK_VERIFY_PREVIEW_NS, batch_lock_key
from app.core.constants import UserRole
from app.repositories import document_bulk_repository as repo
from app.services import document_review_rules as rules
from app.services import document_transition
from app.services.document_transition import DocumentTransitionConflict, RequestMeta
from app.utils.exceptions import (
    BaseAppException,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)

log = structlog.get_logger(__name__)

# =====================================================================================================================
# Tham số — MỘT chỗ. Hai tham số CHƯA ĐO (K1 = N, ``lock_timeout``) để ``None``: không có mặc định "cho chạy" (§13.3) —
# thiếu ⇒ 503 fail-closed; ``tests/unit/test_gd1b_lo_khoa_tu_van.py::test_tham_so_k1_da_do`` ĐỎ cho tới khi Claude điền số
# đo V3 (§16).
# =====================================================================================================================
BULK_VERIFY_MAX_PROFILES = 100
BULK_VERIFY_MAX_DOCUMENTS: Optional[int] = None
BULK_VERIFY_LOCK_TIMEOUT_MS: Optional[int] = None
BULK_VERIFY_PREVIEW_TTL = timedelta(minutes=30)
BULK_VERIFY_MAX_LIVE_PREVIEWS = 3
BULK_VERIFY_LIST_WINDOW_DAYS = 30
BULK_VERIFY_LIST_PAGE_SIZE = 20

REVIEW_MODE_BATCH = "batch"
REVIEW_MODE_CROSS = "cross"
TERMINAL_STATUSES = ("completed", "stopped", "interrupted")

# Mã lý do mục lô (ngoài mã của ``transition_document``).
PROFILE_OVER_DOCUMENT_CAP = "profile_over_document_cap"
PROFILE_BUSY = "profile_busy"
SYSTEM_ERROR = "system_error"
ACTOR_NOT_AUTHORIZED = document_transition.ACTOR_NOT_AUTHORIZED

ITEM_MESSAGES: Dict[str, str] = {
    **document_transition.MESSAGES,
    rules.NOT_PERMITTED: "Không có quyền thực hiện thao tác này trên giấy",
    PROFILE_OVER_DOCUMENT_CAP: "Hồ sơ có quá nhiều giấy cho một lô — duyệt riêng hồ sơ này",
    PROFILE_BUSY: "Hồ sơ đang được thao tác khác giữ — giấy chưa được ghi, thử lại sau",
    SYSTEM_ERROR: "Lỗi hệ thống khi ghi hồ sơ này — giấy chưa được ghi; tra lại lô",
}
NOT_PROCESSED_MESSAGE = "Chưa xử lý — lô đã dừng hoặc bị gián đoạn"

BATCH_NOT_FOUND_DETAIL = "Không tìm thấy lô duyệt giấy"


# =====================================================================================================================
# Ngoại lệ miền
# =====================================================================================================================
class BatchNotFound(ResourceNotFoundError):
    """404 CÙNG THÂN cho: không có / không phải người tạo / không phải Admin (khi được xem) / mã không phải UUID v4."""

    detail = BATCH_NOT_FOUND_DETAIL
    error_code = "RESOURCE_NOT_FOUND"


class PreviewGone(ResourceNotFoundError):
    """404 ``PREVIEW_GONE`` — chỉ người tạo tới được bước này (§5.3 bước 2)."""

    detail = "Bản xem trước không còn — xem trước lại"
    error_code = "PREVIEW_GONE"


class BulkBatchConflict(ConflictError):
    def __init__(self, error_code: str, detail: str):
        super().__init__(detail=detail)
        self.error_code = error_code


class BulkVerifyUnprocessable(BaseAppException):
    """422 kèm số đếm (``public_payload``). KHÔNG kế thừa ``ValidationError`` (bộ xử lý của nó ép 400)."""

    status_code = 422

    def __init__(self, error_code: str, detail: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(detail=detail, public_payload=payload or {})
        self.error_code = error_code


class BulkVerifyNotConfigured(ServiceUnavailableError):
    detail = "Duyệt hàng loạt chưa được cấu hình tham số đo (K1 / lock_timeout) — chưa thể chạy"
    error_code = "BULK_VERIFY_NOT_CONFIGURED"


class BulkVerifyLockUnavailable(ServiceUnavailableError):
    detail = "Không kiểm được trạng thái khoá của lô — thử lại sau"
    error_code = "BULK_VERIFY_LOCK_UNAVAILABLE"


def _running() -> BulkBatchConflict:
    return BulkBatchConflict("BATCH_RUNNING", "Lô đang chạy — tra lô để xem kết quả")


# =====================================================================================================================
# Tiện ích
# =====================================================================================================================
def _require_max_documents() -> int:
    n = BULK_VERIFY_MAX_DOCUMENTS
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise BulkVerifyNotConfigured()
    return n


def _require_lock_timeout_ms() -> int:
    ms = BULK_VERIFY_LOCK_TIMEOUT_MS
    if not isinstance(ms, int) or isinstance(ms, bool) or ms < 1:
        raise BulkVerifyNotConfigured()
    return ms


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception as exc:  # noqa: BLE001 — kết nối có thể đã chết; phiên vẫn dùng lại được cho giao dịch sau
        log.warning("bulk_verify_rollback_failed", error_type=type(exc).__name__)


async def _commit_profile(db: AsyncSession) -> None:
    """Commit giao dịch của MỘT hồ sơ (điểm móc cho test: dừng giữa hai hồ sơ, bơm lỗi sau COMMIT)."""
    await db.commit()


async def _commit_step(db: AsyncSession) -> None:
    """Commit các giao dịch quản lý lô (bắt đầu / dừng / kết thúc)."""
    await db.commit()


def _msg(code: Optional[str]) -> Optional[str]:
    return None if code is None else ITEM_MESSAGES.get(code, code)


def _doc_rule_facts(profile: models.AdmissionProfile, doc: models.ProfileDocument) -> Tuple[str, bool, bool, rules.DocFacts]:
    """(mã giấy, ngoài cấu hình?, bắt buộc?, sự kiện cho ``decide``) — cùng cách tính với ``transition_document``
    (``requires_upload`` của giấy ngoài cấu hình suy từ việc có tệp)."""
    code = doc.document_type.code
    applied = profile.applied_rules or {}
    mandatory = set(applied.get("mandatory_docs", []) or [])
    # MỘT nguồn với ``transition_document`` + cờ phản hồi hồ sơ (bổ sung hợp đồng bản 5 A3).
    is_extra, requires_upload = rules.config_facts(applied, code, has_file=bool(doc.file_path))
    facts = rules.DocFacts.from_row(doc, requires_upload=requires_upload, is_extra=is_extra)
    return code, is_extra, (code in mandatory and not is_extra), facts


async def emit_bulk_verify_finished(user_id: int, batch_id: UUID) -> None:
    """Socket ``bulk_verify_finished {batch_id}`` tới người tạo — gọi SAU commit cuối (router gọi callback)."""
    try:
        from app.socket_manager import sio

        await sio.emit("bulk_verify_finished", {"batch_id": str(batch_id)}, room=f"user_room_{user_id}")
    except Exception as exc:  # noqa: BLE001 — thông báo thời gian thực không được làm hỏng kết quả đã commit
        log.warning("bulk_verify_finished_emit_failed", error_type=type(exc).__name__)


# =====================================================================================================================
# §5.2 Xem trước — TẠO lô
# =====================================================================================================================
async def preview_batch(
    db: AsyncSession,
    *,
    actor: models.User,
    profile_ids: Optional[Sequence[int]],
    filter_: Any,
    include_optional: bool,
    review_mode: str,
    grant_id: Optional[int] = None,
    request_meta: Optional[RequestMeta] = None,
) -> Dict[str, Any]:
    from app.services.admission_document_policy import DocumentActionPolicy
    from app.services.admission_service import _resolve_coordination_filters

    if review_mode not in (REVIEW_MODE_BATCH, REVIEW_MODE_CROSS):
        raise ValueError(review_mode)
    n_max = _require_max_documents()  # 503 TRƯỚC mọi khoá / ghi
    meta = request_meta or RequestMeta()
    actor_id, actor_role = actor.id, actor.role
    cross = review_mode == REVIEW_MODE_CROSS
    if profile_ids is not None and len(profile_ids) > BULK_VERIFY_MAX_PROFILES:
        raise BulkVerifyUnprocessable(
            "TOO_MANY_PROFILES",
            f"Quá {BULK_VERIFY_MAX_PROFILES} hồ sơ trong một lô — thu hẹp lựa chọn",
            {"profile_count": len(profile_ids), "limit": BULK_VERIFY_MAX_PROFILES},
        )

    grant = None
    if cross:
        from app.services.document_cross_review_service import require_grant_for_action

        grant = await require_grant_for_action(db, actor_id=actor_id, grant_id=grant_id, action=rules.ACTION_VERIFY)

    # Bước 0 — tuần tự hoá theo người dùng (tự nhả cuối giao dịch).
    await repo.lock_preview_user(db, BULK_VERIFY_PREVIEW_NS, actor_id)
    # Bước 1 — dọn bản xem trước của CHÍNH người bấm (còn ≤ 2).
    await repo.cleanup_previews(
        db, user_id=actor_id, ns=BULK_VERIFY_BATCH_NS, keep=BULK_VERIFY_MAX_LIVE_PREVIEWS - 1, key_of=batch_lock_key
    )
    # Bước 2 — đếm lại SAU khi dọn, vẫn dưới khoá bước 0.
    if await repo.count_live_previews(db, actor_id) >= BULK_VERIFY_MAX_LIVE_PREVIEWS:
        raise BulkBatchConflict("TOO_MANY_PREVIEWS", "Đang có lô chuẩn bị chạy — thử lại sau giây lát")

    # Bước 3 — chọn hồ sơ (phạm vi của người bấm) + tính tập giấy.
    if cross:
        selected = await repo.select_profile_ids(
            db, coord={"unit_id": grant.unit_id}, statuses=None, profile_ids=profile_ids
        )
    elif profile_ids is not None:
        selected = await repo.select_profile_ids(
            db, coord=_resolve_coordination_filters(actor), statuses=None, profile_ids=profile_ids
        )
    else:
        f = filter_
        wanted = f.statuses()
        statuses = sorted(rules.PENDING_PROFILE_STATUSES if not wanted else set(wanted) & rules.PENDING_PROFILE_STATUSES)
        coord = _resolve_coordination_filters(
            actor,
            officer_ids=f.officer_ids(),
            unit_id_param=f.unit_id,
            reviewer_ids=f.reviewer_ids(),
            unassigned=f.unassigned,
        )
        selected = await repo.select_profile_ids(
            db,
            coord=coord,
            statuses=statuses,
            search=f.search,
            major_ids=f.major_ids(),
            academic_year=f.academic_year,
            degree_level=f.degree_level,
            payment_status=f.payment_status,
            date_from=f.date_from,
            date_to=f.date_to,
        )
        if len(selected) > BULK_VERIFY_MAX_PROFILES:
            raise BulkVerifyUnprocessable(
                "TOO_MANY_PROFILES",
                f"Bộ lọc khớp quá {BULK_VERIFY_MAX_PROFILES} hồ sơ chờ xét — thu hẹp bộ lọc",
                {"profile_count": len(selected), "limit": BULK_VERIFY_MAX_PROFILES},
            )

    via = rules.VIA_CROSS if cross else rules.VIA_BATCH
    grant_actions = frozenset({rules.ACTION_VERIFY}) if cross else frozenset()
    items: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for profile in await repo.load_profiles_with_documents(db, selected):
        policy = DocumentActionPolicy.for_(profile, actor)
        lead = profile.__dict__.get("lead")
        prof_items: List[Dict[str, Any]] = []
        docs = sorted(
            (d for d in profile.documents if d.category == "path" and d.status in ("paper_submitted", "uploaded")),
            key=lambda d: d.id,
        )
        for doc in docs:
            if doc.document_type is None:
                continue
            code, is_extra, is_mandatory, facts = _doc_rule_facts(profile, doc)
            base = {"profile_id": profile.id, "document_row_id": doc.id, "document_type_code": code}
            if is_extra:
                excluded.append({**base, "reason_code": rules.OUTSIDE_CONFIG})
                continue
            if not is_mandatory and not include_optional:
                continue
            if cross and lead is not None and lead.assigned_officer_id == actor_id:
                excluded.append({**base, "reason_code": ACTOR_NOT_AUTHORIZED})
                continue
            decision = rules.decide(
                rules.ACTION_VERIFY, via, policy=policy, actor_id=actor_id, profile_status=profile.status, doc=facts,
                grant_actions=grant_actions,
            )
            if not decision.allowed:
                excluded.append({**base, "reason_code": decision.block_reason})
                continue
            prof_items.append({**base, "expected_row_version": doc.row_version, "is_mandatory": is_mandatory})
        if len(prof_items) > n_max:
            excluded.extend(
                {k: v for k, v in it.items() if k not in ("expected_row_version", "is_mandatory")}
                | {"reason_code": PROFILE_OVER_DOCUMENT_CAP}
                for it in prof_items
            )
            continue
        items.extend(prof_items)

    # Bước 4 — vượt trần ⇒ 422, không tự cắt, không tạo lô.
    if len(items) > n_max:
        raise BulkVerifyUnprocessable(
            "TOO_MANY_DOCUMENTS",
            f"Quá {n_max} giấy trong một lô — thu hẹp lựa chọn",
            {"document_count": len(items), "limit": n_max},
        )

    # Bước 5 — chèn dòng lô ``previewed`` + dòng mục.
    batch_id = uuid4()
    now = await repo.db_clock(db)
    expires_at = now + BULK_VERIFY_PREVIEW_TTL
    payload = sorted((it["profile_id"], it["document_row_id"], it["expected_row_version"]) for it in items)
    payload_sha256 = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    filter_json: Dict[str, Any] = (
        {"profile_ids": list(profile_ids)}
        if profile_ids is not None
        else {"filter": json.loads(filter_.model_dump_json(exclude_none=True))}
    )
    await repo.insert_batch(
        db,
        {
            "batch_id": batch_id,
            "actor_user_id": actor_id,
            "review_mode": review_mode,
            "grant_id": grant.id if grant is not None else None,
            "filter_json": filter_json,
            "payload_sha256": payload_sha256,
            "include_optional": bool(include_optional),
            "expires_at": expires_at,
            "status": "previewed",
            "ip_address": meta.ip_address,
            "user_agent": (meta.user_agent or None) and meta.user_agent[:500],
        },
        [
            {
                "batch_id": batch_id,
                "document_row_id": it["document_row_id"],
                "profile_id": it["profile_id"],
                "document_type_code": it["document_type_code"],
                "expected_row_version": it["expected_row_version"],
            }
            for it in items
        ],
    )
    log.info(
        "bulk_verify_preview_created",
        batch_id=str(batch_id),
        actor_id=actor_id,
        actor_role=str(actor_role),
        review_mode=review_mode,
        documents=len(items),
        excluded=len(excluded),
    )
    required = sum(1 for it in items if it["is_mandatory"])
    return {
        "batch_id": batch_id,
        "expires_at": expires_at,
        "counts": {
            "profiles": len({it["profile_id"] for it in items}),
            "documents": len(items),
            "required": required,
            "optional": len(items) - required,
        },
        "items": items,
        "excluded": excluded,
    }


# =====================================================================================================================
# §5.3–§5.5 Chạy lô
# =====================================================================================================================
def _actor_authorized(
    review_mode: str,
    actor: Optional[models.User],
    lead: models.Lead,
    grant_row: Optional[Tuple[models.DocumentCrossReviewGrant, bool]],
) -> bool:
    """§5.4 bước 4 — kiểm lại người bấm ở MỖI hồ sơ, trên dòng VỪA KHOÁ."""
    if actor is None or actor.status != "active":
        return False
    if review_mode == REVIEW_MODE_BATCH:
        if actor.role == UserRole.ADMIN:
            return True
        return actor.role == UserRole.MANAGER and actor.unit_id is not None and actor.unit_id == lead.unit_id
    if actor.role != UserRole.OFFICER or grant_row is None:
        return False
    grant, still_valid = grant_row
    return bool(
        still_valid
        and grant.revoked_at is None
        and grant.grantee_user_id == actor.id
        and grant.unit_id == lead.unit_id
        and grant.allow_verify
        and lead.assigned_officer_id != actor.id
    )


async def execute_batch(
    db: AsyncSession,
    *,
    batch_id: UUID,
    actor_id: int,
    confirmation_text: str,
    review_mode: str,
    request_meta: Optional[RequestMeta] = None,
) -> Tuple[Dict[str, Any], Callable[[], Awaitable[None]]]:
    """Bước 0 (kiểm người tạo TRƯỚC khoá) do deps làm. Trả ``(BatchView, callback sau commit)``."""
    timeout_ms = _require_lock_timeout_ms()  # 503 chỉ phát TRƯỚC bước 2
    meta = request_meta or RequestMeta()
    k = batch_lock_key(batch_id)

    # Bước 1 — khoá phiên trên L.
    lock = await repo.try_lock_batch(BULK_VERIFY_BATCH_NS, k)
    if lock is None:
        raise _running()
    started = False
    try:
        # Bước 2 — MỘT giao dịch: khoá dòng lô, kiểm lại người tạo DƯỚI khoá, đổi ``processing``.
        got = await repo.lock_batch_row(db, batch_id)
        if got is None or got[0].actor_user_id != actor_id or got[0].review_mode != review_mode:
            await _safe_rollback(db)
            raise PreviewGone()
        row, expired = got
        if row.status != "previewed":
            await _safe_rollback(db)
            raise BulkBatchConflict("BATCH_EXISTS", "Lô này đã được chạy — tra lô để xem kết quả")
        if expired:
            await _safe_rollback(db)
            raise BulkBatchConflict("PREVIEW_EXPIRED", "Bản xem trước đã hết hạn — xem trước lại")
        grant_id = row.grant_id
        await repo.set_batch_status(
            db, batch_id, status="processing", confirmation_text=confirmation_text, started_at=func.clock_timestamp()
        )
        await _commit_step(db)
        started = True
        log.info("bulk_verify_started", batch_id=str(batch_id), actor_id=actor_id, review_mode=review_mode)
        # Bước 3 — đúng các dòng mục đã lưu.
        await _run_profiles(
            db,
            batch_id=batch_id,
            lock=lock,
            actor_id=actor_id,
            review_mode=review_mode,
            grant_id=grant_id,
            timeout_ms=timeout_ms,
            meta=meta,
        )
    finally:
        # Xong (completed / stopped đã commit) RỒI mới nhả khoá.
        await repo.release_batch_lock(lock)

    view = await get_batch(db, batch_id=batch_id, viewer_id=actor_id, viewer_role=None)

    async def post_commit() -> None:
        if started:
            await emit_bulk_verify_finished(actor_id, batch_id)

    return view, post_commit


async def _run_profiles(
    db: AsyncSession,
    *,
    batch_id: UUID,
    lock: repo.BatchLock,
    actor_id: int,
    review_mode: str,
    grant_id: Optional[int],
    timeout_ms: int,
    meta: RequestMeta,
) -> None:
    groups: "OrderedDict[int, List[Tuple[int, int]]]" = OrderedDict()
    for it in await repo.list_items(db, batch_id):
        groups.setdefault(it.profile_id, []).append((it.document_row_id, it.expected_row_version))
    await _commit_step(db)  # kết thúc giao dịch chỉ đọc (commit không làm hết hạn đối tượng trong phiên)
    for profile_id, items in groups.items():
        go_on = await _process_profile(
            db,
            batch_id=batch_id,
            lock=lock,
            actor_id=actor_id,
            review_mode=review_mode,
            grant_id=grant_id,
            profile_id=profile_id,
            items=items,
            timeout_ms=timeout_ms,
            meta=meta,
        )
        if not go_on:
            return
    await _finish(db, batch_id)


async def _process_profile(
    db: AsyncSession,
    *,
    batch_id: UUID,
    lock: repo.BatchLock,
    actor_id: int,
    review_mode: str,
    grant_id: Optional[int],
    profile_id: int,
    items: List[Tuple[int, int]],
    timeout_ms: int,
    meta: RequestMeta,
) -> bool:
    """MỘT hồ sơ = MỘT giao dịch (§5.4). Trả ``True`` = chạy tiếp hồ sơ sau, ``False`` = dừng vòng lặp."""
    from app.services.admission_service import _lock_profile_for_document_write

    done: List[document_transition.TransitionResult] = []
    try:
        # 1. Khoá theo thứ tự §4.5 — dòng lô TRƯỚC.
        got = await repo.lock_batch_row(db, batch_id)
        # 2. Trạng thái lô.
        if got is None or got[0].status != "processing":
            await _safe_rollback(db)
            log.info("bulk_verify_halted_not_processing", batch_id=str(batch_id), profile_id=profile_id)
            return False
        # 3. Kiểm sống khoá tư vấn trên L.
        try:
            alive = await repo.batch_lock_alive(lock)
        except Exception as exc:  # noqa: BLE001 — L chết / lỗi truy vấn ⇒ coi như mất khoá
            log.warning("bulk_verify_lock_check_failed", batch_id=str(batch_id), error_type=type(exc).__name__)
            alive = False
        if not alive:
            await _safe_rollback(db)
            log.warning("bulk_verify_lock_lost", batch_id=str(batch_id), profile_id=profile_id)
            return False
        await repo.set_local_lock_timeout(db, timeout_ms)
        # … → quyền chéo FOR SHARE → hồ sơ FOR UPDATE → lead FOR SHARE → giấy FOR UPDATE (id tăng) → người bấm FOR SHARE.
        grant_row = await repo.lock_grant_share(db, grant_id) if review_mode == REVIEW_MODE_CROSS else None
        try:
            profile = await _lock_profile_for_document_write(db, profile_id)
        except ResourceNotFoundError:
            profile = None
        lead = await repo.lock_lead_share(db, profile.lead_id) if profile is not None else None
        versions = await repo.lock_documents(db, profile_id, [d for d, _ in items]) if profile is not None else {}
        actor = await repo.lock_user_share(db, actor_id)

        if profile is None or lead is None or lead.deleted_at is not None:
            await repo.write_profile_error(db, batch_id, profile_id, rules.NOT_PENDING, _msg(rules.NOT_PENDING))
            await _commit_profile(db)
            return True

        # 4. Kiểm lại người bấm ở MỖI hồ sơ.
        if not _actor_authorized(review_mode, actor, lead, grant_row):
            await repo.write_profile_error(db, batch_id, profile_id, ACTOR_NOT_AUTHORIZED, _msg(ACTOR_NOT_AUTHORIZED))
            await repo.mark_remaining_not_processed(db, batch_id, NOT_PROCESSED_MESSAGE)
            await repo.set_batch_status(db, batch_id, status="stopped", finished_at=func.clock_timestamp())
            await _commit_profile(db)
            log.warning("bulk_verify_stopped_actor_not_authorized", batch_id=str(batch_id), profile_id=profile_id)
            return False

        # 5–6. Từng giấy trong SAVEPOINT; dòng kết quả CÙNG giao dịch.
        via = rules.VIA_CROSS if review_mode == REVIEW_MODE_CROSS else rules.VIA_BATCH
        results: List[Dict[str, Any]] = []
        for document_row_id, expected_row_version in items:
            code: Optional[str] = None
            # Phiên bản so TRƯỚC (trên dòng vừa khoá): bản xem trước đã cũ ⇒ ``version_changed`` (§5.9 "hai tab"), kể cả khi
            # giấy đã đổi trạng thái — lõi ``decide`` chạy trước phép so phiên bản nên sẽ báo ``not_pending``. Lõi vẫn kiểm
            # lại phiên bản khi ghi (tầng chủ sở hữu).
            if document_row_id not in versions:
                results.append({"document_row_id": document_row_id, "result": "error", "reason_code": rules.NOT_PENDING,
                                "message": _msg(rules.NOT_PENDING)})
                continue
            if versions[document_row_id] != expected_row_version:
                code = document_transition.VERSION_CHANGED
                results.append({"document_row_id": document_row_id, "result": "error", "reason_code": code,
                                "message": _msg(code)})
                continue
            try:
                async with db.begin_nested():
                    res = await document_transition.transition_document(
                        db,
                        profile_id=profile_id,
                        document_row_id=document_row_id,
                        action=rules.ACTION_VERIFY,
                        actor_id=actor_id,
                        via=via,
                        expected_row_version=expected_row_version,
                        batch_id=batch_id,
                        grant_id=grant_id if review_mode == REVIEW_MODE_CROSS else None,
                        request_meta=meta,
                    )
                done.append(res)
            except DocumentTransitionConflict as exc:
                code = exc.reason_code
            except PermissionDeniedError:
                code = rules.NOT_PERMITTED
            except ResourceNotFoundError:
                code = rules.NOT_PENDING
            except ValidationError:
                code = rules.MISSING_FORMAT
            if code is None:
                results.append({"document_row_id": document_row_id, "result": "recorded"})
            else:
                results.append(
                    {"document_row_id": document_row_id, "result": "error", "reason_code": code, "message": _msg(code)}
                )
        await repo.write_item_results(db, batch_id, results)
        await _commit_profile(db)
    except Exception as exc:  # noqa: BLE001 — phân loại ngay dưới đây; CancelledError (BaseException) đi thẳng ra ngoài
        await _safe_rollback(db)
        if repo.is_busy_error(exc):
            log.warning("bulk_verify_profile_busy", batch_id=str(batch_id), profile_id=profile_id)
            return await _handle_busy(db, batch_id=batch_id, profile_id=profile_id, done=done)
        log.error(
            "bulk_verify_profile_system_error",
            batch_id=str(batch_id),
            profile_id=profile_id,
            error_type=type(exc).__name__,
        )
        await _handle_system_error(db, batch_id=batch_id, profile_id=profile_id, done=done)
        return False
    # Callback chỉ cho hồ sơ ĐÃ commit.
    for res in done:
        await res.finalize(True)
    return True


async def _handle_busy(
    db: AsyncSession, *, batch_id: UUID, profile_id: int, done: List[document_transition.TransitionResult]
) -> bool:
    """§5.4 bước 7: giao dịch hồ sơ đã rollback sạch ⇒ giao dịch MỚI khoá dòng lô, xác nhận hồ sơ chưa có dòng kết quả ⇒
    ghi ``error`` / ``profile_busy`` BỀN rồi chạy tiếp. Không ghi được ⇒ dừng lô (§5.5)."""
    for res in done:
        await res.finalize(False)
    try:
        got = await repo.lock_batch_row(db, batch_id)
        if got is None or got[0].status != "processing":
            await _safe_rollback(db)
            return False
        if not await repo.profile_has_results(db, batch_id, profile_id):
            await repo.write_busy_results(db, batch_id, profile_id, _msg(PROFILE_BUSY))
        await _commit_step(db)
        return True
    except Exception as exc:  # noqa: BLE001
        await _safe_rollback(db)
        log.error("bulk_verify_busy_result_not_durable", batch_id=str(batch_id), error_type=type(exc).__name__)
        await _handle_system_error(db, batch_id=batch_id, profile_id=profile_id, done=[])
        return False


async def _handle_system_error(
    db: AsyncSession, *, batch_id: UUID, profile_id: int, done: List[document_transition.TransitionResult]
) -> None:
    """§5.5: giao dịch MỚI khoá dòng lô (chờ giao dịch hồ sơ k thật sự xong), đọc dòng kết quả: có ⇒ giữ (đã commit);
    không ⇒ ``error`` / ``system_error``; hồ sơ sau ⇒ ``not_processed``; ``stopped``. Không ghi được ⇒ lô ở ``processing``,
    khoá nhả ⇒ tra lô thấy ``interrupted_unfinalized`` ⇒ chốt lô."""
    try:
        got = await repo.lock_batch_row(db, batch_id)
        if got is None or got[0].status != "processing":
            await _safe_rollback(db)
            return
        committed = await repo.profile_has_results(db, batch_id, profile_id)
        if not committed:
            await repo.write_profile_error(db, batch_id, profile_id, SYSTEM_ERROR, _msg(SYSTEM_ERROR))
        await repo.mark_remaining_not_processed(db, batch_id, NOT_PROCESSED_MESSAGE)
        await repo.set_batch_status(db, batch_id, status="stopped", finished_at=func.clock_timestamp())
        await _commit_step(db)
    except Exception as exc:  # noqa: BLE001
        await _safe_rollback(db)
        log.error("bulk_verify_stop_not_durable", batch_id=str(batch_id), error_type=type(exc).__name__)
        return
    for res in done:
        await res.finalize(committed)


async def _finish(db: AsyncSession, batch_id: UUID) -> None:
    try:
        got = await repo.lock_batch_row(db, batch_id)
        if got is not None and got[0].status == "processing":
            await repo.set_batch_status(db, batch_id, status="completed", finished_at=func.clock_timestamp())
            await _commit_step(db)
        else:
            await _safe_rollback(db)
    except Exception as exc:  # noqa: BLE001 — lô ở ``processing``; khoá nhả ⇒ ``interrupted_unfinalized`` ⇒ chốt lô
        await _safe_rollback(db)
        log.error("bulk_verify_finish_not_durable", batch_id=str(batch_id), error_type=type(exc).__name__)


# =====================================================================================================================
# §5.6 Tra một lô
# =====================================================================================================================
async def _derive_status(db: AsyncSession, batch_id: UUID, first: Tuple[str, bool]) -> Optional[str]:
    """Bảng §5.6 — READ COMMITTED, MỖI bước một câu riêng. Khoá vắng ⇒ ĐỌC LẠI bằng câu mới (người chạy commit trạng thái
    kết thúc TRƯỚC khi nhả khoá). Trạng thái lưu chỉ đi tới (previewed → processing → kết thúc) ⇒ tối đa 3 vòng."""
    status, expired = first
    k = batch_lock_key(batch_id)
    for _ in range(3):
        if status in TERMINAL_STATUSES:
            return status
        if status == "previewed" and expired:
            return "expired"
        try:
            held = await repo.batch_lock_held(db, BULK_VERIFY_BATCH_NS, k)
        except Exception as exc:  # noqa: BLE001 — không bao giờ suy ra ``interrupted_unfinalized`` khi không hỏi được khoá
            log.warning("bulk_verify_lock_query_failed", batch_id=str(batch_id), error_type=type(exc).__name__)
            await _safe_rollback(db)
            return "unknown"
        if held:
            return "starting" if status == "previewed" else "running"
        again = await repo.read_batch_state(db, batch_id)
        if again is None:
            return None
        if again[0] == status:
            return "not_started" if status == "previewed" else "interrupted_unfinalized"
        status, expired = again
    return "unknown"


async def get_batch(
    db: AsyncSession, *, batch_id: UUID, viewer_id: int, viewer_role: Optional[str]
) -> Dict[str, Any]:
    """Quyền xem đã kiểm ở deps (người tạo / Admin) TRƯỚC mọi truy vấn khoá."""
    first = await repo.read_batch_state(db, batch_id)
    if first is None:
        raise BatchNotFound()
    status = await _derive_status(db, batch_id, first)
    if status is None:
        raise BatchNotFound()
    return await _build_view(db, batch_id, status, viewer_id=viewer_id, viewer_role=viewer_role)


async def _build_view(
    db: AsyncSession, batch_id: UUID, status: str, *, viewer_id: int, viewer_role: Optional[str]
) -> Dict[str, Any]:
    row = await repo.read_batch(db, batch_id)
    if row is None:
        raise BatchNotFound()
    items = await repo.list_items(db, batch_id)
    view_items = []
    counts = {"recorded": 0, "error": 0, "not_processed": 0, "pending": 0}
    for it in items:
        result = it.result or "pending"
        counts[result] += 1
        view_items.append(
            {
                "profile_id": it.profile_id,
                "document_row_id": it.document_row_id,
                "document_type_code": it.document_type_code,
                "result": result,
                "reason_code": it.reason_code,
                "message": it.message,
            }
        )
    is_creator = row.actor_user_id == viewer_id
    return {
        "batch_id": row.batch_id,
        "status": status,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "finalized_at": row.finalized_at,
        "finalized_by_user_id": row.finalized_by_user_id,
        "finalize_reason": row.finalize_reason,
        "counts": {"profiles": len({it.profile_id for it in items}), **counts},
        "items": view_items,
        "can_execute": is_creator and status == "not_started",
        "can_finalize": (is_creator or viewer_role == UserRole.ADMIN) and status == "interrupted_unfinalized",
    }


# =====================================================================================================================
# §5.7 Chốt lô gián đoạn
# =====================================================================================================================
async def finalize_batch(
    db: AsyncSession,
    *,
    batch_id: UUID,
    creator_id: int,
    viewer_id: int,
    viewer_role: str,
    reason: Optional[str],
    request_meta: Optional[RequestMeta] = None,
) -> Dict[str, Any]:
    """Bước 0 (quyền TRƯỚC khoá: người tạo / Admin) do deps làm. Router commit."""
    meta = request_meta or RequestMeta()
    reason = (reason or "").strip() or None
    is_creator = viewer_id == creator_id
    is_admin = viewer_role == UserRole.ADMIN
    if not is_creator and is_admin and not reason:
        raise BulkVerifyUnprocessable("REASON_REQUIRED", "Admin chốt lô của người khác phải ghi lý do")

    # Bước 1 — lối tắt idempotent: chỉ cho trạng thái KẾT THÚC.
    first = await repo.read_batch_state(db, batch_id)
    if first is None:
        raise BatchNotFound()
    if first[0] in TERMINAL_STATUSES:
        view = await _build_view(db, batch_id, first[0], viewer_id=viewer_id, viewer_role=viewer_role)
        return {"batch": view, "finalized_now": False}

    # Bước 2 — khoá GIAO DỊCH trên khoá lô.
    k = batch_lock_key(batch_id)
    try:
        got_lock = await repo.try_xact_lock_batch(db, BULK_VERIFY_BATCH_NS, k)
    except Exception as exc:  # noqa: BLE001
        await _safe_rollback(db)
        log.warning("bulk_verify_finalize_lock_failed", batch_id=str(batch_id), error_type=type(exc).__name__)
        raise BulkVerifyLockUnavailable()
    if not got_lock:
        raise _running()

    # Bước 3 — ĐÃ giữ khoá: khoá dòng lô, kiểm lại quyền + đọc lại trạng thái DƯỚI khoá.
    locked = await repo.lock_batch_row(db, batch_id)
    if locked is None:
        raise BatchNotFound()
    row = locked[0]
    if not (row.actor_user_id == viewer_id or is_admin):
        raise BatchNotFound()
    if row.status == "previewed":
        raise BulkBatchConflict("BATCH_NOT_STARTED", "Lô chưa chạy — không có gì để chốt")
    if row.status in TERMINAL_STATUSES:
        view = await _build_view(db, batch_id, row.status, viewer_id=viewer_id, viewer_role=viewer_role)
        return {"batch": view, "finalized_now": False}

    # Bước 4 — chốt: KHÔNG ghi giấy nào, chỉ đánh dấu mục chưa chạy.
    await repo.mark_remaining_not_processed(db, batch_id, NOT_PROCESSED_MESSAGE)
    clock = await repo.db_clock(db)
    await repo.set_batch_status(
        db,
        batch_id,
        status="interrupted",
        finalized_by_user_id=viewer_id,
        finalized_at=clock,
        finalize_reason=reason,
        finished_at=func.coalesce(models.DocumentBulkBatch.__table__.c.finished_at, clock),
    )
    if is_admin:
        from app.services.audit_service import log_audit

        await log_audit(
            db,
            "document_bulk_batch",
            k,
            "finalize_by_admin",
            actor_user_id=viewer_id,
            new_value={"batch_id": str(batch_id), "creator_id": row.actor_user_id, "status": "interrupted"},
            reason=reason,
            source="api",
            ip_address=meta.ip_address,
            user_agent=(meta.user_agent or None) and meta.user_agent[:500],
        )
    log.warning("bulk_verify_finalized", batch_id=str(batch_id), finalized_by=viewer_id, by_admin=is_admin)
    view = await _build_view(db, batch_id, "interrupted", viewer_id=viewer_id, viewer_role=viewer_role)
    return {"batch": view, "finalized_now": True}


# =====================================================================================================================
# §5.8 Danh sách lô (X3)
# =====================================================================================================================
def _encode_cursor(created_at: datetime, batch_id: UUID) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "b": str(batch_id)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, UUID]]:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        c_at = datetime.fromisoformat(data["c"])
        if c_at.tzinfo is None:
            raise ValueError("naive")
        return c_at, UUID(data["b"])
    except Exception:  # noqa: BLE001
        raise ValidationError("Con trỏ trang không hợp lệ")


async def list_batches(
    db: AsyncSession,
    *,
    viewer_id: int,
    viewer_role: str,
    scope: str,
    cursor: Optional[str],
    limit: int,
    review_mode: Optional[str],
) -> Dict[str, Any]:
    if scope == "all" and viewer_role != UserRole.ADMIN:
        raise PermissionDeniedError(detail="Chỉ Admin xem được danh sách lô của mọi người")
    after = _decode_cursor(cursor)
    rows = await repo.list_batches(
        db,
        actor_user_id=None if scope == "all" else viewer_id,
        review_mode=review_mode,
        window_days=BULK_VERIFY_LIST_WINDOW_DAYS,
        after=after,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    clock = await repo.db_clock(db)
    plain = [
        {
            "batch_id": r.batch_id,
            "status": r.status,
            "expired": r.expires_at <= clock,
            "created_at": r.created_at,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
        }
        for r in rows
    ]
    counts = await repo.item_counts(db, [p["batch_id"] for p in plain])
    out = []
    for p in plain:
        status = await _derive_status(db, p["batch_id"], (p["status"], p["expired"]))
        if status is None:
            continue
        c = counts.get(p["batch_id"], {"profiles": 0, "recorded": 0, "error": 0, "not_processed": 0, "pending": 0})
        out.append(
            {
                "batch_id": p["batch_id"],
                "status": status,
                "created_at": p["created_at"],
                "started_at": p["started_at"],
                "finished_at": p["finished_at"],
                "profile_count": c["profiles"],
                "counts": c,
            }
        )
    next_cursor = _encode_cursor(plain[-1]["created_at"], plain[-1]["batch_id"]) if has_more and plain else None
    return {"items": out, "next_cursor": next_cursor}
