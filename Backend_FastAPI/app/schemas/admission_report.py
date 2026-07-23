"""Weekly admission report schemas (lead → admission → finance, by ngành/officer).

Contract notes (locked with product owner):
- **Attribution = recomputed-current**: ngành/officer resolve theo trạng thái HIỆN
  TẠI. Số của một tuần đã qua CÓ THỂ đổi khi hồ sơ publish/đổi NV/reopen. The
  ``attribution`` field flags this for the client.
- **Week = event-based**: các chỉ số ``*_in_week`` đếm SỰ KIỆN phát sinh trong
  ``[week_start, week_end]`` (lịch sử ``changed_at`` / ``occurred_at`` / ledger
  ``created_at``), KHÔNG phải trạng thái hiện tại. ``active_current`` là metric
  TỒN (stock) tại thời điểm xem — tách riêng để tránh hiểu nhầm.
- **Money = Decimal**: serialize ra JSON string (Pydantic v2 default) để giữ
  precision; FE ``formatVND`` nhận string.
- **Buckets**: hồ sơ không quy được về đúng 1 ngành (``ambiguous`` = >1 admitted
  choice; ``unresolved`` = không có choice/offering) hoặc lead/hồ sơ chưa gán
  officer (``unassigned``) đi vào dòng riêng — KHÔNG nuốt vào ngành/officer nào.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

GroupBy = Literal["major", "officer"]
BucketKind = Literal["ambiguous", "unresolved", "unassigned"]


class WeekMeta(BaseModel):
    """ISO week (Asia/Ho_Chi_Minh). BE owns the week contract; FE does not derive it."""

    iso_year: int
    iso_week: int
    week_start: date  # Monday (VN)
    week_end: date  # Sunday (VN, inclusive)
    timezone: str = "Asia/Ho_Chi_Minh"


class LeadMetrics(BaseModel):
    new_in_week: int = 0  # leads created in [week_start, week_end]
    active_current: int = 0  # STOCK: leads at a non-final consultation status (now)
    consulting_positive_current: int = 0  # STOCK: positive consultation phase (now)


class AdmissionMetrics(BaseModel):
    # all resolved profiles in this group (even with no status history yet)
    profiles_total: int = 0
    # event = first transition INTO the milestone (status_history.occurred_at)
    submitted_in_week: int = 0
    admitted_in_week: int = 0
    enrolled_in_week: int = 0
    submitted_cumulative: int = 0
    admitted_cumulative: int = 0
    enrolled_cumulative: int = 0
    # Đã đóng lệ phí xét tuyển (application paid) NHƯNG hồ sơ CHƯA nộp (chưa có
    # milestone submitted) — nhóm prepay fast-track cần nhắc hoàn tất nộp hồ sơ.
    fee_paid_not_submitted: int = 0
    # chỉ tiêu (annual_admission_quota) — major grouping only; None for officer
    # view / buckets / total rows where a quota does not apply.
    quota: Optional[int] = None


class ConversionMetrics(BaseModel):
    """Cumulative funnel ratios (0..1); null when the denominator is 0."""

    submit_to_admit: Optional[float] = None  # admitted_cum / submitted_cum
    admit_to_enroll: Optional[float] = None  # enrolled_cum / admitted_cum


class FinanceMetrics(BaseModel):
    # ledger PaymentTransaction.created_at; payment|refund (refund stored negative).
    gross_in_week: Decimal = Decimal("0")
    refund_in_week: Decimal = Decimal("0")
    net_in_week: Decimal = Decimal("0")
    application_net_in_week: Decimal = Decimal("0")
    tuition_net_in_week: Decimal = Decimal("0")
    net_cumulative: Decimal = Decimal("0")
    profiles_paid: int = 0  # DISTINCT profiles with ≥1 cash payment (cumulative)


class ReportRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_key: Optional[int] = None  # major_id or officer_id; None for buckets/total
    label: str  # "CNTT (6480201)" / officer name / bucket label
    code: Optional[str] = None  # major code (major grouping only)
    degree_level: Optional[str] = None  # major grouping only
    is_bucket: bool = False
    bucket_kind: Optional[BucketKind] = None
    lead: LeadMetrics = Field(default_factory=LeadMetrics)
    admission: AdmissionMetrics = Field(default_factory=AdmissionMetrics)
    conversion: ConversionMetrics = Field(default_factory=ConversionMetrics)
    finance: FinanceMetrics = Field(default_factory=FinanceMetrics)


class DataQuality(BaseModel):
    """Profiles that could not be cleanly attributed (surfaced, never hidden)."""

    total_profiles: int = 0
    ambiguous_profiles: int = 0  # >1 admitted choice
    unresolved_profiles: int = 0  # no resolvable major
    unassigned_profiles: int = 0  # no officer (officer grouping)


class AdmissionWeeklyReportResponse(BaseModel):
    academic_year: int
    round_code: Optional[str] = None  # None = mọi đợt của năm
    group_by: GroupBy
    week: WeekMeta
    scope_unit_id: Optional[int] = None  # None = toàn trường (admin)
    # week numbers may shift on publish/reopen — see module docstring.
    attribution: Literal["recomputed-current"] = "recomputed-current"
    rows: list[ReportRow]
    totals: ReportRow  # aggregate across rows (label="TỔNG")
    data_quality: DataQuality = Field(default_factory=DataQuality)


class ReportFilters(BaseModel):
    """Options to populate the report filter controls (admin + manager).

    ``academic_years`` = năm có CẤU HÌNH đợt HOẶC có hồ sơ (không chỉ năm-có-hồ-sơ,
    nên năm vừa setup chưa có hồ sơ vẫn hiện). ``rounds`` = mã đợt của
    ``academic_year`` (rỗng nếu không truyền năm). Đây là catalog metadata toàn cục,
    không phải dữ liệu phạm vi đơn vị → manager đọc được (cùng cổng report).
    """

    academic_years: list[int] = Field(default_factory=list)
    rounds: list[str] = Field(default_factory=list)


# ============================================================================
# Overview dashboard extras (funnel · trend · officer×major heatmap)
# Cùng cổng report (require_admin_or_manager), cùng scope IDOR (_resolve_scope).
# ============================================================================


class ScopedReport(BaseModel):
    """Common scope echo so the client can confirm what slice it rendered."""

    academic_year: int
    round_code: Optional[str] = None  # None = mọi đợt của năm
    scope_unit_id: Optional[int] = None  # None = toàn trường


# ---- Pipeline funnel (lead theo giai đoạn pipeline hiện tại) ----------------
class FunnelStage(BaseModel):
    stage_id: str  # "stg01".. (PipelineStage.id)
    name: str
    order: int  # PipelineStage.order (0-based)
    is_final: bool  # PipelineStage.is_final_stage
    color_code: str
    current: int = 0  # lead ĐANG ở giai đoạn này (mỗi lead đúng 1 giai đoạn)
    # Mô hình phễu do BACKEND tính (FE chỉ render — thin-client):
    reached: int = 0  # lũy kế "từng đạt bậc này" trên đường phễu; bậc leak = current
    conversion_pct: Optional[float] = None  # % chuyển tiếp từ bậc path trước (0..100)
    is_leak: bool = False  # bậc rời phễu (terminal âm) — FE hiển thị tách, không thuộc path


class PipelineFunnelResponse(ScopedReport):
    total_leads: int = 0
    # Sorted by ``order``. Lead chưa gán giai đoạn gộp vào giai đoạn order thấp
    # nhất (chưa bắt đầu). ``current`` cộng = total_leads.
    stages: list[FunnelStage] = Field(default_factory=list)


# ---- Trend (chuỗi thời gian N tuần, tích luỹ) -------------------------------
class TrendPoint(BaseModel):
    iso_year: int
    iso_week: int
    week_start: date  # Monday (VN)
    week_end: date  # Sunday (VN, inclusive)
    submitted_cumulative: int = 0
    admitted_cumulative: int = 0
    enrolled_cumulative: int = 0


class AdmissionTrendResponse(ScopedReport):
    weeks: int  # số điểm trả về
    points: list[TrendPoint] = Field(default_factory=list)  # cũ → mới


# ---- Heatmap cán bộ × ngành -------------------------------------------------
class MatrixOfficer(BaseModel):
    id: Optional[int] = None  # None = "Chưa gán cán bộ" (bucket)
    name: str


class MatrixMajor(BaseModel):
    id: Optional[int] = None  # None = "Chưa phân loại ngành" (ambiguous ∪ unresolved)
    code: Optional[str] = None
    name: str
    degree_level: Optional[str] = None


class OfficerMajorCell(BaseModel):
    officer_id: Optional[int] = None
    major_id: Optional[int] = None
    enrolled: int = 0  # đã nhập học (cumulative, event-based)
    submitted: int = 0  # đã nộp hồ sơ (cumulative)


class OfficerMajorMatrixResponse(ScopedReport):
    group_by_metric: Literal["enrolled", "submitted"] = "enrolled"
    officers: list[MatrixOfficer] = Field(default_factory=list)  # hàng
    majors: list[MatrixMajor] = Field(default_factory=list)  # cột
    cells: list[OfficerMajorCell] = Field(default_factory=list)  # thưa (sparse)
