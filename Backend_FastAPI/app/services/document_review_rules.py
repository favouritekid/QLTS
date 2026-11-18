"""GĐ1b — luật quyết định duyệt / từ chối / Đặt lại giấy thường: MỘT nguồn cho cờ máy chủ (§4.7) VÀ cổng ghi
``transition_document`` (§4). GĐ2-0 (cuối tệp) — luật duyệt minh chứng ưu tiên (quyết định owner C1).

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
#: Nút lẻ chọn hình thức KHÁC hình thức lúc nhận trên giấy có tệp scan (owner 18-11, sau Codex 71 điểm 2).
FORMAT_LOCKED = "format_locked"


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


def format_change_allowed(doc: "DocFacts") -> bool:
    """Nút lẻ được chọn hình thức KHÁC hình thức lúc nhận CHỈ với giấy nộp bản giấy — người duyệt cầm giấy thật (§4.6,
    quyết định 3A). Giấy có tệp scan: khoá theo hình thức đã khai lúc tải lên; khai sai thì Đặt lại rồi tải lại (owner
    18-11, sau Codex 71 điểm 2). "Có tệp" = cùng định nghĩa với người gắn với giấy (``DocFacts.has_file``, §4.2).

    MỘT nguồn cho cổng ghi (``transition_document``), :func:`decide` (giấy scan chưa khai hình thức) và cờ máy chủ
    ``can_change_format`` của phản hồi hồ sơ."""
    return not doc.has_file


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
    # Thiếu hình thức lúc nhận: lô / chéo không duyệt được; nút lẻ chỉ tự chọn được khi giấy là bản giấy (giấy scan khoá
    # theo hình thức đã khai — :func:`format_change_allowed`).
    if (
        action == ACTION_VERIFY
        and not doc.actual_submission_format
        and (via in (VIA_BATCH, VIA_CROSS) or not format_change_allowed(doc))
    ):
        return Decision(False, MISSING_FORMAT)
    return gate


# =====================================================================================================================
# GĐ2-0 — minh chứng ưu tiên (quyết định owner C1, 17-11: ``QUYET-DINH-OWNER-GD1B-2026-11-17.md`` nhóm C).
#   (a) người tải minh chứng KHÔNG được tự duyệt;
#   (b) người duyệt = Quản lý trong đơn vị + Admin, "giống giấy tờ".
# MỘT nguồn cho: cổng quyền ``deps.require_priority_evidence_reviewer`` (b), cờ ``permissions.verify_priority_object`` của
# phản hồi hồ sơ (b), cổng người tải trong ``priority_override_service`` (a) và cổng đường cập nhật hồ sơ thường
# (``admission_service.update_profile``). Hàm thuần — không đọc CSDL.
# =====================================================================================================================

#: Trạng thái minh chứng ưu tiên ĐÃ QUA người duyệt (``priority_object_evidence[mã].status``). Chỉ đường duyệt / từ chối
#: (``priority_override_service``) được đặt hai trạng thái này.
PRIORITY_EVIDENCE_REVIEWED_STATUSES: FrozenSet[str] = frozenset({"verified", "rejected"})


def priority_evidence_reviewer(policy: DocumentActionPolicy) -> bool:
    """C1(b): người được duyệt / từ chối minh chứng ưu tiên = Admin hoặc Quản lý trong đơn vị của hồ sơ — ĐÚNG vị từ
    ``reviewer_scope`` của giấy tờ (``admission_document_policy._build_context``). Cán bộ (kể cả cán bộ phụ trách hồ sơ)
    không duyệt. Trạng thái hồ sơ do ``priority_override_service`` xét riêng (giữ nguyên luật cũ)."""
    return bool(policy.ctx.reviewer_scope)


@dataclass(frozen=True)
class PriorityEvidenceFacts:
    """Sự kiện về dòng giấy minh chứng của MỘT mã diện (``profile_document`` ``category = 'priority_evidence'``)."""

    has_file: bool
    uploader_id: Optional[int]
    uploader_unknown: bool

    @classmethod
    def from_row(cls, doc) -> "PriorityEvidenceFacts":
        """Không có dòng / dòng không tệp ⇒ duyệt theo hồ sơ giấy, KHÔNG có người tải. Có tệp mà ``uploaded_by`` NULL ⇒
        "không rõ người tải" kể cả khi cờ chưa bật (tệp tải trước GĐ2-0 không ghi người tải)."""
        if doc is None or not getattr(doc, "file_path", None):
            return cls(has_file=False, uploader_id=None, uploader_unknown=False)
        uploader = getattr(doc, "uploaded_by", None)
        return cls(
            has_file=True,
            uploader_id=uploader,
            uploader_unknown=bool(getattr(doc, "uploaded_by_unknown", False)) or uploader is None,
        )


def decide_priority_evidence(action: str, *, actor_id: int, evidence: PriorityEvidenceFacts) -> Decision:
    """C1(a): người tải tệp minh chứng KHÔNG tự duyệt / từ chối minh chứng ấy (cùng luật người nhận ≠ người duyệt của giấy
    tờ — §4.2 GĐ1b). Tệp không rõ người tải ⇒ chặn (không có đường cam kết như nút lẻ giấy tờ): tải lại tệp — hệ thống ghi
    người tải — rồi người khác duyệt. Không có tệp (duyệt theo hồ sơ giấy) ⇒ không có người tải để so."""
    if action not in (ACTION_VERIFY, ACTION_REJECT):
        raise ValueError(action)
    if not evidence.has_file:
        return Decision(True)
    if evidence.uploader_unknown:
        return Decision(False, UNKNOWN_SUBMITTER)
    if evidence.uploader_id == actor_id:
        return Decision(False, OWN_SUBMISSION)
    return Decision(True)


def _reviewed(entry) -> bool:
    return isinstance(entry, dict) and entry.get("status") in PRIORITY_EVIDENCE_REVIEWED_STATUSES


def _review_identity(entry: dict) -> Tuple:
    return (entry.get("status"), entry.get("verified_by"), entry.get("rejected_by"), entry.get("document_id"))


def merge_profile_evidence_update(current: Optional[dict], incoming: Optional[dict]) -> Tuple[dict, list]:
    """Đường cập nhật hồ sơ thường (``PUT /api/admissions/{id}``, ``AdmissionProfileUpdate.priority_object_evidence``)
    KHÔNG được đặt / đổi / bỏ trạng thái đã qua người duyệt — lối vào thứ hai của "tự duyệt" (C1).

    Trả ``(bản ghi sẽ lưu, danh sách mã vi phạm)``. Vi phạm = mã mà bản hiện tại HOẶC bản gửi lên ở trạng thái đã duyệt /
    từ chối và hai bản khác nhau ở (trạng thái, người duyệt, người từ chối, dòng giấy). Gửi lại NGUYÊN mục đã duyệt là
    hợp lệ, và bản lưu giữ ĐÚNG mục hiện tại (không nhận các trường khác của thân gửi lên cho mục ấy)."""
    cur = dict(current or {})
    inc = dict(incoming or {})
    bad = []
    for code in sorted(set(cur) | set(inc)):
        c, n = cur.get(code), inc.get(code)
        if not _reviewed(c) and not _reviewed(n):
            continue
        if _reviewed(c) and _reviewed(n) and _review_identity(c) == _review_identity(n):
            continue
        bad.append(code)
    merged = dict(inc)
    for code, c in cur.items():
        if _reviewed(c):
            merged[code] = c
    return merged, bad
