"""Add admission_profile read-model columns (perf/admissions-list).

Trang danh sách hồ sơ (`/admissions`) chậm vì "compute-at-read-time":
`/api/admissions/stats` tính `avg_completion` bằng fetch-all mọi hồ sơ + Python
loop (~2.1s), và list serialize `AdmissionProfileResponse` nặng cho mỗi dòng
(324KB/20 dòng). Ba cột read-model denormalized cho phép list + stats ĐỌC giá
trị đã tính sẵn thay vì tính lại mỗi request.

Cột (nullable — KHÔNG backfill trong migration):
* ``cached_completion SMALLINT`` — completion_percent (0-100).
* ``cached_readiness VARCHAR(20)`` — 'eligible'|'ineligible'.
* ``cached_derived_at TIMESTAMPTZ`` — lần cuối refresh.

⚠️ KHÔNG backfill ở đây: completion/readiness cần chạy validator Python
(`_compute_completion_percent`/`_compute_readiness_status`), không SQL-able —
đặc biệt multi-NV đọc live-config. Các cột khởi tạo NULL; **beat task
`refresh_admission_derived_task` TỰ backfill lazily** (mỗi chu kỳ 5' refresh tối
đa `_DERIVED_SWEEP_BATCH` hàng cũ nhất theo cached_derived_at NULLS FIRST — độ tươi
thực = ceil(N_non_frozen/batch)×5', KHÔNG phải "mọi hàng mỗi chu kỳ"). Stats
`AVG(cached_completion)` bỏ qua NULL (COALESCE ở service cho cửa sổ đầu).

Revision ID: admderivedcols20260721
Revises: distpanelcasbin20260719
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "admderivedcols20260721"
down_revision: Union[str, None] = "distpanelcasbin20260719"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "admission_profile"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "cached_completion",
            sa.SmallInteger(),
            nullable=True,
            comment="Read-model: completion_percent (0-100). Ghi bởi refresh_derived_fields; đọc bởi list + AVG stats. Eventual-consistent.",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "cached_readiness",
            sa.String(length=20),
            nullable=True,
            comment="Read-model: 'eligible'|'ineligible'. Ghi bởi refresh_derived_fields; đọc bởi list. Eventual-consistent.",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "cached_derived_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Lần cuối refresh_derived_fields ghi cached_completion/readiness (UTC).",
        ),
    )
    # Index phục vụ sweep `refresh_admission_derived_task`, khớp CHÍNH XÁC thứ tự
    # truy vấn: ORDER BY cached_derived_at ASC NULLS FIRST LIMIT N. NULLS FIRST
    # trong index cho phép index-scan phục vụ CẢ (a) quét hàng CHƯA tính (NULL ở
    # đầu = backfill lazy) LẪN (b) steady-state lấy N hàng cũ nhất — KHÔNG seq-scan
    # + sort toàn bảng mỗi chu kỳ (khác partial-index-chỉ-NULL sẽ rỗng sau backfill).
    op.create_index(
        "ix_admission_profile_cached_derived_at",
        TABLE,
        [sa.text("cached_derived_at ASC NULLS FIRST")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admission_profile_cached_derived_at", table_name=TABLE)
    op.drop_column(TABLE, "cached_derived_at")
    op.drop_column(TABLE, "cached_readiness")
    op.drop_column(TABLE, "cached_completion")
