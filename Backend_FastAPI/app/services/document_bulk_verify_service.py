"""GĐ1b — lô duyệt giấy (Quản lý / Admin, ``review_mode = batch``) và lô duyệt chéo (``review_mode = cross``).

Đặc tả ``DAC-TA-GD1B-DUYET-GIAY-NHANH-BAN3-6-2026-11-17.md`` (sha256 ``9ef02da2…4e2e``) §5.2–§5.8; hợp đồng API GĐ1b bản 4
(sha256 ``45b718f6…adad``) §2.1. Mọi bước theo ĐÚNG thứ tự của đặc tả:

- Thứ tự khoá dòng ``user`` ↔ dòng lô (F7, 20-11): MỌI đường đi NGƯỜI → LÔ như K4 (``user_deletion_policy``: người
  ``FOR UPDATE`` → xoá lô ``previewed``). Xem trước, chạy lô bước 2 khoá người ``FOR KEY SHARE`` trước dòng lô; chốt lô
  khoá người ``FOR SHARE`` trước dòng lô (giữ VAI ổn định tới commit — quyền chốt xét bằng vai đọc dưới khoá, Codex 20-11;
  chốt lô không giữ dòng quyền chéo ⇒ không vòng chờ với Q4 bên dưới); §5.4 khoá người SAU dòng lô nhưng chỉ chạy với lô
  ``processing`` — K4 thấy lô ấy là ``BLOCK_ACTOR`` (409, chỉ đọc) nên không bao giờ xoá dòng lô đó ⇒ không vòng chờ.
- Dòng ``user`` ↔ dòng QUYỀN CHÉO (PR-B, Q4): đổi vai / khoá tài khoản đi NGƯỜI → QUYỀN (``document_cross_review_service.
  revoke_grants_on_account_change``: người ``FOR NO KEY UPDATE`` → quyền ``FOR UPDATE``). Mọi đường duyệt chéo (lẻ, xem
  trước, §5.4) khoá người bằng ``FOR KEY SHARE`` — KHÔNG xung đột ``FOR NO KEY UPDATE`` — nên dù khoá người trước hay sau
  dòng quyền cũng không vòng chờ; đổi vai / khoá xếp hàng sau duyệt chéo ở DÒNG QUYỀN (``FOR UPDATE`` ↔ ``FOR SHARE``).
  ``FOR SHARE`` trên người (bản cũ của lõi / §5.4 khi lô chéo) + giữ dòng quyền ⇒ vòng chờ với Q4; ``FOR SHARE`` trên
  người TRƯỚC lead ⇒ vòng chờ với giao lead cho chính người ấy (lead ``FOR UPDATE`` → ``UPDATE user.last_assigned_at``).
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
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from types import SimpleNamespace
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
# Tham số — MỘT chỗ. K1 = N và ``lock_timeout`` lấy từ số đo V3 (§16; biên bản
# ``logs-P5/cong-bo-ket-qua/gd1b/v3/BIEN-BAN-V3-…``): lô 100 hồ sơ × 12 giấy = 1.200 giấy chạy 24,4 s (20,3 ms / giấy),
# giao dịch một hồ sơ p99 288 ms / max 337 ms. N = 1.000 ⇒ ~20 s, ~3 lần cách trần 60 s của nginx (dư cho máy chủ chậm hơn
# máy đo); ``lock_timeout`` 5 s ≈ 15 lần giao dịch hồ sơ dài nhất. Kiểu vẫn cho ``None`` = 503 fail-closed (§13.3).
# =====================================================================================================================
BULK_VERIFY_MAX_PROFILES = 100
BULK_VERIFY_MAX_DOCUMENTS: Optional[int] = 1000
BULK_VERIFY_LOCK_TIMEOUT_MS: Optional[int] = 5000
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


#: Thân 404 chung của luồng duyệt chéo — CÙNG chuỗi với ``deps.CROSS_REVIEW_NOT_FOUND_DETAIL`` (cổng vào). Hai bản (dịch
#: vụ không import ``deps``) khoá bằng nhau bằng phép so BYTE thân phản hồi ở ``tests/api/test_gd1b_cheo_duoi_khoa.py``.
CROSS_REVIEW_NOT_FOUND_DETAIL = "Không tìm thấy"


class CrossReviewNotFound(ResourceNotFoundError):
    """404 CÙNG THÂN của luồng duyệt chéo (owner Q1, 20-11): thiếu quyền / ngoài phạm vi / không tồn tại — kể cả khi phát
    hiện DƯỚI KHOÁ (F2 / F3: quyền hết hạn / bị thu hồi / người đổi vai / bị khoá trong lúc chờ khoá)."""

    detail = CROSS_REVIEW_NOT_FOUND_DETAIL
    error_code = "RESOURCE_NOT_FOUND"


async def cross_denial(
    db: AsyncSession, actor: Optional[Any], action: str, lead: Optional[Any] = None
) -> BaseAppException:
    """F2 / F3 + Q1 — vị từ chéo KHÔNG đạt dưới khoá ⇒ chọn mã lỗi (chỉ ĐỌC, không khoá thêm; quyết định chặn đã xong):

    - người gọi VẪN còn một quyền hợp lệ cho ĐÚNG thao tác (và đúng đơn vị lead, nếu có lead) ⇒ 409
      ``actor_not_authorized`` — gửi ``grant_id`` sai / cũ (hợp đồng bản 4 §2.2: giao diện làm mới hàng đợi);
    - không còn ⇒ :class:`CrossReviewNotFound` (404 cùng thân cổng vào — owner Q1: thiếu quyền / ngoài phạm vi)."""
    if await has_cross_right(db, actor, action, lead):
        return DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    return CrossReviewNotFound()


def unit_scope(unit_id: Optional[int]) -> Any:
    """"Lead giả" cho câu hỏi quyền theo ĐƠN VỊ (không gắn hồ sơ cụ thể — vd đơn vị của một lô chéo): đúng đơn vị, không ai
    phụ trách, chưa xoá — để ``cross_grant_authorizes`` (MỘT vị từ) trả lời "quyền này có phủ đơn vị ấy cho thao tác ấy"."""
    return SimpleNamespace(unit_id=unit_id, assigned_officer_id=None, deleted_at=None)


async def has_cross_right(db: AsyncSession, actor: Optional[Any], action: str, lead: Optional[Any] = None) -> bool:
    """Người gọi còn ÍT NHẤT MỘT quyền chéo còn hiệu lực (``clock_timestamp()``) cho ĐÚNG thao tác — và, khi có ``lead``
    (hoặc :func:`unit_scope`), đúng ĐƠN VỊ của nó — theo ``cross_grant_authorizes``. Chỉ đọc. MỘT nguồn cho: phân loại
    409 / 404 dưới khoá (:func:`cross_denial`), cổng lô chéo (``deps``: tra / chạy / chốt lô đúng đơn vị của lô), chốt lô
    chéo dưới khoá, danh sách lô chéo."""
    if not (_actor_live(actor) and actor.role == UserRole.OFFICER):
        return False
    for g in await repo.active_grants_for_user(db, actor.id):
        if grant_allows(g, action) if lead is None else cross_grant_authorizes(actor, lead, (g, True), action):
            return True
    return False


async def lock_cross_right_for_unit(db: AsyncSession, actor: Optional[Any], action: str, unit_id: Optional[int]) -> bool:
    """Codex lượt 2 PR-B, điểm chặn 2 — tìm MỘT quyền của người gọi cho ĐÚNG thao tác + ĐÚNG đơn vị và GIỮ chính dòng ấy
    ``FOR SHARE`` tới hết giao dịch: khoá rồi kiểm lại CHÍNH dòng vừa khoá bằng ``cross_grant_authorizes`` (``still_valid``
    tính bằng ``clock_timestamp()`` sau khi đủ khoá) — không kết luận từ một lần đọc thường. Dùng ở chốt lô chéo (owner câu
    10): quyền tạo lô đã mất mà còn quyền thứ hai cùng đơn vị ⇒ dòng ĐƯỢC KHOÁ là quyền thứ hai, nên Admin thu hồi nó tới
    sau phải CHỜ chốt commit; thu hồi đã commit trước lúc khoá ⇒ dòng ấy không còn cho phép ⇒ xét ứng viên kế.

    Ứng viên = quyền còn hiệu lực (đọc thường) đúng đơn vị + đúng thao tác, khoá theo id TĂNG (cùng chiều Q4 khoá ``FOR
    UPDATE`` id tăng). Người gọi đã giữ dòng người + dòng lô (thứ tự toàn cục người → lô → quyền)."""
    if unit_id is None or not (_actor_live(actor) and actor.role == UserRole.OFFICER):
        return False
    scope = unit_scope(unit_id)
    for g in await repo.active_grants_for_user(db, actor.id):
        if g.unit_id != unit_id or not grant_allows(g, action):
            continue
        if cross_grant_authorizes(actor, scope, await repo.lock_grant_share(db, g.id), action):
            return True
    return False


async def cross_batch_unit(db: AsyncSession, batch: Any) -> Optional[int]:
    """Đơn vị của một lô chéo = đơn vị ghi trên quyền dùng để tạo lô (``document_bulk_batch.grant_id``). Chỉ đọc."""
    if batch is None or batch.grant_id is None:
        return None
    return await repo.grant_unit_id(db, batch.grant_id)


def _running() -> BulkBatchConflict:
    return BulkBatchConflict("BATCH_RUNNING", "Lô đang chạy — tra lô để xem kết quả")


def confirmation_sentence(n_documents: int) -> str:
    """Câu của ô xác nhận lô (hợp đồng bản 5 B5) với ``n_documents`` = số mục ĐÃ LƯU của lô (= ``counts.documents`` lúc
    xem trước). Codex 71 điểm 4: ``execute`` chỉ nhận ĐÚNG câu này rồi mới lưu — chuỗi tuỳ ý không thành dấu vết xác nhận.
    Giao diện dựng cùng câu (``frontend/src/lib/document-review/messages.ts`` ``confirmationSentence``);
    ``tests/unit/test_gd1b_lo_cau_xac_nhan.py`` khoá hai bên bằng nhau (CLAUDE.md §7)."""
    return f"Tôi xác nhận đã đối chiếu giấy thật của {n_documents} giấy này. Phần mềm chỉ ghi lại kết quả kiểm của tôi."


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


def _needs_finalize_reason(*, is_creator: bool, viewer_role: Optional[str]) -> bool:
    """MỘT vị từ cho 422 ``REASON_REQUIRED`` của ``finalize_batch`` VÀ cờ ``finalize_requires_reason`` (hợp đồng bản 5 B4):
    Admin chốt lô của NGƯỜI KHÁC phải ghi lý do; người tạo (kể cả người tạo là Admin) thì không."""
    return (not is_creator) and viewer_role == UserRole.ADMIN


def _can_view_all_batches(viewer_role: Optional[str], *, allow_scope_all: bool) -> bool:
    """MỘT vị từ cho 403 của ``scope=all`` VÀ cờ ``can_view_all`` (hợp đồng bản 5 B4): chỉ Admin, chỉ trên đường cho phép
    ``scope=all`` (đường lô chéo luôn ``False``)."""
    return allow_scope_all and viewer_role == UserRole.ADMIN


def regular_route_shows(review_mode: Optional[str], viewer_role: Optional[str]) -> bool:
    """Codex lượt 2 PR-B, điểm chặn 1 — MỘT vị từ cho đường lô THƯỜNG (``/admissions/documents/bulk-verify``: danh sách, tra,
    chốt): lô hiện ra cho người xem khi ``review_mode`` LƯU TRONG CSDL của lô là ``batch``; Admin (ngoại lệ X3) thấy lô mọi
    chế độ. Người tạo một lô CHÉO (Cán bộ) mà nay đi đường thường (vd đã đổi vai sang Quản lý — quyền chéo đã tự thu hồi)
    KHÔNG xem / chốt được lô chéo cũ qua đường này: lô chéo chỉ mở qua đường chéo, nơi đòi quyền đúng đơn vị của lô."""
    return viewer_role == UserRole.ADMIN or review_mode == REVIEW_MODE_BATCH


def regular_route_list_mode(viewer_role: Optional[str]) -> Optional[str]:
    """Bộ lọc ``review_mode`` của DANH SÁCH đường lô thường, suy từ :func:`regular_route_shows` (``None`` = mọi chế độ)."""
    return None if regular_route_shows(REVIEW_MODE_CROSS, viewer_role) else REVIEW_MODE_BATCH


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
async def _recheck_preview_grant(db: AsyncSession, actor_row: Any, grant_id: int, unit_id: int) -> Any:
    """Xem trước lô chéo — dòng quyền FOR SHARE, kiểm DƯỚI khoá bằng ``cross_grant_authorizes`` (MỘT vị từ) trên đơn vị
    của chính quyền ấy, ``still_valid`` tính bằng ``clock_timestamp()`` TẠI LÚC GỌI. Gọi ở bước 3 và gọi LẠI sau khi
    khoá lead (điểm chặn 2). Không đạt ⇒ ném lỗi của ``cross_denial`` (409 còn quyền khác đúng đơn vị / 404)."""
    grant_row = await repo.lock_grant_share(db, grant_id)
    scope = unit_scope(unit_id if grant_row is None else grant_row[0].unit_id)
    if not cross_grant_authorizes(actor_row, scope, grant_row, rules.ACTION_VERIFY):
        raise await cross_denial(db, actor_row, rules.ACTION_VERIFY, unit_scope(unit_id))
    return grant_row[0]


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

        grant = await require_grant_for_action(db, actor=actor, grant_id=grant_id, action=rules.ACTION_VERIFY)

    # Bước 0 — tuần tự hoá theo người dùng (tự nhả cuối giao dịch).
    await repo.lock_preview_user(db, BULK_VERIFY_PREVIEW_NS, actor_id)
    # Bước 0b (F7, 20-11) — dòng người bấm ``FOR KEY SHARE`` TRƯỚC mọi dòng lô: cùng chiều với K4 (người ``FOR UPDATE``
    # → xoá lô ``previewed``). Không có bước này thì bước 1 giữ dòng lô cũ (``FOR UPDATE SKIP LOCKED``), K4 khoá người
    # rồi chờ dòng lô ấy, còn bước 5 chèn lô mới cần khoá khoá-ngoại trên dòng người ⇒ bế tắc. Dòng người không còn /
    # không hoạt động ⇒ 409 ``actor_not_authorized`` (mã có sẵn), không chèn gì — thay cho ``23503`` ⇒ 500.
    # Lô CHÉO (PR-B): cùng khoá ``FOR KEY SHARE`` (KHÔNG ``FOR SHARE`` — xem ``repo.lock_user_key_share``); đổi vai / khoá
    # tài khoản (Q4) xếp hàng sau bản xem trước này ở DÒNG QUYỀN (khoá bên dưới). Mất quyền ⇒ 404 cùng thân (owner Q1).
    actor_row = await repo.lock_user_key_share(db, actor_id)
    if not _actor_live(actor_row):
        if cross:
            raise CrossReviewNotFound()
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
    # Bước 1 — dọn bản xem trước của CHÍNH người bấm (còn ≤ 2).
    await repo.cleanup_previews(
        db, user_id=actor_id, ns=BULK_VERIFY_BATCH_NS, keep=BULK_VERIFY_MAX_LIVE_PREVIEWS - 1, key_of=batch_lock_key
    )
    # Bước 2 — đếm lại SAU khi dọn, vẫn dưới khoá bước 0.
    if await repo.count_live_previews(db, actor_id) >= BULK_VERIFY_MAX_LIVE_PREVIEWS:
        raise BulkBatchConflict("TOO_MANY_PREVIEWS", "Đang có lô chuẩn bị chạy — thử lại sau giây lát")

    # Bước 3 — chọn hồ sơ (phạm vi của người bấm) + tính tập giấy.
    if cross:
        # Dòng quyền FOR SHARE (thứ tự toàn cục: người → lô → quyền → lead), kiểm lại DƯỚI khoá: đúng người, chưa thu hồi,
        # còn hạn theo ``clock_timestamp()``, cho phép duyệt, người vẫn là Cán bộ đang hoạt động.
        grant = await _recheck_preview_grant(db, actor_row, grant.id, grant.unit_id)
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
    own_assigned_excluded = 0
    profiles = await repo.load_profiles_with_documents(db, selected)
    locked_leads: Dict[int, models.Lead] = {}
    if cross:
        # Q3 "chỉ đếm DƯỚI KHOÁ": lead FOR SHARE (id tăng) — đơn vị / người phụ trách đứng yên tới commit.
        locked_leads = await repo.lock_leads_share(db, sorted({p.lead_id for p in profiles}))
        # Codex lượt 2 PR-B, điểm chặn 4b (owner câu 8): M theo đơn vị người gọi CÒN được xem. Đổi đơn vị không thu hồi quyền
        # (owner câu 4) và không bị khoá ``FOR KEY SHARE`` của bước 0b chặn ⇒ đơn vị đọc ở bước 0b có thể đã cũ sau lần chờ
        # khoá lead. Đọc LẠI dòng người (khoá ``FOR KEY SHARE`` — đọc bản đã commit mới nhất) SAU khi có khoá lead, dùng cho
        # cả phép kiểm quyền bên dưới lẫn vị từ "được xem" (``officer_can_view_own_lead``). Không khoá mạnh hơn: ``FOR SHARE``
        # trên người SAU khoá lead đảo thứ tự người → lead (giao lead giữ lead ``FOR UPDATE`` rồi ``UPDATE`` người được giao).
        actor_row = await repo.lock_user_key_share(db, actor_id)
        # Codex lượt 1 PR-B, điểm chặn 2: khoá lead có thể phải CHỜ (lead đang bị giữ) — hạn quyền đọc ở bước 3 tính TRƯỚC lần
        # chờ ấy. Đọc lại theo đồng hồ CSDL SAU khi có khoá lead, TRƯỚC khi dựng items / excluded / M (dòng quyền đã giữ
        # FOR SHARE ⇒ không chờ thêm). Hết hạn ⇒ 404 (hoặc 409 nếu còn quyền khác đúng đơn vị) — không tạo lô.
        grant = await _recheck_preview_grant(db, actor_row, grant.id, grant.unit_id)
    for profile in profiles:
        policy = DocumentActionPolicy.for_(profile, actor)
        # F4 (PR-B): kiểm lại PHẠM VI trên lead vừa nạp / vừa khoá trong vòng lặp — câu chọn và câu nạp là hai câu riêng
        # (READ COMMITTED), lead có thể vừa chuyển đơn vị. Ngoài phạm vi ⇒ BỎ IM LẶNG (như mã không tồn tại): không vào
        # ``items`` lẫn ``excluded``, không đếm.
        lead = locked_leads.get(profile.lead_id) if cross else profile.__dict__.get("lead")
        if cross:
            if lead is None or lead.deleted_at is not None or lead.unit_id != grant.unit_id:
                continue
        elif lead is None or not _actor_authorized(REVIEW_MODE_BATCH, actor, lead, None):
            continue
        prof_items: List[Dict[str, Any]] = []
        docs = sorted(
            (d for d in profile.documents if d.category == "path" and d.status in ("paper_submitted", "uploaded")),
            key=lambda d: d.id,
        )
        own_lead = cross and lead.assigned_officer_id == actor_id
        if own_lead and not officer_can_view_own_lead(actor_row, lead):
            continue  # Q3: cán bộ không được xem hồ sơ này theo phạm vi thường ⇒ như mã không tồn tại (không đếm)
        for doc in docs:
            if doc.document_type is None:
                continue
            code, is_extra, is_mandatory, facts = _doc_rule_facts(profile, doc)
            if own_lead:
                # Q3 (owner 20-11): hồ sơ do CHÍNH cán bộ phụ trách ⇒ CHỈ đếm số giấy bị loại — KHÔNG mã hồ sơ, mã giấy,
                # họ tên, loại giấy ở bất kỳ trường nào (kể cả ``excluded``).
                if not is_extra and (is_mandatory or include_optional):
                    own_assigned_excluded += 1
                continue
            base = {"profile_id": profile.id, "document_row_id": doc.id, "document_type_code": code}
            if is_extra:
                excluded.append({**base, "reason_code": rules.OUTSIDE_CONFIG})
                continue
            if not is_mandatory and not include_optional:
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
        own_assigned_excluded=own_assigned_excluded,
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
            # Q3: "Loại M giấy do bạn phụ trách" — số riêng, KHÔNG gộp vào ``documents`` (= N giấy của danh sách xác nhận).
            "own_assigned_excluded": own_assigned_excluded,
        },
        "items": items,
        "excluded": excluded,
    }


# =====================================================================================================================
# §5.3–§5.5 Chạy lô
# =====================================================================================================================
def _actor_live(actor: Optional[Any]) -> bool:
    """MỘT vị từ "người thao tác còn dùng được" (dòng còn + ``status = 'active'``) cho xem trước (bước 0b), chạy lô
    (bước 2), chốt lô, §5.4 bước 4 và lõi ``transition_document`` — đọc trên dòng VỪA khoá (``User`` hoặc hàng
    ``(id, status, …)`` của ``repo.lock_user_key_share`` / ``repo.lock_user_role_share``)."""
    return actor is not None and actor.status == "active"


def grant_allows(grant: Any, action: str) -> bool:
    """Quyền chéo cho phép ĐÚNG thao tác (``verify`` / ``reject``) — MỘT nguồn cho hàng đợi (``pick_grant_for_action``),
    cổng vào (deps), xem trước, §5.4 và lõi."""
    if action == rules.ACTION_VERIFY:
        return bool(grant.allow_verify)
    if action == rules.ACTION_REJECT:
        return bool(grant.allow_reject)
    return False


def cross_grant_authorizes(actor: Optional[Any], lead: Any, grant_row: Optional[Tuple[Any, bool]], action: str) -> bool:
    """MỘT vị từ "được duyệt chéo ``action`` trên lead này bằng quyền này" (F2 / F3 / Q1, PR-B): người còn dùng được
    (``_actor_live``) + vai Cán bộ + quyền đúng người, chưa thu hồi, còn hạn (``still_valid`` tính bằng
    ``clock_timestamp()`` SAU khi đủ khoá), đúng đơn vị lead, cho phép đúng thao tác + lead chưa xoá mềm, KHÔNG do chính
    người ấy phụ trách.

    Dùng ở: cổng vào duyệt chéo lẻ (``deps``, dòng đọc lúc vào — 404), xem trước lô chéo, §5.4 (``_actor_authorized``,
    mỗi hồ sơ, dòng vừa khoá) và lõi ``transition_document`` (dòng vừa khoá). ``actor`` / ``lead`` / ``grant`` chỉ cần các
    thuộc tính (ORM hoặc hàng cột)."""
    if not _actor_live(actor) or actor.role != UserRole.OFFICER or grant_row is None or lead is None:
        return False
    grant, still_valid = grant_row
    return bool(
        still_valid
        and grant.revoked_at is None
        and grant.grantee_user_id == actor.id
        and grant.unit_id == lead.unit_id
        and grant_allows(grant, action)
        and getattr(lead, "deleted_at", None) is None
        and lead.assigned_officer_id != actor.id
    )


def officer_can_view_own_lead(actor: Any, lead: Any) -> bool:
    """Q3 (owner 20-11) — cán bộ được xem hồ sơ của lead này theo phạm vi đọc thường của Cán bộ (``deps.
    get_admission_for_user_read``: lead CÙNG đơn vị người ấy VÀ do chính người ấy phụ trách). Chỉ khi đạt (cùng các
    điều kiện khác của xem trước chéo) mới ĐẾM giấy "do bạn phụ trách"; không đạt ⇒ bỏ im lặng như mã không tồn tại.
    ``tests/api/test_gd1b_cheo_pham_vi_xem_truoc.py`` khoá vị từ này bằng cổng đọc thật qua HTTP."""
    return bool(
        actor.unit_id is not None
        and lead.unit_id == actor.unit_id
        and lead.assigned_officer_id == actor.id
        and getattr(lead, "deleted_at", None) is None
    )


def _actor_authorized(
    review_mode: str,
    actor: Optional[models.User],
    lead: models.Lead,
    grant_row: Optional[Tuple[models.DocumentCrossReviewGrant, bool]],
) -> bool:
    """§5.4 bước 4 — kiểm lại người bấm ở MỖI hồ sơ, trên dòng VỪA KHOÁ. Lô chéo = ``cross_grant_authorizes`` (verify)."""
    if not _actor_live(actor):
        return False
    if review_mode == REVIEW_MODE_BATCH:
        if actor.role == UserRole.ADMIN:
            return True
        return actor.role == UserRole.MANAGER and actor.unit_id is not None and actor.unit_id == lead.unit_id
    return cross_grant_authorizes(actor, lead, grant_row, rules.ACTION_VERIFY)


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
        # Bước 2 — MỘT giao dịch: khoá dòng NGƯỜI TẠO rồi dòng lô, kiểm lại người tạo DƯỚI khoá, đổi ``processing``.
        # F7 (20-11): người ``FOR KEY SHARE`` TRƯỚC dòng lô — cùng chiều với K4 (người ``FOR UPDATE`` → xoá lô
        # ``previewed``). Thiếu khoá này: K4 kiểm thấy lô còn ``previewed`` (không chặn), lượt chạy commit ``processing``,
        # K4 bỏ qua lô ấy rồi xoá người ⇒ khoá ngoại RESTRICT ``23503`` ⇒ 500 thay vì 409. Có khoá: K4 chờ tới khi
        # ``processing`` đã commit ⇒ thấy lô đã chạy ⇒ 409; K4 tới trước ⇒ lô ``previewed`` đã bị xoá cùng người ⇒ 404.
        creator = await repo.lock_user_key_share(db, actor_id)
        got = await repo.lock_batch_row(db, batch_id)
        if got is None or got[0].actor_user_id != actor_id or got[0].review_mode != review_mode:
            await _safe_rollback(db)
            raise PreviewGone()
        if not _actor_live(creator):
            await _safe_rollback(db)
            raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)
        row, expired = got
        if row.status != "previewed":
            await _safe_rollback(db)
            raise BulkBatchConflict("BATCH_EXISTS", "Lô này đã được chạy — tra lô để xem kết quả")
        if expired:
            await _safe_rollback(db)
            raise BulkBatchConflict("PREVIEW_EXPIRED", "Bản xem trước đã hết hạn — xem trước lại")
        if review_mode == REVIEW_MODE_CROSS:
            # Codex lượt 1 PR-B, điểm chặn 1: lô chéo chỉ chạy khi quyền của CHÍNH lô (đúng đơn vị của lô, cho DUYỆT) còn
            # hiệu lực — kiểm DƯỚI khoá (người → lô → quyền, cùng thứ tự toàn cục), TRƯỚC khi đổi sang ``processing``. Không
            # đạt ⇒ lô vẫn ``previewed``; 409 nếu còn quyền khác đúng đơn vị (owner câu 9: làm mới / xem trước lại), 404 cùng
            # thân nếu không (như lô không tồn tại).
            grant_row = await repo.lock_grant_share(db, row.grant_id) if row.grant_id is not None else None
            scope = unit_scope(None if grant_row is None else grant_row[0].unit_id)
            if not cross_grant_authorizes(creator, scope, grant_row, rules.ACTION_VERIFY):
                denial = await cross_denial(db, creator, rules.ACTION_VERIFY, scope)
                await _safe_rollback(db)
                raise denial
        n_items = await repo.count_batch_items(db, batch_id)
        if confirmation_text != confirmation_sentence(n_items):
            await _safe_rollback(db)
            raise BulkVerifyUnprocessable(
                "CONFIRMATION_MISMATCH",
                "Câu xác nhận không khớp số giấy của lô — xem trước lại rồi xác nhận",
                {"documents": n_items},
            )
        grant_id = row.grant_id
        await repo.set_batch_status(
            db, batch_id, status="processing", confirmation_text=confirmation_text, started_at=func.clock_timestamp()
        )
        await _commit_step(db)
        started = True
        started_at = time.monotonic()
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
    if started:
        # Thời gian chạy lô thật (biên bản V3 §4: theo dõi sau deploy trước khi nới N). Chỉ mã lô + số đếm, không PII.
        log.info(
            "bulk_verify_run_ended",
            batch_id=str(batch_id),
            status=view.get("status"),
            duration_ms=int((time.monotonic() - started_at) * 1000),
            counts=view.get("counts"),
        )

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
        # … → quyền chéo FOR SHARE → hồ sơ FOR UPDATE → lead FOR SHARE → giấy FOR UPDATE (id tăng).
        grant_row = await repo.lock_grant_share(db, grant_id) if review_mode == REVIEW_MODE_CROSS else None
        try:
            profile = await _lock_profile_for_document_write(db, profile_id)
        except ResourceNotFoundError:
            profile = None
        lead = await repo.lock_lead_share(db, profile.lead_id) if profile is not None else None
        versions = await repo.lock_documents(db, profile_id, [d for d, _ in items]) if profile is not None else {}
        if review_mode == REVIEW_MODE_CROSS:
            # → người bấm ``FOR KEY SHARE`` (PR-B: KHÔNG ``FOR SHARE`` — lô đang giữ dòng quyền FOR SHARE; đổi vai / khoá Q4
            # giữ dòng người ``FOR NO KEY UPDATE`` rồi chờ dòng quyền ⇒ ``FOR SHARE`` ở đây là vòng chờ). Q4 xếp hàng ở
            # dòng quyền: hồ sơ đang ghi commit xong ⇒ Q4 thu hồi + khoá ⇒ hồ sơ KẾ TIẾP thấy ⇒ lô dừng trước khi ghi nó.
            actor = await repo.lock_user_key_share_entity(db, actor_id)
            # F2 (PR-B): hạn quyền đọc lại SAU khi đủ khoá — ``clock_timestamp()`` của lần đọc ở trên tính TRƯỚC lúc chờ khoá
            # hồ sơ / lead / giấy. Dòng quyền đã giữ FOR SHARE ⇒ không chờ thêm.
            grant_row = await repo.lock_grant_share(db, grant_id)
        else:
            # → người bấm ``FOR SHARE`` (CUỐI CÙNG, như bản cũ — lô thường không giữ dòng quyền).
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
            except CrossReviewNotFound:
                # Lõi chặn duyệt chéo dưới khoá (quyền vừa hết hạn giữa bước 4 và giấy này) ⇒ đúng mã của mục lô.
                code = ACTOR_NOT_AUTHORIZED
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
    can_finalize = (is_creator or viewer_role == UserRole.ADMIN) and status == "interrupted_unfinalized"
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
        "can_finalize": can_finalize,
        # Hợp đồng bản 5 B4 — cùng vị từ với 422 của ``finalize_batch``.
        "finalize_requires_reason": can_finalize and _needs_finalize_reason(is_creator=is_creator, viewer_role=viewer_role),
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
    cross_route: bool = False,
) -> Dict[str, Any]:
    """Bước 0 (quyền TRƯỚC khoá: người tạo / Admin) do deps làm. Router commit. ``cross_route`` = gọi từ đường lô CHÉO
    (người tạo là Cán bộ chéo): owner câu 10 (21-11) — vẫn phải còn quyền duyệt đúng đơn vị của lô, kiểm lại dưới khoá."""
    meta = request_meta or RequestMeta()
    reason = (reason or "").strip() or None
    is_creator = viewer_id == creator_id
    # 422 TRƯỚC khoá (hợp đồng bản 5 B4 — cùng vị từ với cờ ``finalize_requires_reason``), xét bằng vai đầu yêu cầu. Phép
    # kiểm này chỉ TỪ CHỐI, không cấp quyền: quyền GHI quyết ở bước 3 bằng vai đọc lại dưới khoá. Người không phải người
    # tạo chỉ qua được cổng bước 0 khi vai đầu yêu cầu là Admin ⇒ đã bị đòi lý do ở đây ⇒ "Admin chốt lô của người khác
    # luôn có lý do" vẫn đúng khi bước 3 xét bằng vai hiện hành.
    if _needs_finalize_reason(is_creator=is_creator, viewer_role=viewer_role) and not reason:
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

    # Bước 3 — ĐÃ giữ khoá: khoá dòng NGƯỜI CHỐT rồi dòng lô (F7, 20-11 — cùng chiều K4: người → lô; bước 4 ghi
    # ``finalized_by_user_id`` = khoá ngoại tới dòng người này), kiểm lại quyền + đọc lại trạng thái DƯỚI khoá.
    # Dòng người khoá ``FOR SHARE``, KHÔNG ``FOR KEY SHARE`` (Codex 20-11): lệnh đổi vai / khoá tài khoản tới sau phải CHỜ
    # chốt commit, nên vai đọc ở đây còn đúng tới lúc ghi; đổi vai đã commit TRƯỚC bước này thì đọc ra vai MỚI.
    finalizer = await repo.lock_user_role_share(db, viewer_id)
    locked = await repo.lock_batch_row(db, batch_id)
    if locked is None:
        raise BatchNotFound()
    row = locked[0]
    # Quyền chốt xét bằng VAI HIỆN HÀNH (đọc dưới khoá ở trên), không bằng ``viewer_role`` đọc từ đầu yêu cầu: Admin vừa bị
    # hạ vai không còn chốt được lô của người khác ⇒ cùng 404 với cổng bước 0. Dòng người không còn / không hoạt động thì
    # không có vai để xét ở đây — phép kiểm ``_actor_live`` bên dưới trả 409 ``actor_not_authorized`` (như trước).
    is_admin = finalizer is not None and finalizer.role == UserRole.ADMIN
    if _actor_live(finalizer) and not (row.actor_user_id == viewer_id or is_admin):
        raise BatchNotFound()
    if not cross_route and _actor_live(finalizer) and not regular_route_shows(row.review_mode, finalizer.role):
        # PR-B lượt 3 (Codex điểm chặn 1): đường lô THƯỜNG chỉ chốt lô ``batch`` — lô chéo chỉ Admin (X3). Cổng deps đã
        # chặn bằng vai đầu yêu cầu; ở đây xét lại bằng vai đọc DƯỚI khoá (Admin vừa bị hạ vai, người tạo là chính họ).
        raise BatchNotFound()
    if cross_route and _actor_live(finalizer):
        # Owner câu 10 + Codex lượt 1 PR-B điểm chặn 1: lô chéo — người chốt còn quyền DUYỆT ĐÚNG đơn vị của lô. Codex lượt
        # 2 điểm chặn 2: GIỮ ``FOR SHARE`` CHÍNH dòng quyền đang cho phép chốt (``lock_cross_right_for_unit``; cùng thứ tự
        # người → lô → quyền) — thu hồi nó tới sau phải chờ chốt commit. Không ⇒ 404 cùng thân cổng lô chéo, TRƯỚC mọi kết
        # luận về trạng thái (không lộ "chưa chạy" / "đã xong").
        if not await lock_cross_right_for_unit(db, finalizer, rules.ACTION_VERIFY, await cross_batch_unit(db, row)):
            raise CrossReviewNotFound()
    if row.status == "previewed":
        raise BulkBatchConflict("BATCH_NOT_STARTED", "Lô chưa chạy — không có gì để chốt")
    if row.status in TERMINAL_STATUSES:
        view = await _build_view(db, batch_id, row.status, viewer_id=viewer_id, viewer_role=viewer_role)
        return {"batch": view, "finalized_now": False}

    # Người chốt bị xoá / khoá tài khoản trong lúc chờ khoá ⇒ 409 ``actor_not_authorized`` (mã có sẵn), không ghi gì —
    # thay cho ``23503`` ⇒ 500 ở câu ghi ``finalized_by_user_id``.
    if not _actor_live(finalizer):
        raise DocumentTransitionConflict(ACTOR_NOT_AUTHORIZED)

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
    allow_scope_all: bool,
) -> Dict[str, Any]:
    if scope == "all" and not _can_view_all_batches(viewer_role, allow_scope_all=allow_scope_all):
        raise PermissionDeniedError(detail="Chỉ Admin xem được danh sách lô của mọi người")
    after = _decode_cursor(cursor)
    grant_unit_ids = None
    if review_mode == REVIEW_MODE_CROSS:
        # Codex lượt 1 PR-B điểm chặn 1 (vá nhánh danh sách): danh sách lô chéo chỉ gồm lô thuộc đơn vị người gọi CÒN quyền
        # duyệt — cùng điều kiện với cổng tra / chạy / chốt (``deps._cross_batch_in_scope``), không liệt kê lô mở ra là 404.
        grant_unit_ids = sorted(
            {g.unit_id for g in await repo.active_grants_for_user(db, viewer_id) if grant_allows(g, rules.ACTION_VERIFY)}
        )
    rows = await repo.list_batches(
        db,
        actor_user_id=None if scope == "all" else viewer_id,
        review_mode=review_mode,
        window_days=BULK_VERIFY_LIST_WINDOW_DAYS,
        after=after,
        limit=limit + 1,
        grant_unit_ids=grant_unit_ids,
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
    return {
        "items": out,
        "next_cursor": next_cursor,
        # Hợp đồng bản 5 B4 — cùng vị từ với 403 của ``scope=all``.
        "can_view_all": _can_view_all_batches(viewer_role, allow_scope_all=allow_scope_all),
    }
