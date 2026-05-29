"""feat/document-group-audience-merge — ĐỢT A: add document_group.applicable_audience + GIN

Revision ID: docgrp_audience_20260529
Revises: kv_add_successor_20260526
Create Date: 2026-05-29

ĐỢT A (inert, zero-regression):
- Thêm cột ``document_group.applicable_audience`` ``admission_audience[]`` nullable.
  NULL = lớp NỀN tier shared (luôn merge cho mọi thí sinh). ``[..]`` = lớp theo
  đối tượng/trình độ, merge khi && audience_set của thí sinh.
- GIN index ``ix_document_group_applicable_audience`` cho && overlap.
  Query contract: ``WHERE applicable_audience IS NULL OR
  applicable_audience && ARRAY[:aud]::admission_audience[]`` (NEVER = ANY).

KHÔNG backfill ở đây (ĐỢT A inert): mọi row hiện hữu giữ applicable_audience=NULL
→ vẫn là NỀN → resolve không đổi (profile mới vẫn lấy đủ doc như trước). Backfill
split (§8.2) + lớp POST_THCS (§8.0) là migration RIÊNG ở ĐỢT B (owner-gated).

ENUM ``admission_audience`` đã được tạo ở phase1_03 → ``create_type=False``,
KHÔNG tạo lại.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "docgrp_audience_20260529"
down_revision = "kv_add_successor_20260526"
branch_labels = None
depends_on = None


ADMISSION_AUDIENCE_VALUES = (
    "POST_THCS",
    "POST_THPT",
    "LIEN_THONG_TC",
    "LIEN_THONG_CD",
    "VLVH",
)


def upgrade() -> None:
    # ENUM admission_audience đã tồn tại (phase1_03) → reference, KHÔNG tạo.
    audience_enum = postgresql.ENUM(
        *ADMISSION_AUDIENCE_VALUES,
        name="admission_audience",
        create_type=False,
    )

    # 1. Cột applicable_audience — NULL = lớp NỀN (mọi row hiện hữu = NỀN,
    #    inert: resolve giữ nguyên).
    op.add_column(
        "document_group",
        sa.Column(
            "applicable_audience",
            postgresql.ARRAY(audience_enum),
            nullable=True,
            comment=(
                "Audience layer filter ARRAY admission_audience. "
                "NULL = lớp NỀN (luôn merge). Chỉ dùng trong tier shared. "
                "Query MUST use && overlap (NEVER = ANY) để hit GIN."
            ),
        ),
    )

    # 2. GIN index cho && overlap audience.
    op.create_index(
        "ix_document_group_applicable_audience",
        "document_group",
        ["applicable_audience"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_group_applicable_audience",
        table_name="document_group",
    )
    op.drop_column("document_group", "applicable_audience")
    # KHÔNG drop enum admission_audience — admission_path.applicable_to vẫn dùng.
