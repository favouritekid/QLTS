# app/schemas/quota_matrix.py
"""Quota matrix overview schema (Phase 2 v8.2 PR-2D.1 v2 — Phase 3 view).

Aggregated read-model cho admin tổng quan rải chỉ tiêu theo (ngành × đợt).
Granularity: 1 row = 1 academic_info; 1 col = 1 round; cell = sum of
admit_quota across paths trong cùng (academic_info × round).

Constraint visible: ∑(row cells) ≤ academic_info.annual_admission_quota
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class QuotaMatrixRound(BaseModel):
    """1 đợt cho năm filter (column header)."""
    id: int
    round_code: str
    round_name: str
    is_active: bool


class QuotaMatrixCell(BaseModel):
    """Sum aggregated cho (academic_info × round) cell."""
    admission_round_id: int
    round_code: str
    total_admit_quota: int = Field(
        default=0,
        description="∑ admit_quota across paths trong cùng (academic_info × round). NULL paths counted as 0.",
    )
    total_round_quota: int = Field(
        default=0,
        description="∑ round_quota across paths.",
    )
    total_submission_count: int = Field(
        default=0,
        description="∑ submission_count actual filed.",
    )
    path_count: int = Field(
        default=0,
        description="Số paths trong cell (để admin biết granularity).",
    )


class QuotaMatrixRow(BaseModel):
    """1 ngành (academic_info) × N rounds → 1 row matrix."""
    academic_info_id: int
    academic_year: int
    program_name: str = Field(..., description="Tên ngành đào tạo")
    program_code: Optional[str] = None
    degree_level: Optional[str] = None
    annual_admission_quota: Optional[int] = Field(
        default=None,
        description="Tổng chỉ tiêu cho năm. NULL = không giới hạn (unbounded).",
    )
    cells_by_round_id: dict[int, QuotaMatrixCell] = Field(
        default_factory=dict,
        description="Map round_id → cell. Empty cell nếu chưa có path",
    )
    sum_admit_allocated: int = Field(
        default=0,
        description="∑ tất cả cell.total_admit_quota — đã rải",
    )
    sum_remaining: Optional[int] = Field(
        default=None,
        description="annual - sum_allocated. NULL nếu annual NULL. Negative = vượt cap (warning)",
    )


class QuotaMatrixResponse(BaseModel):
    """GET /api/v2/admin/years/{year}/quota-matrix response.

    Admin tổng quan ALL ngành × ALL rounds cho năm filter.
    """
    model_config = ConfigDict(from_attributes=True)
    academic_year: int
    rounds: List[QuotaMatrixRound]
    rows: List[QuotaMatrixRow]
    total_rows: int


# ============================================================
# Per-major view: paths × rounds (cells = exact path, NOT aggregate)
# ============================================================


class PathMatrixCell(BaseModel):
    """1 cell trong per-major matrix = 1 exact AdmissionPath identity.

    Vì filter theo (academic_info_id × method_id × round_id) = UNIQUE 3-col,
    cell exact 1 path (or empty nếu chưa có).
    """
    path_id: int
    admission_round_id: int
    admission_method_id: int
    round_quota: Optional[int]  # submit cap
    admit_quota: Optional[int]
    submission_count: int
    status: str  # active|draft|inactive|archived
    criteria_code: Optional[str] = None
    # Funnel counts (PR matrix-funnel) — actual progress per path. Đếm thực
    # nộp (multi-NV qua choice + legacy qua applied_rules), KHÔNG dùng
    # submission_count (counter Tier-2 single-path). Default 0 = ô trống.
    submitted_count: int = Field(
        default=0,
        description="Hồ sơ thực nộp (multi-NV distinct profile + legacy). status NOT IN draft/withdrawn.",
    )
    approved_count: int = Field(
        default=0,
        description="Trúng tuyển — QUOTA_OCCUPYING_STATUSES (choice.decision='admitted' + legacy).",
    )
    enrolled_count: int = Field(
        default=0,
        description="Nhập học — status='enrolled' GỒM cả is_dropped (seat đã tiêu thụ).",
    )
    dropped_count: int = Field(
        default=0,
        description="Trong số enrolled, bao nhiêu đã bỏ (is_dropped IS TRUE) — chú thích riêng.",
    )


class PathMatrixMethodRow(BaseModel):
    """1 row trong per-major matrix = 1 admission_method.

    Cells map: round_id → cell (None nếu chưa có path cho cell này).
    """
    admission_method_id: int
    method_code: str
    method_name: str
    cells_by_round_id: dict[int, Optional[PathMatrixCell]] = Field(
        default_factory=dict,
        description="Map round_id → cell (None = chưa tạo path cho cell này)",
    )
    sum_admit_quota: int = 0  # sum across rounds for this method


class PathMatrixResponse(BaseModel):
    """GET /api/v2/admin/academic-infos/{id}/path-matrix response.

    Per-major view: rows = methods, cols = rounds, cells = exact path.
    Admin chọn 1 ngành → render matrix method × đợt cho ngành đó.
    """
    model_config = ConfigDict(from_attributes=True)
    academic_info_id: int
    academic_year: int
    program_name: str
    program_code: Optional[str] = None
    degree_level: Optional[str] = None
    annual_admission_quota: Optional[int] = None
    sum_admit_allocated: int = 0
    sum_remaining: Optional[int] = None
    rounds: List[QuotaMatrixRound]
    methods: List[PathMatrixMethodRow]
