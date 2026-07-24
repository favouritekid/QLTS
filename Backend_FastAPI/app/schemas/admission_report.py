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
    # Chi tiết hoá (khớp heatmap ngành×cán bộ): hồ sơ NHÁP (status='draft') +
    # học phí HK1 đã đóng một-phần / đủ. Snapshot HIỆN TẠI (không theo cutoff tuần),
    # cùng định nghĩa với ma trận officer×major → hai bảng đối chiếu trực tiếp.
    draft: int = 0
    fee_hk1_partial: int = 0
    fee_hk1_full: int = 0
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
    current: int = 0  # lead ON-PATH ở giai đoạn này (đã loại lead rời phễu)
    # Mô hình phễu do BACKEND tính (FE chỉ render — thin-client):
    reached: int = 0  # lũy kế "từng đạt bậc này" trên đường phễu; bậc leak = current
    conversion_pct: Optional[float] = None  # % chuyển tiếp từ bậc path trước (0..100)
    is_leak: bool = False  # bậc terminal ÂM (mọi trạng thái negative) — FE ẩn khỏi path


class PipelineFunnelResponse(ScopedReport):
    total_leads: int = 0  # tổng lead của phễu = Σ on-path + leaked
    leaked: int = 0  # lead rời phễu (trạng thái final + outcome negative, mọi bậc)
    # Sorted by ``order``; lead chưa gán giai đoạn gộp vào bậc order thấp nhất.
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
    """5 chỉ số/ô để FE render 3 tab (Hồ sơ · Học phí HK1 · Nhập học).

    ``submitted``/``enrolled`` = mốc lịch sử (cumulative-to-now). ``draft`` =
    trạng thái hồ sơ HIỆN TẠI = 'draft'. ``fee_partial``/``fee_full`` = đóng học
    phí HỌC KỲ 1 (một phần / đủ) — chỉ HK1 vì là cổng nhập học của báo cáo TS.
    """

    officer_id: Optional[int] = None
    major_id: Optional[int] = None
    submitted: int = 0  # đã nộp hồ sơ (cumulative)
    draft: int = 0  # hồ sơ đang ở trạng thái 'draft' (nháp)
    fee_partial: int = 0  # đóng học phí HK1 một phần (paid>0, còn nợ)
    fee_full: int = 0  # đóng đủ học phí HK1 (remaining<=0)
    enrolled: int = 0  # đã nhập học (cumulative, event-based)


class OfficerMajorMatrixResponse(ScopedReport):
    # Hai trục; FE render ngành làm hàng, cán bộ làm cột (orientation do FE quyết).
    officers: list[MatrixOfficer] = Field(default_factory=list)
    majors: list[MatrixMajor] = Field(default_factory=list)
    cells: list[OfficerMajorCell] = Field(default_factory=list)  # thưa (sparse)


# ---- Week-over-week (biến động 2 tuần ISO ĐÃ HOÀN TẤT, loại tuần đang chạy) --
class WowMovement(BaseModel):
    """Biến động 1 milestone giữa 2 tuần ISO đã HOÀN TẤT (không tính tuần đang chạy)."""

    count_current: int = 0  # tuần hoàn tất gần nhất (W-1)
    count_previous: int = 0  # tuần hoàn tất liền trước (W-2)
    delta: int = 0  # count_current − count_previous
    delta_pct: Optional[float] = None  # %; None khi count_previous == 0 (mẫu số 0)


class WowRow(BaseModel):
    group_key: Optional[int] = None  # major_id / officer_id; None cho bucket/tổng
    label: str
    code: Optional[str] = None  # major code (major grouping only)
    degree_level: Optional[str] = None  # major grouping only
    is_bucket: bool = False
    bucket_kind: Optional[BucketKind] = None
    submitted: WowMovement = Field(default_factory=WowMovement)
    admitted: WowMovement = Field(default_factory=WowMovement)
    enrolled: WowMovement = Field(default_factory=WowMovement)


class WowComparison(BaseModel):
    latest_complete_week: WeekMeta  # W-1
    previous_complete_week: WeekMeta  # W-2


class AdmissionWowResponse(ScopedReport):
    """Nhịp tuần: 2 tuần ISO ĐÃ HOÀN TẤT gần nhất (tuần đang chạy bị loại).

    ``insufficient_data=True`` khi năm chưa bắt đầu / không đủ 2 tuần hoàn tất →
    ``comparison=None``, ``rows=[]`` (KHÔNG bịa 2 tuần 0 giả). Attribution =
    recomputed-current: số của tuần đã qua có thể đổi khi hồ sơ được phân công lại.
    """

    group_by: GroupBy
    attribution: Literal["recomputed-current"] = "recomputed-current"
    insufficient_data: bool = False
    comparison: Optional[WowComparison] = None
    rows: list[WowRow] = Field(default_factory=list)
    totals: WowRow  # Σ across rows (label="TỔNG")
