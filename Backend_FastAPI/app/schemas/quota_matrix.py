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
