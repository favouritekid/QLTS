"""rename: stg04 'Chờ nhập học' → 'Kết quả hồ sơ', stg05 'Đã nộp học phí' → 'Xử lý học phí'

Revision ID: zt9z0a1b2c3d4
Revises: zs8y9z0a1b2c3
Create Date: 2026-03-17

Metadata-only rename. No logic changes.

stg04 contains both sts09 (positive: eligible) and sts16 (negative: rejected).
Old name "Chờ nhập học" implied only positive outcome → misleading for officers.

stg05 contains sts14 (pending), sts10 (paid), sts18 (refunded).
Old name "Đã nộp học phí" only described the paid state → misleading.

NOTE: sts08 (APPLICATION_WITHDRAWN) remains phase=admission, stage_id=stg07.
This is an intentional design exception: admission outcome routed to terminal
stage stg07 for funnel dropout tracking.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zt9z0a1b2c3d4"
down_revision: Union[str, None] = "zs8y9z0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE pipeline_stage SET name = 'Kết quả hồ sơ' WHERE id = 'stg04'"
    ))
    conn.execute(text(
        "UPDATE pipeline_stage SET name = 'Xử lý học phí' WHERE id = 'stg05'"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE pipeline_stage SET name = 'Chờ nhập học' WHERE id = 'stg04'"
    ))
    conn.execute(text(
        "UPDATE pipeline_stage SET name = 'Đã nộp học phí' WHERE id = 'stg05'"
    ))
