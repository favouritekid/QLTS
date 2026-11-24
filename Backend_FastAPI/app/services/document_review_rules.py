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


# =====================================================================================================================
# GĐ2-B — E4 bước 1: cấu hình giấy bắt buộc của hồ sơ (đặc tả GĐ2-B bản 4 §6.2 E4; Codex lượt 2 + lượt 3).
# =====================================================================================================================

#: Ảnh chụp ``applied_rules`` không phải object, hoặc THIẾU khoá ``mandatory_docs`` / ``doc_configs`` ⇒ cấu hình MẤT.
DOCUMENT_CONFIG_MISSING = "document_config_missing"
#: Hai khoá có mà sai kiểu, có mã trùng, ``is_mandatory`` không phải boolean JSON, hoặc hai tập mã bắt buộc LỆCH ⇒ HỎNG.
DOCUMENT_CONFIG_INVALID = "document_config_invalid"


@dataclass(frozen=True)
class RequiredDocuments:
    """Kết quả đọc cấu hình giấy bắt buộc của MỘT hồ sơ. ``error`` khác ``None`` ⇒ ``codes`` là ``None`` (không biết giấy nào
    bắt buộc — KHÔNG được coi là đủ giấy). ``codes = ()`` là "đã cấu hình KHÔNG cần giấy bắt buộc" (hợp lệ). ``material``: phần
    ảnh chụp ĐÃ DÙNG để quyết (``mandatory_docs`` nguyên + ``is_mandatory`` từng mục, bỏ nhãn) — JSON thuần, cho ``row_hash``
    của máy xét (đổi cấu hình giấy ⇒ đổi băm; đổi nhãn giấy ⇒ không)."""

    codes: Optional[Tuple[str, ...]]
    error: Optional[str]
    material: object = None


#: Đánh dấu "khoá vắng" trong ``RequiredDocuments.material`` (khác giá trị ``null``).
CONFIG_KEY_ABSENT = "<absent>"


def required_document_codes(applied_rules: object) -> RequiredDocuments:
    """Danh sách mã giấy bắt buộc theo ảnh chụp cấu hình giấy của hồ sơ — MỘT nguồn cho máy xét GĐ2-B (E4 bước 1).

    ``create_profile`` và đường đổi bộ giấy dựng CẢ HAI khoá từ CÙNG một danh sách giấy đã giải (``admission_service``:
    ``mandatory_docs`` = mã có ``is_mandatory``; ``doc_configs`` = mọi giấy kèm ``is_mandatory``) ⇒ khi mã đúng thì hai tập
    luôn bằng nhau. Luật (fail-closed — không ép kiểu, không đoán):

    * không phải object, hoặc thiếu khoá ``mandatory_docs`` hoặc ``doc_configs`` ⇒ :data:`DOCUMENT_CONFIG_MISSING`
      (KHÁC ``config_facts`` / ``_doc_rule_facts`` ở trên: khoá thiếu KHÔNG được đọc thành ``[]`` / ``{}``);
    * ``mandatory_docs`` không phải danh sách các chuỗi khác rỗng, hoặc có mã trùng; ``doc_configs`` không phải object; một giá
      trị của ``doc_configs`` không phải object; ``is_mandatory`` của nó thiếu hoặc KHÔNG phải boolean JSON (``null``, chuỗi
      ``"true"`` / ``"false"``, số 0 / 1 đều hỏng — Codex lượt 3 GIỮ) ⇒ :data:`DOCUMENT_CONFIG_INVALID`;
    * M = tập mã trong ``mandatory_docs``, D = tập mã của ``doc_configs`` có ``is_mandatory`` là ``true``; M ≠ D theo BẤT KỲ
      chiều nào ⇒ :data:`DOCUMENT_CONFIG_INVALID` (bản 4 — Codex lượt 2);
    * hợp lệ ⇒ ``codes`` = M sắp tăng dần (có thể rỗng: M = D = ∅ là cấu hình hợp lệ, E4 đạt riêng bước này).

    Hàm thuần — không đọc CSDL. Đây là nơi DUY NHẤT của các module GĐ2-B đọc khoá ``mandatory_docs`` (test AST khoá) — kể cả
    phần ``material`` cho ``row_hash``.

    ``material`` (đợt 1 sau Codex B3): E4 coi ``mandatory_docs`` là TẬP ⇒ danh sách mã (mọi phần tử là chuỗi) đem băm ĐÃ SẮP — đổi
    thứ tự ``[A, B]`` ↔ ``[B, A]`` KHÔNG đổi băm; phần tử trùng GIỮ (trùng là cấu hình hỏng, vẫn khác băm với bản không trùng).
    ``doc_configs`` là object ⇒ băm JSON khoá sắp, vốn không phụ thuộc thứ tự. Khoá ``state`` (``ok`` / mã lỗi) giữ phân biệt cấu
    hình THIẾU với cấu hình HỎNG ngay trong vật liệu băm."""
    if not isinstance(applied_rules, dict):
        return RequiredDocuments(
            None, DOCUMENT_CONFIG_MISSING, {"state": DOCUMENT_CONFIG_MISSING, "kind": type(applied_rules).__name__}
        )
    raw_configs = applied_rules.get("doc_configs", CONFIG_KEY_ABSENT)
    material = {
        "mandatory_docs": _sorted_if_code_list(applied_rules.get("mandatory_docs", CONFIG_KEY_ABSENT)),
        "doc_configs": {
            str(k): (v.get("is_mandatory", CONFIG_KEY_ABSENT) if isinstance(v, dict) else {"raw": v})
            for k, v in raw_configs.items()
        }
        if isinstance(raw_configs, dict)
        else raw_configs,
    }

    def _result(codes: Optional[Tuple[str, ...]], error: Optional[str]) -> RequiredDocuments:
        return RequiredDocuments(codes, error, {**material, "state": error or "ok"})

    if "mandatory_docs" not in applied_rules or "doc_configs" not in applied_rules:
        return _result(None, DOCUMENT_CONFIG_MISSING)
    mandatory = applied_rules["mandatory_docs"]
    configs = applied_rules["doc_configs"]
    if not isinstance(mandatory, list) or not all(isinstance(c, str) and c.strip() for c in mandatory):
        return _result(None, DOCUMENT_CONFIG_INVALID)
    if len(set(mandatory)) != len(mandatory):
        return _result(None, DOCUMENT_CONFIG_INVALID)
    if not isinstance(configs, dict):
        return _result(None, DOCUMENT_CONFIG_INVALID)
    marked = set()
    for code, item in configs.items():
        if not isinstance(item, dict) or type(item.get("is_mandatory")) is not bool:
            return _result(None, DOCUMENT_CONFIG_INVALID)
        if item["is_mandatory"] is True:
            marked.add(code)
    if set(mandatory) != marked:
        return _result(None, DOCUMENT_CONFIG_INVALID)
    return _result(tuple(sorted(mandatory)), None)


def _sorted_if_code_list(value: object) -> object:
    """Danh sách mà MỌI phần tử là chuỗi ⇒ bản ĐÃ SẮP (giữ phần tử trùng); giá trị khác (khoá vắng, kiểu sai) giữ nguyên — cho
    vật liệu băm của :func:`required_document_codes`."""
    if isinstance(value, list) and all(isinstance(c, str) for c in value):
        return sorted(value)
    return value


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


#: Câu 1 owner 19-11 (``gd2\QUYET-DINH-OWNER-GD2-0-A-BON-CAU-2026-11-19.md``) — MỘT chỗ duy nhất quyết TỆP minh chứng không
#: rõ người tải có được đi đường ngoại lệ "cam kết + lý do" như nút lẻ giấy tờ GĐ1b (N1b A′) hay chặn hẳn tới khi tải lại.
#: ``True`` = giống GĐ1b (mặc định đang cài). Đảo thành ``False`` ⇒ tệp không rõ người tải bị chặn kể cả khi có cam kết; giấy
#: (không tệp) không rõ người nhận vẫn đi ngoại lệ (câu 2). Mỗi chiều có test riêng.
UNKNOWN_UPLOADER_ACK_ALLOWED: bool = True

#: Nguồn của "người gắn với minh chứng" (giống ``DocFacts`` của giấy tờ: có tệp ⇒ người tải; không tệp ⇒ người nhận giấy).
RECEIVER_UPLOAD = "upload"
RECEIVER_PAPER = "paper"
#: Không có dòng giấy minh chứng nào (duyệt theo hồ sơ giấy mà chưa ghi nhận người nhận — mọi lần duyệt giấy trước bản sửa).
RECEIVER_NONE = "none"


@dataclass(frozen=True)
class PriorityEvidenceFacts:
    """Sự kiện về dòng giấy minh chứng của MỘT mã diện (``profile_document`` ``category = 'priority_evidence'``).

    "Người gắn với minh chứng" (gọi tắt người nhận) = ``uploaded_by`` nếu dòng CÓ tệp; = ``paper_submitted_by`` nếu dòng KHÔNG
    tệp (đã ghi nhận bản giấy). Cột NULL ⇒ "không rõ" kể cả khi cờ chưa bật; KHÔNG suy người từ nhật ký (owner 19-11).
    Không có dòng ⇒ không rõ người nhận (``RECEIVER_NONE``)."""

    has_file: bool
    receiver_kind: str
    receiver_id: Optional[int]
    receiver_unknown: bool

    @classmethod
    def from_row(cls, doc) -> "PriorityEvidenceFacts":
        if doc is None:
            return cls(has_file=False, receiver_kind=RECEIVER_NONE, receiver_id=None, receiver_unknown=True)
        if getattr(doc, "file_path", None):
            rid, flag, kind = getattr(doc, "uploaded_by", None), getattr(doc, "uploaded_by_unknown", False), RECEIVER_UPLOAD
            has_file = True
        else:
            rid, flag = getattr(doc, "paper_submitted_by", None), getattr(doc, "paper_submitted_by_unknown", False)
            kind, has_file = RECEIVER_PAPER, False
        return cls(has_file=has_file, receiver_kind=kind, receiver_id=rid, receiver_unknown=bool(flag) or rid is None)


def decide_priority_evidence(action: str, *, actor_id: int, evidence: PriorityEvidenceFacts) -> Decision:
    """C1(a) + câu 2, 3 owner 19-11: người tải tệp / người nhận bản giấy KHÔNG tự duyệt và KHÔNG tự từ chối minh chứng ấy
    (cùng luật ``_receiver_gate`` của giấy tờ — §4.2 GĐ1b). Không rõ người nhận ⇒ chỉ đi được đường ngoại lệ có cam kết +
    lý do (``requires_ack`` — câu 1, N1b A′); tệp không rõ người tải theo cờ :data:`UNKNOWN_UPLOADER_ACK_ALLOWED`. Cam kết
    KHÔNG mở đường khi người nhận đã biết là chính người bấm (xét trước)."""
    if action not in (ACTION_VERIFY, ACTION_REJECT):
        raise ValueError(action)
    if not evidence.receiver_unknown and evidence.receiver_id == actor_id:
        return Decision(False, OWN_SUBMISSION)
    if evidence.receiver_unknown:
        if evidence.has_file and not UNKNOWN_UPLOADER_ACK_ALLOWED:
            return Decision(False, UNKNOWN_SUBMITTER)
        return Decision(True, None, requires_ack=True)
    return Decision(True)


def priority_evidence_paper_recordable(policy: DocumentActionPolicy, *, has_row: bool) -> bool:
    """GĐ2-F1 — người xem có được ghi nhận minh chứng ưu tiên nộp bằng BẢN GIẤY cho một mã diện không: chỉ khi mã CHƯA có
    dòng giấy nào (như ``paper_submitted`` của giấy tờ: chỉ từ ``missing``) và vị từ "ghi nhận bản giấy" của giấy tờ cho
    phép (hồ sơ ở trạng thái cho sửa giấy + cán bộ phụ trách / Quản lý trong đơn vị / Admin — ``DocumentActionPolicy``).

    MỘT nguồn cho cờ ``priority_evidence_documents[*].can_mark_paper_submitted`` VÀ cổng route
    ``admission_service.mark_priority_evidence_paper_submitted`` (gọi sau các kiểm có câu báo riêng)."""
    return (not has_row) and policy.authorize("paper_submitted", "missing", False)


def priority_evidence_ack_satisfied(decision: Decision, *, unknown_submitter_ack: bool, reason: Optional[str]) -> bool:
    """Đường ngoại lệ có cam kết (giống ``transition_document``: ``requires_ack and not (unknown_submitter_ack and reason)``
    ⇒ chặn): cờ cam kết TƯỜNG MINH + lý do khác rỗng sau khi bỏ khoảng trắng hai đầu. MỘT nguồn cho duyệt và từ chối."""
    if not decision.requires_ack:
        return True
    return bool(unknown_submitter_ack) and bool((reason or "").strip())


def _reviewed(entry) -> bool:
    return isinstance(entry, dict) and entry.get("status") in PRIORITY_EVIDENCE_REVIEWED_STATUSES


def _review_identity(entry: dict) -> Tuple:
    return (entry.get("status"), entry.get("verified_by"), entry.get("rejected_by"), entry.get("document_id"))


#: Trường của mục minh chứng mà CHỈ đường duyệt / từ chối / tải lên được ghi (người duyệt, người từ chối, dòng giấy gắn với
#: lần duyệt, cờ "duyệt theo bản giấy"). Mục CHƯA qua người duyệt gửi qua PUT hồ sơ thường phải để trống các trường này.
_REVIEW_ONLY_FIELDS = (
    "document_id", "verified_by", "verified_at", "rejected_by", "rejected_at", "reject_reason", "paper_only_verification",
)


def merge_profile_evidence_update(current: Optional[dict], incoming: Optional[dict]) -> Tuple[dict, list]:
    """Đường cập nhật hồ sơ thường (``PUT /api/admissions/{id}``, ``AdmissionProfileUpdate.priority_object_evidence``)
    KHÔNG được đặt / đổi / bỏ trạng thái đã qua người duyệt — lối vào thứ hai của "tự duyệt" (C1) — và KHÔNG được gắn dòng
    giấy / cờ "duyệt theo bản giấy" / người duyệt vào mục chưa duyệt (câu 2 owner 19-11). Người nhận giấy / người tải nằm ở
    ``profile_document`` — đường PUT này không ghi bảng ấy.

    Trả ``(bản ghi sẽ lưu, danh sách mã vi phạm)``. Vi phạm = mã mà (i) bản hiện tại HOẶC bản gửi lên ở trạng thái đã duyệt /
    từ chối và hai bản khác nhau ở (trạng thái, người duyệt, người từ chối, dòng giấy); hoặc (ii) bản gửi lên CHƯA duyệt mà
    mang giá trị ở một trường chỉ đường duyệt được ghi. Gửi lại NGUYÊN mục đã duyệt là hợp lệ, và bản lưu giữ ĐÚNG mục hiện
    tại (không nhận các trường khác của thân gửi lên cho mục ấy)."""
    cur = dict(current or {})
    inc = dict(incoming or {})
    bad = []
    for code in sorted(set(cur) | set(inc)):
        c, n = cur.get(code), inc.get(code)
        if not _reviewed(c) and not _reviewed(n):
            if isinstance(n, dict) and any(n.get(k) for k in _REVIEW_ONLY_FIELDS):
                bad.append(code)
            continue
        if _reviewed(c) and _reviewed(n) and _review_identity(c) == _review_identity(n):
            continue
        bad.append(code)
    merged = dict(inc)
    for code, c in cur.items():
        if _reviewed(c):
            merged[code] = c
    return merged, bad
