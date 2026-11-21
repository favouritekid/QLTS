# app/services/admission_review_rules.py
"""GĐ2-B — luật THUẦN của máy xét mới (lần xét nháp → "Kiểm hồ sơ"): điều kiện hồ sơ E1–E7, ưu tiên dân tộc v2, xét nguyện
vọng theo ``display_order``, đề xuất theo Q1, bốn tab + mã, ``row_hash``, ``quota_view``, cảnh báo / cờ.

Nguồn (thắng theo thứ tự): biên bản owner K1–K4 21-11 (+ phụ lục 5 điểm) và biên bản A13 21-11 > QĐB 20-11, QĐO1, QĐH1 > đặc tả
GĐ2-B bản 4 (§6.1–§6.7, §9.4) + hợp đồng API bản 4 (§3.5, §4). Mọi hàm ở đây KHÔNG đọc CSDL, KHÔNG ghi gì, KHÔNG import FastAPI:
lượt đọc ảnh chụp (``admission_review_run_service`` — L3b) nạp dữ kiện theo lô vào các dataclass dưới rồi gọi :func:`evaluate_run`.

**Một nguồn (CLAUDE.md §7)** — mỗi câu hỏi đi qua ĐÚNG hàm đang trả lời nó ở GĐ1 / cổng nhập học / T6:

* E2 học phí HK1 — ``fee_gate_rules.evaluate_selected_fee`` (chung với cổng nhập học, K2);
* E4 cấu hình giấy — ``document_review_rules.required_document_codes``;
* E5 + E6 — ``council_set_gate_service.row_block_reason(…, mode=GATE_MODE_REVIEW)`` (mã ``thieu_ma_ho_so`` của E5 cũng do hàm này
  sinh — một nguồn với bản in GĐ1);
* E7 — ``council_set_gate_service.decision_state_block_reason`` (trừ dấu AppSheet ⇒ cờ);
* cổng nguyện vọng — ``admission_choice_engine_service.evaluate_choice_gates`` (chung với T6; KHÔNG áp điểm chuẩn — Q4);
* điểm so sàn = điểm in — ``council_document_render_service.compute_printed_scores`` (trần 2,75 ``PRIORITY_CAP_V1`` — QĐB:22);
  điểm KV / đối tượng in theo luật đường xét — ``printed_area_score`` / ``printed_priority_score`` của cổng GĐ1;
* "dân tộc Kinh hoặc trống" — ``council_candidate_repository.is_kinh_or_blank`` (cùng hằng với chữ SQL bản in);
* mức đối tượng cao nhất — ``priority_service.best_code_by_rate``;
* tập trạng thái "chiếm chỗ" (E1 nhóm Phê duyệt cũ + cờ A13) — ``quota_occupancy_service.OCCUPYING_STATUSES`` (owner chốt 21-11:
  A13 dùng CHUNG 5 trạng thái của bộ đếm; trỏ thẳng, không giữ bản riêng).

Không gọi, không chép đường vượt chỉ tiêu của nút Phê duyệt cũ (``_assert_quota_or_bypass``) — BT42; không gọi ``evaluate_cascade``,
``publish_result``, ``freeze_priority_snapshot``, ``transition`` — BT25 (test AST khoá).

Quy ước dòng (giữ đúng CHECK của L1 ``app/models/admission_review.py``): ``per_choice = []`` KHI VÀ CHỈ KHI hồ sơ trượt điều kiện hồ
sơ E1–E7 (kể cả ngoài tập xét) — khi ấy ``ethnic_priority_state`` và ``review_total`` là ``None``; tab ``auto`` / ``needs_decision``
⇔ có NV được xếp.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.models.finance.fee import FeeStatusEnum
from app.repositories.council_candidate_repository import is_kinh_or_blank
from app.services import council_set_gate_service as set_gate
from app.services import fee_gate_rules
from app.services import quota_occupancy_service as _qos
from app.services.admission_choice_engine_service import (
    choice_scoring_config_complete,
    evaluate_choice_gates,
)
from app.services.admission_scoring_service import DisqualificationReason, ProfileStatus
from app.services.council_document_render_service import compute_printed_scores
from app.services.document_review_rules import (
    DOCUMENT_CONFIG_INVALID,
    DOCUMENT_CONFIG_MISSING,
    required_document_codes,
)
from app.services.priority_service import RATE_TABLE_OBJECT, best_code_by_rate
from app.utils.exceptions import ChoiceTargetLevelNotConfigured, PriorityRateNotConfigured

#: Nhãn bộ luật ghi vào ``admission_review_run.rule_version`` (hợp đồng §3.3 — chuỗi mờ).
RULE_VERSION = "gd2b-1"
#: Tiền tố của vật liệu băm ``row_hash`` — đổi khi đổi cách dựng vật liệu.
ROW_HASH_VERSION = "gd2b-row-v1"

# ═══════════════════════════════════════════ danh mục giá trị (hợp đồng §4) ═══════════════════════════════════════════
TAB_AUTO = "auto"
TAB_NEEDS_DECISION = "needs_decision"
TAB_NOT_PASSED = "not_passed"
TAB_INELIGIBLE = "ineligible"
#: Đúng thứ tự hiển thị của E9.
REVIEW_TABS: Tuple[str, ...] = (TAB_AUTO, TAB_NEEDS_DECISION, TAB_NOT_PASSED, TAB_INELIGIBLE)

ETHNIC_NOT_APPLICABLE = "not_applicable"
ETHNIC_FULL_EVIDENCE = "full_evidence"
ETHNIC_PROVISIONAL_BY_COMMUNE = "provisional_by_commune"
ETHNIC_UNDETERMINED = "undetermined"
ETHNIC_PRIORITY_STATES: Tuple[str, ...] = (
    ETHNIC_NOT_APPLICABLE,
    ETHNIC_FULL_EVIDENCE,
    ETHNIC_PROVISIONAL_BY_COMMUNE,
    ETHNIC_UNDETERMINED,
)

CHOICE_PASSED_FLOOR = "passed_floor"
CHOICE_BELOW_FLOOR = "below_floor"
CHOICE_FAILED_GATE = "failed_gate"
CHOICE_CONFIG_MISSING = "config_missing"
CHOICE_QUOTA_CLOSED = "quota_closed"
CHOICE_NOT_CONSIDERED = "not_considered"
CHOICE_NOT_REACHED = "not_reached"
CHOICE_STATUSES: Tuple[str, ...] = (
    CHOICE_PASSED_FLOOR,
    CHOICE_BELOW_FLOOR,
    CHOICE_FAILED_GATE,
    CHOICE_CONFIG_MISSING,
    CHOICE_QUOTA_CLOSED,
    CHOICE_NOT_CONSIDERED,
    CHOICE_NOT_REACHED,
)

# ── mã lý do (hợp đồng §4.7) ─────────────────────────────────────────────────────────────────────────────────────────
STATUS_NOT_IN_POOL = "status_not_in_pool"
LEGACY_APPROVED_WITHOUT_DECISION = "legacy_approved_without_decision"
LEGACY_ENGINE_STATE = "legacy_engine_state"
TUITION_NOT_CLEARED = "tuition_not_cleared"
APPLICATION_FEE_NOT_CLEARED = "application_fee_not_cleared"
MANDATORY_DOCUMENT_MISSING = "mandatory_document_missing"
MANDATORY_DOCUMENT_NOT_VERIFIED = "mandatory_document_not_verified"
ACADEMIC_INFO_DELETED = "academic_info_deleted"
QUOTA_NOT_CONFIGURED = "quota_not_configured"
GROUP_MISSING = "group_missing"
FLOOR_MISSING = "floor_missing"
CHOICE_CONFIG_INCOMPLETE = "choice_config_incomplete"
TARGET_LEVEL_NOT_CONFIGURED = "target_level_not_configured"
ALL_CHOICES_FAILED = "all_choices_failed"
QUOTA_CLOSED = "quota_closed"
OVER_MAJOR_QUOTA = "over_major_quota"
TIE_AT_LAST_SEAT = "tie_at_last_seat"
TUITION_MAJOR_MISMATCH = "tuition_major_mismatch"
ETHNIC_PRIORITY_UNDETERMINED = "ethnic_priority_undetermined"
#: Mã của ``per_choice[].reason_codes`` khi tổng điểm dưới sàn.
BELOW_FLOOR = "below_floor"
#: Mã E8 — thuộc GĐ2-C (bảng giữ chỗ); GĐ2-B KHÔNG sinh.
RESERVED_IN_OTHER_SESSION = "reserved_in_other_session"

# ── cờ (hợp đồng §4.8) ──────────────────────────────────────────────────────────────────────────────────────────────
FLAG_RESIDENCE_PROOF_MISSING = "residence_proof_missing"
FLAG_APPSHEET_MARK = "dau_trung_tuyen_appsheet"
FLAG_QUOTA_CLOSED = "quota_closed"
FLAG_OFFERING_INACTIVE = "offering_inactive"
FLAG_MAJOR_INACTIVE = "major_inactive"
FLAG_SAME_CITIZEN_PREVIOUS_YEAR = "same_citizen_admitted_previous_year"
FLAG_SELECTED_IN_OTHER_DRAFT_SESSION = "selected_in_other_draft_session"
FLAG_ETHNIC_PRIORITY_UNDETERMINED = "ethnic_priority_undetermined"

# ── gợi ý (hợp đồng §4.9) ───────────────────────────────────────────────────────────────────────────────────────────
HINT_ADMIT_OVER_MAJOR_QUOTA = "admit_over_major_quota"
HINT_CONSIDER_NEXT_CHOICE = "consider_next_choice"
HINT_DEFER_SUPPLEMENT = "defer_supplement"
HINT_ADMIT_WITHOUT_ETHNIC_BONUS = "admit_without_ethnic_bonus"

# ── trạng thái học vụ ở ``quota_view`` (hợp đồng §4.10) + cảnh báo (§4.11) ─────────────────────────────────────────────
QUOTA_STATE_OK = "ok"
QUOTA_STATE_CLOSED = "quota_closed"
QUOTA_STATE_NOT_CONFIGURED = "quota_not_configured"
QUOTA_STATE_FLOOR_MISSING = "floor_missing"
QUOTA_STATE_GROUP_MISSING = "group_missing"
QUOTA_STATE_DELETED = "deleted"

WARNING_QUOTA_TABLE_NOT_LOCKED = "quota_table_not_locked"
WARNING_GROUP_CEILING_WOULD_EXCEED = "group_ceiling_would_exceed"
WARNING_QUOTA_CLOSED_PRESENT = "quota_closed_present"

#: Câu hiển thị gợi ý (đặc tả §6.7; QĐB:17; QĐO1:10; [ĐX] cho ba mã P1) — giao diện có thể dùng làm câu mặc định.
REASON_MESSAGES: Dict[str, str] = {
    QUOTA_NOT_CONFIGURED: "Ngành chưa có chỉ tiêu",
    QUOTA_CLOSED: "Ngành đã đóng tuyển (chỉ tiêu 0)",
    DOCUMENT_CONFIG_MISSING: "Hồ sơ thiếu cấu hình giấy tờ bắt buộc",
    DOCUMENT_CONFIG_INVALID: "Cấu hình giấy tờ bắt buộc của hồ sơ không hợp lệ",
    MANDATORY_DOCUMENT_MISSING: "Chưa có giấy bắt buộc",
}
#: Câu hiển thị cờ A13 (owner K4 21-11), kèm năm + căn cứ ở ``prior_year_findings`` (:class:`PriorYearFinding`; phụ lục kỹ thuật
#: đợt 1 §1).
SAME_CITIZEN_PREVIOUS_YEAR_MESSAGE = "Có hồ sơ chiếm chỗ hoặc có Quyết định trúng tuyển ở năm trước"

# ═══════════════════════════════════════════ tập trạng thái hồ sơ (§6.1) ═══════════════════════════════════════════
#: Tập xét — được xét E2–E7 rồi xét nguyện vọng.
POOL_STATUSES: Tuple[str, ...] = ("submitted", "resubmitted", "reviewing")
#: "Yêu cầu bổ sung" — có dòng, ``ineligible`` ``status_not_in_pool``.
REVISION_REQUESTED_STATUS = "revision_requested"
#: Đã "Phê duyệt" kiểu cũ — CHÍNH tập chiếm chỗ của bộ đếm (đặc tả §6.1 trỏ ``OCCUPYING_STATUSES``). Cùng đối tượng, không chép.
LEGACY_APPROVED_STATUSES = _qos.OCCUPYING_STATUSES
#: Luồng nguyện vọng cũ — ``legacy_engine_state`` (QĐB:24, liệt kê riêng).
LEGACY_ENGINE_STATUSES: Tuple[str, ...] = ("result_published", "waitlisted")
#: Không có dòng trong run (nháp, đã từ chối, đang rút, đã rút).
NO_ROW_STATUSES: Tuple[str, ...] = ("draft", "rejected", "withdrawal_pending", "withdrawn")
#: Cờ A13: trạng thái "chiếm chỗ" của hồ sơ năm trước = CHÍNH tập của bộ đếm (owner 21-11 — một nguồn; đổi bộ đếm thì A13 đổi theo).
PRIOR_YEAR_OCCUPYING_STATUSES = _qos.OCCUPYING_STATUSES

#: Mã E6 MỨC NGUYỆN VỌNG — áp cho NV đang xét ⇒ DỪNG ở NV ấy (§6.2 E6, §6.5 bước 6). Mọi mã E6 khác là MỨC HỒ SƠ.
E6_CHOICE_LEVEL_CODES: FrozenSet[str] = frozenset(
    {"khong_xac_dinh_luat_cong_diem_kv", "khong_xac_dinh_luat_cong_diem_ut", "diem_hai_nguon_khac"}
)
#: Mã E7 chặn (``decision_state_block_reason`` trừ dấu AppSheet — dấu chỉ là cờ ở lần xét; LXM:38).
E7_APPSHEET_CODE = "dau_trung_tuyen_appsheet"

#: Giấy khai sinh — bước 1 của ưu tiên dân tộc v2 (cùng mã bản in ``council_candidate_repository`` CTE ``giay``).
BIRTH_CERTIFICATE_DOC_CODE = "giay_khai_sinh"
#: Giấy xác nhận thông tin về cư trú — mã có trong mã nguồn (``admission_service`` chú thích; migration ``optdocmat01``). Lượt đọc
#: phải kiểm loại giấy này CÓ trong ``config_document_type`` (thiếu ⇒ 503 ``residence_proof_doc_type_missing``) rồi mới gọi.
RESIDENCE_PROOF_DOC_CODE = "giay_xac_nhan_cu_tru"
#: Mã đối tượng ưu tiên của em dân tộc thiểu số theo hộ khẩu (xã thường trú KV1 hay không) — cùng chữ cột ``ut_ma`` của bản in.
ETHNIC_OBJECT_CODE_KV1 = "01"
ETHNIC_OBJECT_CODE_OTHER = "06"
ETHNIC_OBJECT_CODES: FrozenSet[str] = frozenset({ETHNIC_OBJECT_CODE_KV1, ETHNIC_OBJECT_CODE_OTHER})
KV1_AREA_CODE = "KV1"

DOCUMENT_STATUS_VERIFIED = "verified"
DOCUMENT_STATUS_REJECTED = "rejected"

#: Trạng thái cổng nguyện vọng (kết quả :func:`choice_gate_facts`).
GATE_PASSED = "passed"
GATE_FAILED = "failed"
GATE_CONFIG_INCOMPLETE = "config_incomplete"
GATE_TARGET_LEVEL_NOT_CONFIGURED = "target_level_not_configured"
GATE_STATUSES: Tuple[str, ...] = (GATE_PASSED, GATE_FAILED, GATE_CONFIG_INCOMPLETE, GATE_TARGET_LEVEL_NOT_CONFIGURED)

#: Căn cứ của cờ A13.
#: Căn cứ của cờ A13 (phụ lục kỹ thuật đợt 1 §1 — giá trị ``basis`` của ``prior_year_findings``).
A13_BASIS_OCCUPYING = "occupying_status"
A13_BASIS_ADMISSION_DECISION = "admission_decision"
A13_BASES: Tuple[str, ...] = (A13_BASIS_ADMISSION_DECISION, A13_BASIS_OCCUPYING)

_CENT = Decimal("0.01")


class ReviewInputError(ValueError):
    """Dữ kiện đầu vào tự mâu thuẫn (lỗi của lượt đọc, không phải của hồ sơ) — dừng cả run, KHÔNG đoán. Thông điệp chỉ id / mã."""


# ═══════════════════════════════════════════ dữ kiện đầu vào ═══════════════════════════════════════════
@dataclass(frozen=True)
class DocumentRowFacts:
    """Một dòng giấy thường (``profile_document`` ``category = 'path'``; tối đa một dòng / loại — ``uq_profile_document_path``)."""

    document_id: int
    status: str
    row_version: Optional[int] = None
    verified_format: Optional[str] = None


@dataclass(frozen=True)
class FeeFacts:
    """Một khoản phí đã chọn (học phí HK1) hoặc một khoản lệ phí (``application``, không huỷ)."""

    fee_id: Optional[int]
    status: str
    paid_amount: Optional[Decimal] = None


@dataclass(frozen=True)
class ChoiceGateFacts:
    """Kết quả cổng của MỘT nguyện vọng ở chế độ lần xét (:func:`choice_gate_facts`)."""

    status: str
    reason_codes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ChoiceFacts:
    """Một nguyện vọng của hồ sơ.

    ``check``: dữ kiện E6 MỨC NV (dựng bằng :func:`choice_check` từ dữ kiện hồ sơ — ``nv_in_*`` = NV này, ``luat_kv`` / ``luat_ut``
    của đường xét NV). ``subject_total``: tổng điểm các môn của tổ hợp đã chọn của CHÍNH NV ấy (``profile_choice_score`` — một hàm
    đọc chung với bản in; KHÔNG phải ``final_score`` của engine — BT12). ``application_fee_free``: đường xét có ô
    ``application_fee`` trống HOẶC 0 (QĐO1:11); NV không có đường xét ⇒ ``False`` (không chứng minh được "không thu")."""

    choice_id: int
    display_order: int
    admission_path_id: Optional[int]
    offering_academic_info_id: Optional[int]
    major_id: Optional[int]
    gate: ChoiceGateFacts
    check: set_gate.CheckData
    subject_total: Optional[Decimal]
    application_fee_free: bool


@dataclass(frozen=True)
class AcademicInfoFacts:
    """Một học vụ (ngành × loại hình × năm) — ``annual_quota``: ``None`` = chưa cấu hình, ``0`` = đóng tuyệt đối. ``used_*``: bộ
    đếm Phần A + B (một câu SQL — §7.1); ``used`` = số bộ đếm trả (số lớn hơn của hai cách đếm). Nhãn chỉ để hiển thị (không băm)."""

    offering_academic_info_id: int
    academic_year: int
    offering_id: Optional[int]
    annual_quota: Optional[int]
    group_id: Optional[int]
    is_deleted: bool = False
    offering_inactive: bool = False
    major_inactive: bool = False
    used_publish: int = 0
    used_approved: int = 0
    used: int = 0
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    offering_type: Optional[str] = None


@dataclass(frozen=True)
class GroupFacts:
    """Một nhóm ngành của bảng chỉ tiêu năm (trần ``ceiling`` NOT NULL — GĐ2-A); ``used_*`` theo ``count_by_group``."""

    group_id: int
    code: str
    name: str
    ceiling: int
    used_publish: int = 0
    used_approved: int = 0
    used: int = 0


@dataclass(frozen=True)
class PriorYearProfileFacts:
    """Một hồ sơ CÙNG CCCD ở năm tuyển sinh NHỎ HƠN năm của lần xét (cờ A13 — K4). ``has_effective_decision``: có dòng Quyết định
    trúng tuyển còn hiệu lực ĐÃ GHI TRONG PHẦN MỀM (Quyết định chỉ có trên giấy KHÔNG tính)."""

    academic_year: int
    status: str
    has_effective_decision: bool


@dataclass(frozen=True)
class ProfileFacts:
    """Dữ kiện của MỘT hồ sơ năm Y, đọc trong CÙNG ảnh chụp của run.

    * ``check``: dữ kiện E6 MỨC HỒ SƠ + E7 (đúng ``CheckData`` của GĐ1; ``so_nv`` = số dòng nguyện vọng; ``hp_co`` /
      ``hp_nganh_id`` = khoản học phí HK1 ĐÃ CHỌN theo K2 — cùng khoản với ``tuition_fee``).
    * ``tuition_fee``: khoản HK1 đã chọn (chưa huỷ, ``id`` lớn nhất — mệnh đề của bản in); ``None`` = không có khoản.
    * ``application_fees``: các khoản lệ phí (``application``) KHÔNG huỷ.
    * ``applied_rules``: ảnh chụp ``admission_profile.applied_rules`` NGUYÊN (không tự điền khoá thiếu).
    * ``path_documents``: {mã loại giấy: dòng giấy thường}.
    * ``ethnicity_name``: đã ``COALESCE`` như ``council_candidate_repository.SQL_ETHNICITY_NAME``.
    * ``commune_area_code``: KV của xã thường trú tra theo NĂM CỦA LẦN XÉT (``_lookup_commune_kv`` — bản theo lô); ``None`` = không
      tra ra.
    * ``verified_object_codes``: mã diện ưu tiên có minh chứng ĐÃ DUYỆT theo luật GĐ2-0 (CB3 C6).
    """

    profile_id: int
    status: str
    check: set_gate.CheckData
    tuition_fee: Optional[FeeFacts]
    application_fees: Tuple[FeeFacts, ...]
    applied_rules: Any
    path_documents: Mapping[str, DocumentRowFacts]
    ethnicity_name: Optional[str]
    permanent_commune_code: Optional[str]
    commune_area_code: Optional[str]
    verified_object_codes: Tuple[str, ...]
    choices: Tuple[ChoiceFacts, ...]
    prior_year_profiles: Tuple[PriorYearProfileFacts, ...] = ()


@dataclass(frozen=True)
class RunFacts:
    """Dữ kiện chung của run. ``floors``: mức sàn của lần xét {học vụ: điểm} — GIÁ TRỊ chụp lúc chạy (P4). ``object_rates``: mọi mức
    đối tượng ĐANG MỞ của năm {mã: điểm} (thiếu mã cần dùng ⇒ ``PriorityRateNotConfigured`` — chỉ khi THẬT SỰ cần, phụ lục điểm 3).
    ``other_draft_auto_profile_ids``: hồ sơ ở tab ``auto`` của run ``done`` MỚI NHẤT của mỗi lần xét nháp KHÁC cùng năm (phụ lục
    điểm 1 — cờ A19)."""

    academic_year: int
    fee_gate_mode: str
    floors: Mapping[int, Decimal]
    academic_infos: Mapping[int, AcademicInfoFacts]
    groups: Tuple[GroupFacts, ...]
    quota_table_status: str
    object_rates: Mapping[str, Decimal]
    residence_proof_doc_code: str = RESIDENCE_PROOF_DOC_CODE
    other_draft_auto_profile_ids: FrozenSet[int] = frozenset()


# ═══════════════════════════════════════════ kết quả ═══════════════════════════════════════════
@dataclass(frozen=True)
class ScoreParts:
    """Điểm của MỘT nguyện vọng — mọi phần đã làm tròn hai chữ số qua chuỗi ``"%.2f"`` (§6.3). ``area`` / ``object`` CHƯA trần;
    ``priority_total`` đã trần 2,75; ``review_total`` = điểm in."""

    subject_total: Decimal
    area: Decimal
    object: Decimal
    priority_total: Decimal
    review_total: Decimal

    def as_json(self) -> Dict[str, str]:
        return {
            "subject_total": format_score(self.subject_total),
            "area": format_score(self.area),
            "object": format_score(self.object),
            "priority_total": format_score(self.priority_total),
        }


@dataclass(frozen=True)
class ChoiceOutcome:
    """Một phần tử ``per_choice`` (hợp đồng ``PerChoiceOut``)."""

    choice_id: int
    display_order: int
    offering_academic_info_id: Optional[int]
    status: str
    reason_codes: Tuple[str, ...] = ()
    review_total: Optional[Decimal] = None
    floor_score: Optional[Decimal] = None

    def as_json(self) -> Dict[str, Any]:
        return {
            "choice_id": self.choice_id,
            "display_order": self.display_order,
            "offering_academic_info_id": self.offering_academic_info_id,
            "status": self.status,
            "reason_codes": sorted(self.reason_codes),
            "review_total": format_score(self.review_total),
            "floor_score": format_score(self.floor_score),
        }


@dataclass(frozen=True)
class ConsideredChoice:
    """NV được xếp (hợp đồng ``considered_choice``) — luôn thuộc học vụ chỉ tiêu > 0. Nhãn là nhãn LÚC CHẠY."""

    choice_id: int
    display_order: int
    offering_academic_info_id: int
    offering_id: int
    admission_path_id: int
    major_id: int
    major_code: Optional[str]
    major_name: Optional[str]
    offering_type: Optional[str]


@dataclass(frozen=True)
class EthnicDecision:
    """Kết quả bảng quyết định ưu tiên dân tộc v2 (§6.4) — đúng MỘT trạng thái. ``object_code`` = ``01`` / ``06`` khi được cộng."""

    state: str
    object_code: Optional[str] = None
    residence_proof_missing: bool = False


@dataclass(frozen=True)
class PriorYearFinding:
    """Một phần tử ``prior_year_findings`` (phụ lục kỹ thuật đợt 1 §1): năm + căn cứ + trạng thái hồ sơ cũ (``status`` CHỈ khi căn
    cứ là ``occupying_status``; ``None`` khi căn cứ là Quyết định hiệu lực ghi trong phần mềm). KHÔNG có mã hồ sơ cũ, họ tên, CCCD."""

    year: int
    basis: str
    status: Optional[str] = None

    def as_json(self) -> Dict[str, Any]:
        return {"year": self.year, "basis": self.basis, "status": self.status}


@dataclass(frozen=True)
class DocumentCondition:
    """E4: mã trượt (đã sắp) + ``document_gaps`` (``None`` khi E4 đạt HOẶC cấu hình mất / hỏng)."""

    reason_codes: Tuple[str, ...]
    document_gaps: Optional[Dict[str, List[str]]]
    required_codes: Tuple[str, ...]
    #: Phần ảnh chụp cấu hình giấy ĐÃ DÙNG (``RequiredDocuments.material``) — vật liệu ``row_hash``.
    config_material: Any = None


@dataclass(frozen=True)
class ProfileEvaluation:
    """Kết quả của MỘT hồ sơ TRƯỚC bước xếp (§6.6). ``profile_codes`` khác rỗng ⇔ trượt điều kiện hồ sơ E1–E7."""

    facts: ProfileFacts
    profile_codes: Tuple[str, ...]
    document: DocumentCondition
    ethnic: Optional[EthnicDecision]
    per_choice: Tuple[ChoiceOutcome, ...]
    stop_codes: Tuple[str, ...]
    placed: Optional[ConsideredChoice]
    placed_scores: Optional[ScoreParts]
    placed_floor: Optional[Decimal]
    quota_closed_hit: bool


@dataclass(frozen=True)
class SeatOutcome:
    """Vị trí của một em trong học vụ được xếp (§6.6 bước 2–3)."""

    rank_in_major: int
    within_seats: bool
    seat_reason: Optional[str]  # None (trong số chỗ) | TIE_AT_LAST_SEAT | OVER_MAJOR_QUOTA


@dataclass(frozen=True)
class ReviewRow:
    """Một dòng kết quả (một em trong một run) — :meth:`column_values` = cột của ``admission_review_row`` (trừ ``id`` / ``run_id``)."""

    profile_id: int
    profile_status: str
    tab: str
    reason_codes: Tuple[str, ...]
    flags: Tuple[str, ...]
    decision_hints: Tuple[str, ...]
    document_gaps: Optional[Dict[str, List[str]]]
    considered: Optional[ConsideredChoice]
    scores: Optional[ScoreParts]
    floor_score: Optional[Decimal]
    rank_in_major: Optional[int]
    within_seats: Optional[bool]
    ethnic_priority_state: Optional[str]
    per_choice: Tuple[ChoiceOutcome, ...]
    prior_year_findings: Tuple[PriorYearFinding, ...]
    row_hash: str

    def column_values(self) -> Dict[str, Any]:
        c, s = self.considered, self.scores
        return {
            "profile_id": self.profile_id,
            "profile_status": self.profile_status,
            "tab": self.tab,
            "reason_codes": list(self.reason_codes),
            "flags": list(self.flags),
            "decision_hints": list(self.decision_hints),
            "document_gaps": self.document_gaps,
            "prior_year_findings": [f.as_json() for f in self.prior_year_findings],
            "considered_choice_id": c.choice_id if c else None,
            "considered_display_order": c.display_order if c else None,
            "considered_offering_academic_info_id": c.offering_academic_info_id if c else None,
            "considered_offering_id": c.offering_id if c else None,
            "considered_admission_path_id": c.admission_path_id if c else None,
            "considered_major_code": c.major_code if c else None,
            "considered_major_name": c.major_name if c else None,
            "considered_offering_type": c.offering_type if c else None,
            "subject_total": s.subject_total if s else None,
            "area_score": s.area if s else None,
            "object_score": s.object if s else None,
            "priority_total": s.priority_total if s else None,
            "review_total": s.review_total if s else None,
            "floor_score": self.floor_score,
            "rank_in_major": self.rank_in_major,
            "within_seats": self.within_seats,
            "ethnic_priority_state": self.ethnic_priority_state,
            "per_choice": [o.as_json() for o in self.per_choice],
            "row_hash": self.row_hash,
        }


@dataclass(frozen=True)
class RunEvaluation:
    rows: Tuple[ReviewRow, ...]
    quota_view: Dict[str, Any]
    summary: Dict[str, Any]


# ═══════════════════════════════════════════ tiện ích ═══════════════════════════════════════════
def format_score(value: Optional[Decimal]) -> Optional[str]:
    """Chuỗi điểm đúng hai chữ số (hợp đồng §1.4 — ``^\\d{1,3}\\.\\d{2}$``); ``None`` giữ ``None``."""
    if value is None:
        return None
    return format(Decimal(value).quantize(_CENT), "f")


def _d2(value: float) -> Decimal:
    """Làm tròn hai chữ số DẠNG CHUỖI ``"%.2f"`` rồi đổi sang ``Decimal`` — đúng cách bản in in điểm (§6.3)."""
    return Decimal("%.2f" % value)


def _sorted_unique(codes: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted(set(codes)))


# ═══════════════════════════════════════════ E1 — tập xét (§6.1) ═══════════════════════════════════════════
def has_row(status: str) -> bool:
    """Hồ sơ có dòng trong run không (nháp / đã từ chối / đang rút / đã rút ⇒ không). Trạng thái lạ ⇒ :class:`ReviewInputError`."""
    if status in NO_ROW_STATUSES:
        return False
    if (
        status in POOL_STATUSES
        or status == REVISION_REQUESTED_STATUS
        or status in LEGACY_APPROVED_STATUSES
        or status in LEGACY_ENGINE_STATUSES
    ):
        return True
    raise ReviewInputError("Trạng thái hồ sơ không thuộc tập nào của lần xét: %r" % (status,))


def pool_status_codes(status: str, *, has_effective_decision: bool) -> Tuple[str, ...]:
    """E1 — mã trượt "trạng thái thuộc tập xét" (§6.1). Hồ sơ chiếm chỗ CÓ Quyết định hiệu lực ⇒ mã do E7 sinh
    (``da_co_quyet_dinh``), ở đây trả rỗng."""
    if status in POOL_STATUSES:
        return ()
    if status == REVISION_REQUESTED_STATUS:
        return (STATUS_NOT_IN_POOL,)
    if status in LEGACY_APPROVED_STATUSES:
        return () if has_effective_decision else (LEGACY_APPROVED_WITHOUT_DECISION,)
    if status in LEGACY_ENGINE_STATUSES:
        return (LEGACY_ENGINE_STATE,)
    raise ReviewInputError("Trạng thái hồ sơ không có dòng trong lần xét: %r" % (status,))


# ═══════════════════════════════════════════ E3 — lệ phí theo hồ sơ ═══════════════════════════════════════════
def application_fee_cleared(application_fees: Sequence[FeeFacts], choices_fee_free: Sequence[bool]) -> bool:
    """E3 (QĐB:20; QĐO1:11) — theo HỒ SƠ, không theo từng NV:

    1. hơn một khoản lệ phí (không huỷ) ⇒ chưa đạt (dữ liệu lỗi — fail-closed như ``_load_application_fee``);
    2. một khoản ``paid`` / ``waived`` ⇒ đạt; ``partial`` ⇒ chưa đạt;
    3. MỌI NV thuộc đường xét có ô lệ phí trống hoặc 0 ⇒ đạt (không có NV nào ⇒ KHÔNG chứng minh được ⇒ chưa đạt);
    4. còn lại ⇒ chưa đạt."""
    if len(application_fees) > 1:
        return False
    if application_fees:
        status = application_fees[0].status
        if status in (FeeStatusEnum.paid.value, FeeStatusEnum.waived.value):
            return True
        if status == FeeStatusEnum.partial.value:
            return False
    return bool(choices_fee_free) and all(choices_fee_free)


# ═══════════════════════════════════════════ E4 — giấy bắt buộc ═══════════════════════════════════════════
def document_condition(applied_rules: Any, path_documents: Mapping[str, DocumentRowFacts]) -> DocumentCondition:
    """E4 hai bước (§6.2): (1) cấu hình giấy hợp lệ — ``required_document_codes`` (MỘT nguồn); mất / hỏng ⇒ mã cấu hình,
    ``document_gaps = None``, KHÔNG sang bước 2; (2) đối chiếu TỪNG mã bắt buộc với dòng giấy thường: không có dòng ⇒
    ``mandatory_document_missing``; có dòng mà trạng thái ≠ ``verified`` (kể cả ``paper_submitted``) ⇒
    ``mandatory_document_not_verified``. Giấy không bắt buộc / ngoài cấu hình không chặn."""
    required = required_document_codes(applied_rules)
    if required.error is not None:
        return DocumentCondition((required.error,), None, (), required.material)
    codes = required.codes or ()
    missing = sorted(c for c in codes if c not in path_documents)
    not_verified = sorted(
        c for c in codes if c in path_documents and path_documents[c].status != DOCUMENT_STATUS_VERIFIED
    )
    reasons: List[str] = []
    if missing:
        reasons.append(MANDATORY_DOCUMENT_MISSING)
    if not_verified:
        reasons.append(MANDATORY_DOCUMENT_NOT_VERIFIED)
    gaps = {"missing": missing, "not_verified": not_verified} if reasons else None
    return DocumentCondition(tuple(sorted(reasons)), gaps, tuple(codes), required.material)


# ═══════════════════════════════════════════ E5 + E6 + E7 ═══════════════════════════════════════════
def e6_profile_codes(check: set_gate.CheckData) -> Tuple[str, ...]:
    """E5 + E6 mức HỒ SƠ — ``row_block_reason`` chế độ lần xét, bỏ mã mức NV (xét ở :func:`e6_choice_codes`)."""
    codes = set_gate.row_block_reason(check, mode=set_gate.GATE_MODE_REVIEW)
    return _sorted_unique(c for c in codes if c not in E6_CHOICE_LEVEL_CODES)


def e6_choice_codes(check: set_gate.CheckData) -> Tuple[str, ...]:
    """E6 mức NGUYỆN VỌNG — ``row_block_reason`` chế độ lần xét trên dữ kiện của NV, chỉ giữ mã mức NV."""
    codes = set_gate.row_block_reason(check, mode=set_gate.GATE_MODE_REVIEW)
    return _sorted_unique(c for c in codes if c in E6_CHOICE_LEVEL_CODES)


def e7_codes(check: set_gate.CheckData) -> Tuple[str, ...]:
    """E7 — Quyết định GHI TRONG PHẦN MỀM còn hiệu lực / chờ Admin quyết chặn; dấu AppSheet KHÔNG chặn (cờ)."""
    return _sorted_unique(c for c in set_gate.decision_state_block_reason(check) if c != E7_APPSHEET_CODE)


def choice_check(
    profile_check: set_gate.CheckData,
    *,
    choice_id: int,
    major_id: Optional[int],
    admission_path_id: Optional[int],
    subject_group_id: Optional[int],
    offering_academic_info_id: Optional[int],
    offering_id: Optional[int],
    area_rule: Optional[str],
    object_rule: Optional[str],
    score_both_differ: int = 0,
    score_only_choice: int = 0,
    score_only_profile: int = 0,
) -> set_gate.CheckData:
    """Dữ kiện E6 MỨC NV = dữ kiện hồ sơ với phần "nguyện vọng in" thay bằng NV đang xét (§6.2 E6: "gọi cho từng NV đang
    xét"). ``area_rule`` / ``object_rule``: luật cộng điểm của đường xét NV (``cong`` / ``tat`` / ``khong_co_luat`` / ``None``).
    ``score_*``: số môn của tổ hợp NV lệch giữa hai bảng điểm (khuôn ``SQL_CHECK_SOURCE`` CTE ``diem``)."""
    return dataclasses.replace(
        profile_check,
        nv_in_id=choice_id,
        nv_in_nganh_id=major_id,
        nv_in_path_id=admission_path_id,
        nv_in_sg_id=subject_group_id,
        nv_in_ai_id=offering_academic_info_id,
        nv_in_offering_id=offering_id,
        luat_kv=area_rule,
        luat_ut=object_rule,
        diem_ca_hai_khac=score_both_differ,
        diem_chi_nv=score_only_choice,
        diem_chi_hs=score_only_profile,
    )


# ═══════════════════════════════════════════ cổng nguyện vọng (§6.5 bước 6–7) ═══════════════════════════════════════════
def choice_gate_facts(profile: Any, choice: Any) -> ChoiceGateFacts:
    """Cổng điều kiện của MỘT nguyện vọng ở chế độ lần xét — dùng CHUNG ``evaluate_choice_gates`` với T6 (không chép luật). Đối
    tượng ``profile`` / ``choice`` phải đã nạp sẵn chuỗi quan hệ (không đọc CSDL ở đây; thiếu chuỗi ⇒ ``T6ChainNotLoaded`` nổi lên).

    * thiếu đường xét / tiêu chí / tổ hợp không có môn ⇒ :data:`GATE_CONFIG_INCOMPLETE` (bước 6 — kiểm TRƯỚC cổng điều kiện);
    * thiếu cấu hình trình độ / loại hình ⇒ :data:`GATE_TARGET_LEVEL_NOT_CONFIGURED` (bước 6);
    * trượt cổng (trình độ văn hoá, điểm TB tối thiểu — QĐB:21, đủ môn, điểm liệt, tổ hợp sai, không điểm) ⇒ :data:`GATE_FAILED`
      với ĐÚNG mã của engine;
    * còn lại ⇒ :data:`GATE_PASSED`. Điểm chuẩn (``BELOW_MIN_SCORE``) KHÔNG áp (Q4): không đọc cờ ``passed`` của
      ``calculate_score`` — chỉ đọc ``status`` hợp lệ / không hợp lệ."""
    if getattr(choice, "admission_path", None) is None or not choice_scoring_config_complete(choice):
        return ChoiceGateFacts(GATE_CONFIG_INCOMPLETE, (CHOICE_CONFIG_INCOMPLETE,))
    try:
        outcome = evaluate_choice_gates(profile, choice)
    except ChoiceTargetLevelNotConfigured:
        return ChoiceGateFacts(GATE_TARGET_LEVEL_NOT_CONFIGURED, (TARGET_LEVEL_NOT_CONFIGURED,))
    if outcome.reason_codes:
        return ChoiceGateFacts(GATE_FAILED, tuple(outcome.reason_codes))
    result = outcome.score_result
    if result is None:
        if not outcome.has_subject_scores:
            return ChoiceGateFacts(GATE_FAILED, (DisqualificationReason.NO_VALID_SCORES.value,))
        return ChoiceGateFacts(GATE_CONFIG_INCOMPLETE, (CHOICE_CONFIG_INCOMPLETE,))
    if result.status == ProfileStatus.INVALID:
        codes = tuple(c for c in result.disqualification_codes if c != DisqualificationReason.BELOW_MIN_SCORE.value)
        return ChoiceGateFacts(GATE_FAILED, codes or (DisqualificationReason.NO_VALID_SCORES.value,))
    return ChoiceGateFacts(GATE_PASSED, ())


# ═══════════════════════════════════════════ ưu tiên dân tộc v2 (§6.4) ═══════════════════════════════════════════
def ethnic_priority(
    *,
    ethnicity_name: Optional[str],
    birth_certificate: Optional[DocumentRowFacts],
    permanent_commune_code: Optional[str],
    commune_area_code: Optional[str],
    residence_proof: Optional[DocumentRowFacts],
) -> EthnicDecision:
    """Bảng quyết định LOẠI TRỪ NHAU (P2) — đi từ trên xuống, dừng ở dòng đầu tiên khớp; CHỈ gọi cho hồ sơ đã qua E1–E7.

    0. Kinh hoặc trống (vị từ một nguồn với bản in) ⇒ ``not_applicable``;
    1. khai sinh chưa ``verified`` / không có dòng ⇒ ``undetermined`` (H1 = A — QĐH1);
    2. mã xã trống hoặc không tra ra KV theo năm của lần xét ⇒ ``undetermined``;
    3. giấy cư trú ``rejected`` ⇒ ``undetermined``;
    4. giấy cư trú ``verified`` ⇒ ``full_evidence`` (``01`` nếu xã KV1, không thì ``06``);
    5. giấy cư trú chưa có dòng / đang chờ ⇒ ``provisional_by_commune`` (tạm cộng như 4) + cờ ``residence_proof_missing``."""
    if is_kinh_or_blank(ethnicity_name):
        return EthnicDecision(ETHNIC_NOT_APPLICABLE)
    if birth_certificate is None or birth_certificate.status != DOCUMENT_STATUS_VERIFIED:
        return EthnicDecision(ETHNIC_UNDETERMINED)
    if not (permanent_commune_code or "").strip() or commune_area_code is None:
        return EthnicDecision(ETHNIC_UNDETERMINED)
    residence_status = residence_proof.status if residence_proof is not None else None
    if residence_status == DOCUMENT_STATUS_REJECTED:
        return EthnicDecision(ETHNIC_UNDETERMINED)
    code = ETHNIC_OBJECT_CODE_KV1 if commune_area_code == KV1_AREA_CODE else ETHNIC_OBJECT_CODE_OTHER
    if residence_status == DOCUMENT_STATUS_VERIFIED:
        return EthnicDecision(ETHNIC_FULL_EVIDENCE, code)
    return EthnicDecision(ETHNIC_PROVISIONAL_BY_COMMUNE, code, residence_proof_missing=True)


def object_score_text(
    ethnic: EthnicDecision,
    verified_object_codes: Sequence[str],
    rates: Mapping[str, Decimal],
    *,
    academic_year: int,
) -> str:
    """Điểm đối tượng (CHƯA trần) khi luật đường xét BẬT cộng đối tượng: mức cao nhất (``best_code_by_rate`` — TT: một diện cao
    nhất) giữa phần dân tộc v2 (``01`` / ``06`` khi được cộng) và các diện khác ĐÃ DUYỆT. Mã ``01`` / ``06`` khai trong diện khác
    KHÔNG tính lần hai [ĐX]. Không diện nào ⇒ ``"0"``. Thiếu mức đang mở của mã cần dùng ⇒ ``PriorityRateNotConfigured`` (cả run 503)."""
    codes: List[str] = []
    if ethnic.object_code is not None:
        codes.append(ethnic.object_code)
    for c in verified_object_codes:
        if c not in ETHNIC_OBJECT_CODES and c not in codes:
            codes.append(c)
    if not codes:
        return set_gate.PRIORITY_SCORE_NOT_ADDED
    missing = [c for c in codes if c not in rates]
    if missing:
        raise PriorityRateNotConfigured(table=RATE_TABLE_OBJECT, academic_year=academic_year, missing_codes=missing)
    picked = {c: Decimal(rates[c]) for c in codes}
    return str(picked[best_code_by_rate(picked, codes)])


# ═══════════════════════════════════════════ điểm — một hàm với bản in (§6.3) ═══════════════════════════════════════════
def review_score(subject_total: Decimal, area_text: str, object_text: str) -> ScoreParts:
    """``review_total`` = ``compute_printed_scores(...).admission_total`` (điểm IN — trần 2,75), làm tròn qua ``"%.2f"``."""
    printed = compute_printed_scores(str(subject_total), area_text, object_text)
    return ScoreParts(
        subject_total=_d2(printed.subject_total),
        area=_d2(printed.area),
        object=_d2(printed.priority),
        priority_total=_d2(printed.priority_total),
        review_total=_d2(printed.admission_total),
    )


def meets_floor(review_total: Decimal, floor_score: Decimal) -> bool:
    """Bằng sàn là ĐẠT (QĐB:15) — so trên ``Decimal`` hai chữ số."""
    return Decimal(review_total) >= Decimal(floor_score)


def choice_score(
    choice: ChoiceFacts, profile: ProfileFacts, ethnic: EthnicDecision, run: RunFacts
) -> ScoreParts:
    """Điểm của MỘT NV: tổng môn của tổ hợp NV + điểm KV theo luật đường xét (``printed_area_score``) + điểm đối tượng theo công tắc
    (``printed_priority_score``; mức chỉ tra khi công tắc BẬT — phụ lục điểm 3)."""
    if choice.subject_total is None:
        raise ReviewInputError("NV %s qua cổng mà không có tổng điểm môn." % choice.choice_id)
    area_text = set_gate.printed_area_score(choice.check)
    if area_text is None:
        raise ReviewInputError("NV %s không xác định được điểm KV mà không có mã E6." % choice.choice_id)
    if choice.check.luat_ut == set_gate.AREA_RULE_ADD:
        raw_object = object_score_text(
            ethnic, profile.verified_object_codes, run.object_rates, academic_year=run.academic_year
        )
    else:
        raw_object = set_gate.PRIORITY_SCORE_NOT_ADDED
    object_text = set_gate.printed_priority_score(choice.check.luat_ut, raw_object)
    if object_text is None:
        raise ReviewInputError("NV %s không xác định được điểm đối tượng mà không có mã E6." % choice.choice_id)
    return review_score(choice.subject_total, area_text, object_text)


# ═══════════════════════════════════════════ hồ sơ — E1–E7 rồi nguyện vọng ═══════════════════════════════════════════
def _ordered_choices(choices: Iterable[ChoiceFacts]) -> List[ChoiceFacts]:
    return sorted(choices, key=lambda c: (c.display_order, c.choice_id))


def profile_condition_codes(profile: ProfileFacts, run: RunFacts) -> Tuple[Tuple[str, ...], DocumentCondition]:
    """Mọi mã trượt E1–E7 của hồ sơ (ghi ĐỦ, không dừng ở mã đầu — J1 dòng 3; CB3 A5) + kết quả E4."""
    check = profile.check
    if (profile.tuition_fee is not None) != bool(check.hp_co):
        raise ReviewInputError("Hồ sơ %s: khoản học phí HK1 lệch dữ kiện E6." % profile.profile_id)
    if check.so_nv != len(profile.choices):
        raise ReviewInputError("Hồ sơ %s: số nguyện vọng lệch dữ kiện E6." % profile.profile_id)
    codes: Set[str] = set(pool_status_codes(profile.status, has_effective_decision=check.qd_hieu_luc_id is not None))
    # E2 — chế độ đã kiểm ở đầu run; không có khoản ⇒ mã ``thieu_hoc_phi_hk1`` của E6.
    if profile.tuition_fee is not None:
        verdict = fee_gate_rules.evaluate_selected_fee(
            run.fee_gate_mode, status=profile.tuition_fee.status, paid_amount=profile.tuition_fee.paid_amount
        )
        if not verdict.cleared:
            codes.add(TUITION_NOT_CLEARED)
    # E3
    if not application_fee_cleared(profile.application_fees, [c.application_fee_free for c in profile.choices]):
        codes.add(APPLICATION_FEE_NOT_CLEARED)
    # E4
    document = document_condition(profile.applied_rules, profile.path_documents)
    codes.update(document.reason_codes)
    # E5 + E6 mức hồ sơ
    codes.update(e6_profile_codes(check))
    # E7
    codes.update(e7_codes(check))
    if profile.status not in POOL_STATUSES and not codes:
        raise ReviewInputError("Hồ sơ %s ngoài tập xét mà không có mã E1–E7." % profile.profile_id)
    return tuple(sorted(codes)), document


def evaluate_profile(profile: ProfileFacts, run: RunFacts) -> Optional[ProfileEvaluation]:
    """Một hồ sơ TRƯỚC bước xếp. ``None`` ⇔ hồ sơ không có dòng (§6.1).

    Trượt BẤT KỲ điều kiện E1–E7 ⇒ dừng: không ưu tiên, không điểm, ``per_choice`` rỗng (P2). Qua hết ⇒ ưu tiên v2 rồi xét từng NV
    theo ``display_order`` (rồi ``id``) đúng thứ tự §6.5."""
    if not has_row(profile.status):
        return None
    profile_codes, document = profile_condition_codes(profile, run)
    if profile_codes:
        return ProfileEvaluation(profile, profile_codes, document, None, (), (), None, None, None, False)
    if not profile.choices:
        # Không tới được khi dữ kiện nhất quán (E6 sinh ``nhieu_nv_khong_co_nv`` / ``mot_nv_khong_co_dong_nguyen_vong``). Đặc tả
        # CHƯA nói ca này ⇒ KHÔNG tự đặt luật (bàn giao L2) — dừng cả run.
        raise ReviewInputError("Hồ sơ %s qua E1–E7 mà không có nguyện vọng." % profile.profile_id)
    ethnic = ethnic_priority(
        ethnicity_name=profile.ethnicity_name,
        birth_certificate=profile.path_documents.get(BIRTH_CERTIFICATE_DOC_CODE),
        permanent_commune_code=profile.permanent_commune_code,
        commune_area_code=profile.commune_area_code,
        residence_proof=profile.path_documents.get(run.residence_proof_doc_code),
    )
    outcomes: List[ChoiceOutcome] = []
    stop_codes: Tuple[str, ...] = ()
    placed: Optional[ConsideredChoice] = None
    placed_scores: Optional[ScoreParts] = None
    placed_floor: Optional[Decimal] = None
    quota_closed_hit = False
    for choice in _ordered_choices(profile.choices):
        ai_id = choice.offering_academic_info_id
        if placed is not None:
            outcomes.append(ChoiceOutcome(choice.choice_id, choice.display_order, ai_id, CHOICE_NOT_CONSIDERED))
            continue
        if stop_codes:
            outcomes.append(ChoiceOutcome(choice.choice_id, choice.display_order, ai_id, CHOICE_NOT_REACHED))
            continue
        outcome, scores, ai = _evaluate_choice(choice, profile, ethnic, run)
        outcomes.append(outcome)
        if outcome.status == CHOICE_CONFIG_MISSING:
            stop_codes = outcome.reason_codes
        elif outcome.status == CHOICE_QUOTA_CLOSED:
            quota_closed_hit = True
        elif outcome.status == CHOICE_PASSED_FLOOR:
            placed = ConsideredChoice(
                choice_id=choice.choice_id,
                display_order=choice.display_order,
                offering_academic_info_id=ai.offering_academic_info_id,
                offering_id=ai.offering_id,
                admission_path_id=choice.admission_path_id,
                major_id=choice.major_id,
                major_code=ai.major_code,
                major_name=ai.major_name,
                offering_type=ai.offering_type,
            )
            placed_scores, placed_floor = scores, outcome.floor_score
    return ProfileEvaluation(
        profile, (), document, ethnic, tuple(outcomes), stop_codes, placed, placed_scores, placed_floor, quota_closed_hit
    )


def _evaluate_choice(
    choice: ChoiceFacts, profile: ProfileFacts, ethnic: EthnicDecision, run: RunFacts
) -> Tuple[ChoiceOutcome, Optional[ScoreParts], Optional[AcademicInfoFacts]]:
    """§6.5 bước 1–9 cho MỘT NV (gặp ô nào thì dừng xét NV ấy). Phụ lục điểm 2: đứt chuỗi TRƯỚC học vụ (thiếu đường xét / học vụ)
    ⇒ ``choice_config_incomplete`` ngay."""
    cid, order, ai_id = choice.choice_id, choice.display_order, choice.offering_academic_info_id

    def stop(codes: Sequence[str], floor: Optional[Decimal] = None) -> Tuple[ChoiceOutcome, None, None]:
        return ChoiceOutcome(cid, order, ai_id, CHOICE_CONFIG_MISSING, _sorted_unique(codes), None, floor), None, None

    if choice.gate.status not in GATE_STATUSES:
        raise ReviewInputError("NV %s: trạng thái cổng lạ %r." % (cid, choice.gate.status))
    if choice.admission_path_id is None or ai_id is None:
        return stop((CHOICE_CONFIG_INCOMPLETE,))
    ai = run.academic_infos.get(ai_id)
    if ai is None:
        raise ReviewInputError("Thiếu dữ kiện học vụ %s của NV %s." % (ai_id, cid))
    if ai.is_deleted:  # bước 1
        return stop((ACADEMIC_INFO_DELETED,))
    if ai.annual_quota is None:  # bước 2 — chưa cấu hình ⇒ DỪNG (QĐB:17)
        return stop((QUOTA_NOT_CONFIGURED,))
    if ai.annual_quota < 0:
        raise ReviewInputError("Học vụ %s có chỉ tiêu âm." % ai_id)
    if ai.annual_quota == 0:  # bước 3 — đóng tuyệt đối, xét tiếp NV kế (QĐB:16, QĐO1:9)
        return ChoiceOutcome(cid, order, ai_id, CHOICE_QUOTA_CLOSED, (QUOTA_CLOSED,)), None, None
    if ai.group_id is None:  # bước 4
        return stop((GROUP_MISSING,))
    floor = run.floors.get(ai_id)
    if floor is None:  # bước 5
        return stop((FLOOR_MISSING,))
    floor = Decimal(floor)
    step6: List[str] = []  # bước 6
    if ai.offering_id is None or choice.major_id is None or choice.gate.status == GATE_CONFIG_INCOMPLETE:
        step6.append(CHOICE_CONFIG_INCOMPLETE)
    if choice.gate.status == GATE_TARGET_LEVEL_NOT_CONFIGURED:
        step6.append(TARGET_LEVEL_NOT_CONFIGURED)
    step6.extend(e6_choice_codes(choice.check))
    if step6:
        return stop(step6, floor)
    if choice.gate.status == GATE_FAILED:  # bước 7 — sang NV kế
        return ChoiceOutcome(cid, order, ai_id, CHOICE_FAILED_GATE, _sorted_unique(choice.gate.reason_codes), None, floor), None, None
    scores = choice_score(choice, profile, ethnic, run)  # bước 8–9
    if not meets_floor(scores.review_total, floor):
        return ChoiceOutcome(cid, order, ai_id, CHOICE_BELOW_FLOOR, (BELOW_FLOOR,), scores.review_total, floor), None, None
    return ChoiceOutcome(cid, order, ai_id, CHOICE_PASSED_FLOOR, (), scores.review_total, floor), scores, ai


# ═══════════════════════════════════════════ xếp theo Q1 (§6.6) ═══════════════════════════════════════════
def seats_left(ai: AcademicInfoFacts) -> int:
    """Chỗ còn S(X) = chỉ tiêu năm − đã dùng (Phần A + B), nhỏ nhất 0. Chỉ gọi cho học vụ chỉ tiêu > 0."""
    if ai.annual_quota is None:
        raise ReviewInputError("Học vụ %s chưa cấu hình chỉ tiêu." % ai.offering_academic_info_id)
    return max(int(ai.annual_quota) - int(ai.used), 0)


def rank_major(scores: Mapping[int, Decimal], seats: int) -> Dict[int, SeatOutcome]:
    """Xếp các em của MỘT học vụ (§6.6 bước 2–3): tổng điểm GIẢM DẦN; NV1 / NV2 bình đẳng; KHÔNG dùng id hồ sơ, giờ nộp, thứ tự NV
    hay thứ tự nào khác để phân hạng. ``rank_in_major`` = hạng xếp liền (bằng điểm cùng hạng) [ĐX: hạng dày 1, 1, 2].

    |L| ≤ S ⇒ mọi em trong số chỗ. S = 0 ⇒ mọi em ``over_major_quota``. |L| > S ≥ 1: t = điểm em thứ S; em thứ S + 1 cũng có t ⇒ MỌI
    em điểm t ``tie_at_last_seat``, em điểm > t trong số chỗ; không thì S em đầu trong số chỗ; còn lại ``over_major_quota``."""
    if seats < 0:
        raise ValueError("Số chỗ còn âm.")
    distinct = sorted(set(Decimal(v) for v in scores.values()), reverse=True)
    rank_of = {v: i + 1 for i, v in enumerate(distinct)}
    ordered = sorted((Decimal(v) for v in scores.values()), reverse=True)
    out: Dict[int, SeatOutcome] = {}
    n = len(ordered)
    t: Optional[Decimal] = None
    tie = False
    if 0 < seats < n:
        t = ordered[seats - 1]
        tie = ordered[seats] == t
    for pid, value in scores.items():
        v = Decimal(value)
        rank = rank_of[v]
        if n <= seats:
            out[pid] = SeatOutcome(rank, True, None)
        elif seats == 0:
            out[pid] = SeatOutcome(rank, False, OVER_MAJOR_QUOTA)
        elif tie:
            if v > t:
                out[pid] = SeatOutcome(rank, True, None)
            elif v == t:
                out[pid] = SeatOutcome(rank, False, TIE_AT_LAST_SEAT)
            else:
                out[pid] = SeatOutcome(rank, False, OVER_MAJOR_QUOTA)
        else:
            out[pid] = SeatOutcome(rank, v >= t, None if v >= t else OVER_MAJOR_QUOTA)
    return out


def rank_placements(evaluations: Sequence[ProfileEvaluation], run: RunFacts) -> Dict[int, SeatOutcome]:
    """Xếp TỪNG học vụ độc lập (mỗi em chỉ ở một học vụ) — {id hồ sơ: vị trí}."""
    by_ai: Dict[int, Dict[int, Decimal]] = {}
    for e in evaluations:
        if e.placed is not None:
            by_ai.setdefault(e.placed.offering_academic_info_id, {})[e.facts.profile_id] = e.placed_scores.review_total
    out: Dict[int, SeatOutcome] = {}
    for ai_id, scores in by_ai.items():
        ai = run.academic_infos[ai_id]
        if not ai.annual_quota or ai.annual_quota <= 0:
            raise ReviewInputError("NV được xếp vào học vụ %s có chỉ tiêu không dương." % ai_id)
        out.update(rank_major(scores, seats_left(ai)))
    return out


# ═══════════════════════════════════════════ cờ A13 / A19 ═══════════════════════════════════════════
def same_citizen_previous_year(
    review_year: int, prior_profiles: Iterable[PriorYearProfileFacts]
) -> Tuple[PriorYearFinding, ...]:
    """Cờ A13 (K4 + biên bản A13 21-11): hồ sơ CÙNG CCCD ở MỌI năm tuyển sinh NHỎ HƠN năm Y của lần xét, thoả ít nhất một —
    (a) đang ở trạng thái chiếm chỗ theo ĐÚNG định nghĩa của bộ đếm (``quota_occupancy_service.OCCUPYING_STATUSES``) ⇒ phần tử
    ``occupying_status`` kèm trạng thái ấy; (b) có Quyết định trúng tuyển còn hiệu lực ĐÃ GHI TRONG PHẦN MỀM ⇒ phần tử
    ``admission_decision``, ``status = None``. Thứ tự: năm GIẢM dần, rồi căn cứ (phụ lục kỹ thuật đợt 1 §1); phần tử trùng gộp một.
    Chỉ để Ban thư ký đối chiếu: KHÔNG đổi tab, KHÔNG đổi chỉ tiêu. Hồ sơ năm ≥ Y ⇒ :class:`ReviewInputError` (lượt đọc phải lọc)."""
    found: Set[PriorYearFinding] = set()
    for p in prior_profiles:
        if p.academic_year >= review_year:
            raise ReviewInputError("Hồ sơ năm %s không phải năm trước năm %s." % (p.academic_year, review_year))
        if p.status in _qos.OCCUPYING_STATUSES:
            found.add(PriorYearFinding(int(p.academic_year), A13_BASIS_OCCUPYING, p.status))
        if p.has_effective_decision:
            found.add(PriorYearFinding(int(p.academic_year), A13_BASIS_ADMISSION_DECISION, None))
    return tuple(sorted(found, key=lambda f: (-f.year, f.basis, f.status or "")))


def selected_in_other_draft_session(profile_id: int, other_draft_auto_profile_ids: FrozenSet[int]) -> bool:
    """Cờ A19 (phụ lục điểm 1): hồ sơ đang ở tab ``auto`` của run ``done`` mới nhất của một lần xét nháp KHÁC cùng năm. Không chặn,
    không đổi tab."""
    return profile_id in other_draft_auto_profile_ids


# ═══════════════════════════════════════════ dựng dòng ═══════════════════════════════════════════
def _later_open_choice(evaluation: ProfileEvaluation, run: RunFacts) -> bool:
    """Em còn NV SAU NV được xếp mà học vụ có thật, chưa xoá, chỉ tiêu > 0 — gợi ý ``consider_next_choice`` không bao giờ trỏ vào
    học vụ chỉ tiêu 0 / trống [ĐX]."""
    placed = evaluation.placed
    for c in evaluation.facts.choices:
        if (c.display_order, c.choice_id) <= (placed.display_order, placed.choice_id):
            continue
        ai = run.academic_infos.get(c.offering_academic_info_id) if c.offering_academic_info_id is not None else None
        if ai is not None and not ai.is_deleted and ai.annual_quota is not None and ai.annual_quota > 0:
            return True
    return False


def _base_flags(evaluation: ProfileEvaluation, run: RunFacts, findings: Tuple[PriorYearFinding, ...]) -> Set[str]:
    flags: Set[str] = set()
    if evaluation.facts.check.dau_appsheet:
        flags.add(FLAG_APPSHEET_MARK)
    if findings:
        flags.add(FLAG_SAME_CITIZEN_PREVIOUS_YEAR)
    if selected_in_other_draft_session(evaluation.facts.profile_id, run.other_draft_auto_profile_ids):
        flags.add(FLAG_SELECTED_IN_OTHER_DRAFT_SESSION)
    if evaluation.quota_closed_hit:
        flags.add(FLAG_QUOTA_CLOSED)
    if evaluation.ethnic is not None and evaluation.ethnic.residence_proof_missing:
        flags.add(FLAG_RESIDENCE_PROOF_MISSING)
    return flags


def classify(
    evaluation: ProfileEvaluation, seat: Optional[SeatOutcome]
) -> Tuple[str, Tuple[str, ...]]:
    """Tab + mã lý do (§6.7) — chưa có gợi ý / cờ. ``auto`` chỉ khi trong số chỗ và không có ca chuyển "Cần Ban thư ký quyết"
    (Q5 lệch ngành học phí; ưu tiên dân tộc ``undetermined``) — hai ca ấy VẪN giữ chỗ tạm (QĐB:23)."""
    if evaluation.profile_codes:
        return TAB_INELIGIBLE, evaluation.profile_codes
    if evaluation.stop_codes:
        return TAB_INELIGIBLE, evaluation.stop_codes
    if evaluation.placed is None:
        codes = [ALL_CHOICES_FAILED] + ([QUOTA_CLOSED] if evaluation.quota_closed_hit else [])
        return TAB_NOT_PASSED, _sorted_unique(codes)
    if seat is None:
        raise ReviewInputError("Hồ sơ %s có NV được xếp mà chưa xếp hạng." % evaluation.facts.profile_id)
    codes: List[str] = []
    if seat.seat_reason is not None:
        codes.append(seat.seat_reason)
    if evaluation.facts.check.hp_nganh_id != evaluation.placed.major_id:
        codes.append(TUITION_MAJOR_MISMATCH)
    if evaluation.ethnic is not None and evaluation.ethnic.state == ETHNIC_UNDETERMINED:
        codes.append(ETHNIC_PRIORITY_UNDETERMINED)
    if not codes:
        return TAB_AUTO, ()
    return TAB_NEEDS_DECISION, _sorted_unique(codes)


def group_room_after_auto(rows_auto_ai_ids: Iterable[int], run: RunFacts) -> Dict[int, int]:
    """{nhóm: trần − đã dùng − số em ``auto`` của run vào các học vụ thành viên} (có thể âm — chỉ cảnh báo, QĐB:25)."""
    auto_by_group: Counter = Counter()
    for ai_id in rows_auto_ai_ids:
        gid = run.academic_infos[ai_id].group_id
        if gid is not None:
            auto_by_group[gid] += 1
    return {g.group_id: int(g.ceiling) - int(g.used) - auto_by_group[g.group_id] for g in run.groups}


def evaluate_run(profiles: Sequence[ProfileFacts], run: RunFacts) -> RunEvaluation:
    """Toàn bộ luật của MỘT run "Kiểm hồ sơ" trên dữ kiện đã đọc trong MỘT ảnh chụp. Chế độ cổng học phí kiểm TRƯỚC mọi hồ sơ
    (chế độ lạ ⇒ ``fee_gate_rules.FeeGateModeInvalid`` — nơi gọi đổi ra 503, không ghi gì)."""
    fee_gate_rules.require_fee_gate_mode(run.fee_gate_mode)
    seen: Set[int] = set()
    evaluations: List[ProfileEvaluation] = []
    for p in profiles:
        if p.profile_id in seen:
            raise ReviewInputError("Hồ sơ %s xuất hiện hai lần." % p.profile_id)
        seen.add(p.profile_id)
        e = evaluate_profile(p, run)
        if e is not None:
            evaluations.append(e)
    seats = rank_placements(evaluations, run)
    staged = []
    for e in evaluations:
        seat = seats.get(e.facts.profile_id)
        tab, reasons = classify(e, seat)
        staged.append((e, seat, tab, reasons))
    room = group_room_after_auto(
        (e.placed.offering_academic_info_id for e, _, tab, _ in staged if tab == TAB_AUTO), run
    )
    rows: List[ReviewRow] = []
    for e, seat, tab, reasons in staged:
        rows.append(_build_row(e, seat, tab, reasons, room, run))
    rows.sort(key=lambda r: r.profile_id)
    return RunEvaluation(tuple(rows), build_quota_view(rows, run), build_summary(rows, run))


def _build_row(
    e: ProfileEvaluation,
    seat: Optional[SeatOutcome],
    tab: str,
    reasons: Tuple[str, ...],
    room: Mapping[int, int],
    run: RunFacts,
) -> ReviewRow:
    findings = same_citizen_previous_year(run.academic_year, e.facts.prior_year_profiles)
    flags = _base_flags(e, run, findings)
    hints: Set[str] = set()
    if tab == TAB_NOT_PASSED and e.ethnic is not None and e.ethnic.state == ETHNIC_UNDETERMINED:
        flags.add(FLAG_ETHNIC_PRIORITY_UNDETERMINED)
    if e.placed is not None:
        ai = run.academic_infos[e.placed.offering_academic_info_id]
        if ai.offering_inactive:
            flags.add(FLAG_OFFERING_INACTIVE)
        if ai.major_inactive:
            flags.add(FLAG_MAJOR_INACTIVE)
    if tab == TAB_NEEDS_DECISION:
        ai = run.academic_infos[e.placed.offering_academic_info_id]
        if seat.seat_reason in (OVER_MAJOR_QUOTA, TIE_AT_LAST_SEAT) and room.get(ai.group_id, 0) > 0:
            hints.add(HINT_ADMIT_OVER_MAJOR_QUOTA)
        if _later_open_choice(e, run):
            hints.add(HINT_CONSIDER_NEXT_CHOICE)
        if e.ethnic is not None and e.ethnic.state == ETHNIC_UNDETERMINED:
            hints.update((HINT_DEFER_SUPPLEMENT, HINT_ADMIT_WITHOUT_ETHNIC_BONUS))
    row_fields = dict(
        profile_id=e.facts.profile_id,
        profile_status=e.facts.status,
        tab=tab,
        reason_codes=tuple(sorted(reasons)),
        flags=tuple(sorted(flags)),
        decision_hints=tuple(sorted(hints)),
        document_gaps=e.document.document_gaps,
        considered=e.placed,
        scores=e.placed_scores,
        floor_score=e.placed_floor,
        rank_in_major=seat.rank_in_major if seat is not None else None,
        within_seats=seat.within_seats if seat is not None else None,
        ethnic_priority_state=e.ethnic.state if e.ethnic is not None else None,
        per_choice=e.per_choice,
        prior_year_findings=findings,
    )
    return ReviewRow(row_hash=compute_row_hash(e, row_fields, run), **row_fields)


# ═══════════════════════════════════════════ row_hash (F209; hợp đồng §7) ═══════════════════════════════════════════
def _json_value(value: Any) -> Any:
    """JSON thuần, CHUẨN theo giá trị: ``Decimal`` ⇒ chuỗi dạng rút gọn (``15.00`` và ``15`` cùng một chữ)."""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _doc_material(doc: Optional[DocumentRowFacts]) -> Any:
    if doc is None:
        return None
    return {"id": doc.document_id, "status": doc.status, "row_version": doc.row_version, "verified_format": doc.verified_format}


def _check_material(check: set_gate.CheckData) -> Dict[str, Any]:
    data = dataclasses.asdict(check)
    data.pop("stt", None)  # số thứ tự dòng — không phải dữ liệu
    return data


def _fee_material(fee: Optional[FeeFacts]) -> Any:
    if fee is None:
        return None
    return {"id": fee.fee_id, "status": fee.status, "paid_amount": fee.paid_amount}


def _fee_sort_key(fee: FeeFacts) -> Tuple[Any, ...]:
    """Khoá sắp ổn định của một khoản phí trong vật liệu băm (khoản không có id xếp cuối)."""
    return (fee.fee_id is None, fee.fee_id or 0, str(fee.status), str(fee.paid_amount))


def row_hash_material(e: ProfileEvaluation, row_fields: Mapping[str, Any], run: RunFacts) -> Dict[str, Any]:
    """Dữ liệu CHUẨN HOÁ thực dùng của một dòng (F209; hợp đồng §7): trạng thái hồ sơ; ảnh chụp cấu hình giấy; giấy bắt buộc + hai
    giấy ưu tiên dân tộc (id / trạng thái / ``row_version`` / ``verified_format``); phí (E2 + chế độ, E3); dữ kiện E6 / E7 (khoá
    đếm, KV, luật cộng điểm); ưu tiên; từng NV (cổng, điểm môn, chỉ tiêu, nhóm, sàn); kết quả (tab, mã, NV được xếp, ``per_choice``,
    điểm, sàn, ``document_gaps``, ``prior_year_findings`` — phụ lục kỹ thuật đợt 1 §1). KHÔNG có họ tên, nhãn ngành / loại hình,
    hạng, cờ, gợi ý — đổi chúng không đổi băm."""
    p = e.facts
    docs_used = set(e.document.required_codes) | {BIRTH_CERTIFICATE_DOC_CODE, run.residence_proof_doc_code}
    choices = []
    for c in _ordered_choices(p.choices):
        ai = run.academic_infos.get(c.offering_academic_info_id) if c.offering_academic_info_id is not None else None
        choices.append(
            {
                "choice_id": c.choice_id,
                "display_order": c.display_order,
                "admission_path_id": c.admission_path_id,
                "offering_academic_info_id": c.offering_academic_info_id,
                "major_id": c.major_id,
                "gate": {"status": c.gate.status, "reason_codes": sorted(c.gate.reason_codes)},
                "check": _check_material(c.check),
                "subject_total": c.subject_total,
                "application_fee_free": c.application_fee_free,
                "academic_info": None
                if ai is None
                else {
                    "offering_id": ai.offering_id,
                    "annual_quota": ai.annual_quota,
                    "group_id": ai.group_id,
                    "is_deleted": ai.is_deleted,
                },
                "floor_score": run.floors.get(c.offering_academic_info_id) if c.offering_academic_info_id else None,
            }
        )
    considered = row_fields["considered"]
    scores = row_fields["scores"]
    return {
        "v": ROW_HASH_VERSION,
        "profile_id": p.profile_id,
        "profile_status": p.status,
        "doc_config": e.document.config_material,
        "documents": {code: _doc_material(p.path_documents.get(code)) for code in sorted(docs_used)},
        "fee_gate_mode": run.fee_gate_mode,
        "tuition_fee": _fee_material(p.tuition_fee),
        # Sắp theo ``fee_id`` (rồi trạng thái, số đã đóng) — băm KHÔNG phụ thuộc thứ tự đọc của lượt chạy.
        "application_fees": [_fee_material(f) for f in sorted(p.application_fees, key=_fee_sort_key)],
        "check": _check_material(p.check),
        "ethnic_inputs": {
            "kinh_or_blank": is_kinh_or_blank(p.ethnicity_name),
            "permanent_commune_code": p.permanent_commune_code,
            "commune_area_code": p.commune_area_code,
            "verified_object_codes": sorted(p.verified_object_codes),
        },
        "choices": choices,
        "result": {
            "tab": row_fields["tab"],
            "reason_codes": list(row_fields["reason_codes"]),
            "considered_choice_id": considered.choice_id if considered else None,
            "scores": scores.as_json() if scores else None,
            "review_total": scores.review_total if scores else None,
            "floor_score": row_fields["floor_score"],
            "ethnic_priority_state": row_fields["ethnic_priority_state"],
            "document_gaps": row_fields["document_gaps"],
            "per_choice": [o.as_json() for o in row_fields["per_choice"]],
            "prior_year_findings": [f.as_json() for f in row_fields["prior_year_findings"]],
        },
    }


def compute_row_hash(e: ProfileEvaluation, row_fields: Mapping[str, Any], run: RunFacts) -> str:
    """sha256 hex (64 ký tự — CHECK ``row_hash ~ '^[0-9a-f]{64}$'``) của JSON CHUẨN (khoá sắp, không khoảng trắng) của
    :func:`row_hash_material`."""
    material = _json_value(row_hash_material(e, row_fields, run))
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════ quota_view + summary ═══════════════════════════════════════════
def quota_state(ai: AcademicInfoFacts, has_floor: bool) -> str:
    """Trạng thái học vụ ở ``quota_view`` — cùng thứ tự với §6.5 (xoá → trống → 0 → nhóm → sàn)."""
    if ai.is_deleted:
        return QUOTA_STATE_DELETED
    if ai.annual_quota is None:
        return QUOTA_STATE_NOT_CONFIGURED
    if ai.annual_quota == 0:
        return QUOTA_STATE_CLOSED
    if ai.group_id is None:
        return QUOTA_STATE_GROUP_MISSING
    if not has_floor:
        return QUOTA_STATE_FLOOR_MISSING
    return QUOTA_STATE_OK


def build_quota_view(rows: Sequence[ReviewRow], run: RunFacts) -> Dict[str, Any]:
    """Bảng chỉ tiêu THAM KHẢO của run (hợp đồng §3.3 ``QuotaView``) — JSON thuần. Chỉ học vụ của ĐÚNG năm lần xét. ``floor_score``
    là GIÁ TRỊ lúc chạy (P4). Nhóm: ``remaining_after_auto`` có thể âm, ``would_exceed`` chỉ là cảnh báo (QĐB:25)."""
    placed: Dict[int, Counter] = {}
    for r in rows:
        if r.considered is not None:
            placed.setdefault(r.considered.offering_academic_info_id, Counter())[r.tab] += 1
    groups_by_id = {g.group_id: g for g in run.groups}
    majors = []
    for ai_id in sorted(run.academic_infos):
        ai = run.academic_infos[ai_id]
        if ai.academic_year != run.academic_year:
            continue
        counts = placed.get(ai_id, Counter())
        floor = run.floors.get(ai_id)
        group = groups_by_id.get(ai.group_id) if ai.group_id is not None else None
        majors.append(
            {
                "offering_academic_info_id": ai_id,
                "offering_id": ai.offering_id,
                "major_code": ai.major_code,
                "major_name": ai.major_name,
                "offering_type": ai.offering_type,
                "group_id": ai.group_id,
                "group_code": group.code if group is not None else None,
                "annual_admission_quota": ai.annual_quota,
                "floor_score": format_score(floor),
                "used_publish": ai.used_publish,
                "used_approved": ai.used_approved,
                "used": ai.used,
                "remaining": None if ai.annual_quota is None else max(int(ai.annual_quota) - int(ai.used), 0),
                "state": quota_state(ai, floor is not None),
                "candidates": counts[TAB_AUTO] + counts[TAB_NEEDS_DECISION],
                "auto": counts[TAB_AUTO],
                "needs_decision": counts[TAB_NEEDS_DECISION],
                "offering_inactive": ai.offering_inactive,
                "major_inactive": ai.major_inactive,
            }
        )
    room = group_room_after_auto((r.considered.offering_academic_info_id for r in rows if r.tab == TAB_AUTO), run)
    groups = []
    for g in sorted(run.groups, key=lambda x: x.group_id):
        remaining = room[g.group_id]
        groups.append(
            {
                "group_id": g.group_id,
                "code": g.code,
                "name": g.name,
                "ceiling": g.ceiling,
                "used_publish": g.used_publish,
                "used_approved": g.used_approved,
                "used": g.used,
                "auto_in_run": int(g.ceiling) - int(g.used) - remaining,
                "remaining_after_auto": remaining,
                "would_exceed": remaining < 0,
            }
        )
    return {"majors": majors, "groups": groups}


def run_warnings(rows: Sequence[ReviewRow], run: RunFacts) -> Tuple[str, ...]:
    """``summary.warnings`` (§9.4): bảng chỉ tiêu chưa khoá; nhóm sẽ vượt trần sau phần ``auto``; có học vụ (chưa xoá, đúng năm)
    chỉ tiêu 0 (``quota_closed_present`` — nhắc cổng vận hành N4, §7.4)."""
    out: Set[str] = set()
    if run.quota_table_status != "locked":
        out.add(WARNING_QUOTA_TABLE_NOT_LOCKED)
    room = group_room_after_auto((r.considered.offering_academic_info_id for r in rows if r.tab == TAB_AUTO), run)
    if any(v < 0 for v in room.values()):
        out.add(WARNING_GROUP_CEILING_WOULD_EXCEED)
    if any(
        ai.academic_year == run.academic_year and not ai.is_deleted and ai.annual_quota == 0
        for ai in run.academic_infos.values()
    ):
        out.add(WARNING_QUOTA_CLOSED_PRESENT)
    return tuple(sorted(out))


def build_summary(rows: Sequence[ReviewRow], run: RunFacts) -> Dict[str, Any]:
    """``RunSummary`` (hợp đồng §3.3) — JSON thuần, chỉ số đếm + mã (không dữ liệu cá nhân)."""
    tab_counts = {t: 0 for t in REVIEW_TABS}
    reasons: Counter = Counter()
    flags: Counter = Counter()
    for r in rows:
        tab_counts[r.tab] += 1
        reasons.update(r.reason_codes)
        flags.update(r.flags)
    return {
        "rows_total": len(rows),
        "pool_total": sum(1 for r in rows if r.profile_status in POOL_STATUSES),
        "tab_counts": tab_counts,
        "reason_counts": dict(sorted(reasons.items())),
        "flag_counts": dict(sorted(flags.items())),
        "warnings": list(run_warnings(rows, run)),
    }


def floors_snapshot(floors: Mapping[int, Decimal]) -> List[Dict[str, Any]]:
    """``inputs.floors`` của run — ẢNH CHỤP GIÁ TRỊ (P4), sắp theo học vụ."""
    return [
        {"offering_academic_info_id": int(ai_id), "floor_score": format_score(Decimal(v))}
        for ai_id, v in sorted(floors.items())
    ]
