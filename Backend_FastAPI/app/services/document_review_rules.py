"""GĐ1b — luật quyết định duyệt / từ chối / Đặt lại giấy thường: MỘT nguồn cho cờ máy chủ (§4.7) VÀ cổng ghi
``transition_document`` (§4).

Đặc tả GĐ1b bản 3.6 §4.1 (phạm vi theo ``via``), §4.2 (người nhận / người tải, Đặt lại, X1), §4.6 (hình thức), §4.7 (cờ).
Hàm thuần — không đọc CSDL. ``transition_document`` gọi :func:`decide` với trạng thái ĐỌC LẠI DƯỚI KHOÁ; phản hồi hồ sơ gọi
cùng hàm với trạng thái vừa đọc ⇒ nút giao diện và cổng máy chủ không thể lệch nhau.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

from app.services.admission_document_policy import DocumentActionPolicy

#: Tập hồ sơ "chờ xét" — lô / duyệt chéo chỉ chạm hồ sơ ở các trạng thái này (§4.1).
PENDING_PROFILE_STATUSES: FrozenSet[str] = frozenset({"submitted", "resubmitted", "reviewing", "revision_requested"})

VIA_SINGLE = "single"
VIA_BATCH = "batch"
VIA_CROSS = "cross"
VIAS = (VIA_SINGLE, VIA_BATCH, VIA_CROSS)

ACTION_VERIFY = "verify"
ACTION_REJECT = "reject"
ACTION_RESET = "reset"

#: Mã lý do chặn (``verify_block_reason`` + ``reason_code`` của mục lô) — tiếng Anh (quy ước owner 17-11).
NOT_PERMITTED = "not_permitted"
OWN_SUBMISSION = "own_submission"
UNKNOWN_SUBMITTER = "unknown_submitter"
MISSING_FORMAT = "missing_format"
OUTSIDE_CONFIG = "outside_config"
NOT_PENDING = "not_pending"
CROSS_NO_RESET = "cross_no_reset"
NOT_RESETTABLE = "not_resettable"


def config_facts(applied_rules: Optional[dict], doc_code: str, *, has_file: bool) -> Tuple[bool, bool]:
    """``(is_extra, requires_upload)`` của MỘT giấy theo ảnh chụp ``applied_rules`` của hồ sơ.

    MỘT nguồn (CLAUDE.md §7) cho ``transition_document`` (dưới khoá), cờ máy chủ của phản hồi hồ sơ và bộ chọn của lô —
    trước đây ba nơi tự chép. Giấy ngoài cấu hình (đường xét đổi sau khi nộp) không còn cấu hình ⇒ ``requires_upload`` suy
    từ việc có tệp."""
    doc_configs = (applied_rules or {}).get("doc_configs") or {}
    if doc_code not in doc_configs:
        return True, bool(has_file)
    return False, bool((doc_configs.get(doc_code) or {}).get("requires_upload", True))


@dataclass(frozen=True)
class DocFacts:
    """Sự kiện về MỘT dòng giấy thường cần cho quyết định."""

    status: str
    requires_upload: bool
    is_extra: bool
    has_file: bool
    receiver_id: Optional[int]
    receiver_unknown: bool
    actual_submission_format: Optional[str]

    @classmethod
    def from_row(cls, doc, *, requires_upload: bool, is_extra: bool) -> "DocFacts":
        """"Người gắn với giấy" (người nhận) = ``paper_submitted_by`` nếu giấy KHÔNG có tệp; ``uploaded_by`` nếu có tệp
        (§4.2). Cột NULL coi là "không rõ" kể cả khi cờ chưa bật (trạng thái ngoài phạm vi I1 / I2)."""
        has_file = bool(doc.file_path)
        if has_file:
            rid, flag = doc.uploaded_by, bool(doc.uploaded_by_unknown)
        else:
            rid, flag = doc.paper_submitted_by, bool(doc.paper_submitted_by_unknown)
        return cls(
            status=doc.status,
            requires_upload=requires_upload,
            is_extra=is_extra,
            has_file=has_file,
            receiver_id=rid,
            receiver_unknown=flag or rid is None,
            actual_submission_format=doc.actual_submission_format,
        )


@dataclass(frozen=True)
class Decision:
    allowed: bool
    block_reason: Optional[str] = None
    #: Người nhận "không rõ": nút lẻ chỉ qua ngoại lệ có cam kết (ack + lý do).
    requires_ack: bool = False


_DENY_NOT_PERMITTED = Decision(False, NOT_PERMITTED)


def _receiver_gate(actor_id: int, doc: DocFacts, via: str) -> Decision:
    """§4.2: người nhận KHÔNG tự duyệt / từ chối / Đặt lại giấy đã duyệt. Không rõ người nhận: lô / chéo loại; nút lẻ cần
    cam kết. Cam kết KHÔNG mở đường khi người nhận đã biết là chính người bấm."""
    if not doc.receiver_unknown and doc.receiver_id == actor_id:
        return Decision(False, OWN_SUBMISSION)
    if doc.receiver_unknown:
        if via == VIA_SINGLE:
            return Decision(True, None, requires_ack=True)
        return Decision(False, UNKNOWN_SUBMITTER)
    return Decision(True)


def _reviewer(policy: DocumentActionPolicy) -> bool:
    """Quản lý trong phạm vi / Admin, hồ sơ chưa nhập học."""
    return policy.ctx.reviewer_scope and policy.ctx.reviewer_can_modify_docs


def decide(
    action: str,
    via: str,
    *,
    policy: DocumentActionPolicy,
    actor_id: int,
    profile_status: str,
    doc: DocFacts,
    grant_actions: FrozenSet[str] = frozenset(),
) -> Decision:
    """Quyết định MỘT thao tác trên MỘT giấy thường. ``grant_actions`` chỉ dùng khi ``via = cross`` (đã kiểm hiệu lực
    quyền chéo ở nơi gọi, dưới khoá)."""
    if via not in VIAS:
        raise ValueError(via)

    if action == ACTION_RESET:
        if via == VIA_CROSS:
            return Decision(False, CROSS_NO_RESET)
        if via == VIA_BATCH:
            return _DENY_NOT_PERMITTED
        if doc.status == "missing":
            return Decision(False, NOT_RESETTABLE)
        if doc.is_extra:
            # X1: giấy ngoài cấu hình — CHỈ Quản lý trong phạm vi / Admin, chỉ Đặt lại.
            return Decision(True) if _reviewer(policy) else _DENY_NOT_PERMITTED
        if doc.status == "verified":
            if not _reviewer(policy):
                return _DENY_NOT_PERMITTED
            return _receiver_gate(actor_id, doc, via)
        # Chưa duyệt: ai đang có quyền Đặt lại như hiện nay, GỒM CẢ người nhận.
        return Decision(True) if policy.authorize(ACTION_RESET, doc.status, doc.requires_upload) else _DENY_NOT_PERMITTED

    if action not in (ACTION_VERIFY, ACTION_REJECT):
        raise ValueError(action)
    if doc.is_extra:
        return Decision(False, OUTSIDE_CONFIG)

    if via == VIA_SINGLE:
        if not policy.authorize(action, doc.status, doc.requires_upload):
            return _DENY_NOT_PERMITTED
    elif via == VIA_BATCH:
        if action != ACTION_VERIFY or not _reviewer(policy):
            return _DENY_NOT_PERMITTED
        if profile_status not in PENDING_PROFILE_STATUSES or doc.status != "paper_submitted":
            return Decision(False, NOT_PENDING)
    else:  # cross
        if action not in grant_actions:
            return _DENY_NOT_PERMITTED
        if profile_status not in PENDING_PROFILE_STATUSES or doc.status != "paper_submitted":
            return Decision(False, NOT_PENDING)

    gate = _receiver_gate(actor_id, doc, via)
    if not gate.allowed:
        return gate
    if action == ACTION_VERIFY and via in (VIA_BATCH, VIA_CROSS) and not doc.actual_submission_format:
        return Decision(False, MISSING_FORMAT)
    return gate
