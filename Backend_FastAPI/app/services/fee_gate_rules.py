# app/services/fee_gate_rules.py
"""Cổng học phí học kỳ 1 — MỘT hàm đánh giá **một khoản đã chọn** theo chế độ cổng (owner K2 21-11; QĐB:19).

Hai nơi hỏi cùng một câu "khoản học phí HK1 này đã đủ điều kiện chưa" và đi qua ĐÚNG hàm :func:`evaluate_selected_fee`:

* cổng nhập học ``admission_service._check_fee_gate_legacy`` / ``_check_fee_gate_semester_hk1`` (đường đang chạy production —
  GIỮ NGUYÊN cách chọn khoản: khoản đầu tiên của ``FeeRepository.get_by_profile_id``);
* máy xét mới GĐ2-B (E2 — ``admission_review_rules``; khoản do lượt đọc của lần xét chọn bằng ĐÚNG mệnh đề của bản in GĐ1:
  khoản ``tuition`` HK1 chưa huỷ có ``id`` lớn nhất — ``council_candidate_repository.SQL_PRINT_FIGURES`` CTE ``hoc_phi``).

Hàm này CHỈ đánh giá; KHÔNG chọn khoản, KHÔNG đọc CSDL, KHÔNG ném lỗi HTTP. "Chưa có khoản" là việc của nơi gọi (cổng nhập học:
400 như cũ; lần xét: mã ``thieu_hoc_phi_hk1`` của ``council_set_gate_service.row_block_reason``).

**Chế độ** (``ADMISSION_FEE_GATE_MODE`` — ``config.py``, ADR-002):

=================  ==========================================================================
``legacy``         đạt khi khoản ``paid`` hoặc ``waived``
``semester_hk1``   đạt khi ``paid``, ``waived``, HOẶC ``partial`` với ``paid_amount > 0``
khác               :class:`FeeGateModeInvalid` — **không** rơi về ``legacy`` (BT04, QĐB:19)
=================  ==========================================================================

Trước đây cổng nhập học chọn chế độ bằng ``if semester_hk1 … else legacy`` ⇒ giá trị lạ lặng lẽ thành ``legacy`` (đặc tả GĐ2-B
bản 4 §4.3, M22). Ở cổng nhập học ca ấy không xảy ra được (``Literal`` của cấu hình) — nhánh rõ từng chế độ chỉ là lớp phụ.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Tuple

from app.models.finance.fee import FeeStatusEnum
from app.services.admission_review_errors import FEE_GATE_MODE_INVALID as _REVIEW_FEE_GATE_MODE_INVALID

FEE_GATE_MODE_LEGACY = "legacy"
FEE_GATE_MODE_SEMESTER_HK1 = "semester_hk1"
#: Mọi chế độ hợp lệ — đúng hai giá trị của ``Literal`` ``ADMISSION_FEE_GATE_MODE`` (test khoá bằng nhau).
FEE_GATE_MODES: Tuple[str, ...] = (FEE_GATE_MODE_LEGACY, FEE_GATE_MODE_SEMESTER_HK1)

#: Mã lý do của lỗi chế độ = ``reason_code`` 503 ``REVIEW_CONFIG_UNAVAILABLE`` của hợp đồng API GĐ2-B §5. MỘT nguồn: danh mục
#: lỗi ``admission_review_errors`` (đợt 1 sau Codex — tên ở đây là CHÍNH đối tượng ấy; test đồng nhất ``is``).
FEE_GATE_MODE_INVALID = _REVIEW_FEE_GATE_MODE_INVALID

#: Trạng thái khoản đạt ở MỌI chế độ (đúng tuple cổng nhập học đã dùng — so bằng ``==`` như ``in (…)`` cũ).
_CLEARED_STATUSES: Tuple[str, ...] = (FeeStatusEnum.paid.value, FeeStatusEnum.waived.value)
_PARTIAL_STATUS: str = FeeStatusEnum.partial.value


class FeeGateModeInvalid(ValueError):
    """Chế độ cổng học phí không rõ / không hợp lệ. Lỗi THUẦN (không HTTP): lần xét đổi ra 503 ``REVIEW_CONFIG_UNAVAILABLE`` /
    ``fee_gate_mode_invalid`` (``admission_review_errors.fee_gate_mode_invalid``); cổng nhập học đổi ra 503 ``SERVICE_UNAVAILABLE``.
    Thông điệp không chứa giá trị cấu hình (chỉ kiểu) — không lộ cấu hình ra log khách."""

    reason_code = FEE_GATE_MODE_INVALID

    def __init__(self, mode: Any):
        super().__init__("Chế độ cổng học phí không hợp lệ (kiểu %s)." % type(mode).__name__)


def require_fee_gate_mode(mode: Any) -> str:
    """Trả ``mode`` nếu là MỘT trong :data:`FEE_GATE_MODES` (so chính xác: chuỗi, đúng chữ, không cắt khoảng trắng); còn lại ⇒
    :class:`FeeGateModeInvalid`. Lần xét gọi MỘT lần trước khi đọc hồ sơ; cổng nhập học gọi trước khi chọn nhánh."""
    if isinstance(mode, str) and mode in FEE_GATE_MODES:
        return mode
    raise FeeGateModeInvalid(mode)


#: Kết quả của một khoản: đạt vì ``paid`` / ``waived``; đạt vì đóng một phần (chỉ ``semester_hk1``); chưa đạt.
VERDICT_CLEARED = "cleared"
VERDICT_PARTIAL_ACCEPTED = "partial_accepted"
VERDICT_NOT_CLEARED = "not_cleared"


@dataclass(frozen=True)
class FeeGateVerdict:
    """Kết quả đánh giá MỘT khoản. ``verdict`` để cổng nhập học giữ nguyên hai dòng log "đạt" cũ của chế độ ``semester_hk1``."""

    verdict: str

    @property
    def cleared(self) -> bool:
        return self.verdict in (VERDICT_CLEARED, VERDICT_PARTIAL_ACCEPTED)


def evaluate_selected_fee(mode: Any, *, status: Any, paid_amount: Optional[Decimal]) -> FeeGateVerdict:
    """Đánh giá MỘT khoản học phí HK1 ĐÃ CHỌN theo chế độ cổng — MỘT nguồn cho cổng nhập học và máy xét mới (K2).

    * Chế độ kiểm TRƯỚC (:func:`require_fee_gate_mode`) — chế độ lạ ⇒ :class:`FeeGateModeInvalid`, kể cả khi khoản đã ``paid``.
    * ``legacy``: KHÔNG đọc ``paid_amount`` (giữ đúng hành vi cổng cũ — khoản ``partial`` luôn chưa đạt).
    * ``semester_hk1``: ``partial`` chỉ đạt khi ``paid_amount`` có giá trị và ``> 0``; ``paid_amount`` trống ⇒ chưa đạt
      (cột ``fee.paid_amount`` NOT NULL — nhánh này chỉ là thất bại an toàn)."""
    mode = require_fee_gate_mode(mode)
    if status in _CLEARED_STATUSES:
        return FeeGateVerdict(VERDICT_CLEARED)
    if mode == FEE_GATE_MODE_LEGACY:
        return FeeGateVerdict(VERDICT_NOT_CLEARED)
    if mode == FEE_GATE_MODE_SEMESTER_HK1:
        if status == _PARTIAL_STATUS and paid_amount is not None and paid_amount > 0:
            return FeeGateVerdict(VERDICT_PARTIAL_ACCEPTED)
        return FeeGateVerdict(VERDICT_NOT_CLEARED)
    # Không tới được (require_fee_gate_mode đã lọc) — giữ thất bại an toàn nếu ai thêm chế độ vào FEE_GATE_MODES mà quên nhánh.
    raise FeeGateModeInvalid(mode)
