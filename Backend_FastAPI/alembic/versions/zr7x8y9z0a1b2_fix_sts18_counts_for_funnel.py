"""fix: counts_for_funnel false -> true for sts13, sts17, sts18

Revision ID: zr7x8y9z0a1b2
Revises: zq6w7x8y9z0a1
Create Date: 2026-03-16

Three statuses at stg03/stg05 had counts_for_funnel=false, making leads
invisible to funnel/NCR queries in officer_repository.py:

sts13 (APPLICATION_FEE_PAID, stg03): Lead paid application fee — strong
  commitment signal. Between sts13→sts09 needs manual manager approval,
  lead can sit here for days invisible in stg03 funnel count.

sts17 (APPLICATION_REVISION, stg03): Lead supplementing documents — still
  active in pipeline. Can take weeks. Same stg03 as sts07 (counted) with
  no logical reason to exclude.

sts18 (TUITION_REFUNDED, stg05): is_final=true, outcome=negative — clear
  loss event. Was excluded from early_exit_count and total_lost entirely,
  causing NCR inflation. After fix: picked up by early_exit_count at stg05
  (non-final stage), feeds total_lost, NCR denominator corrected.

KPI enrollment count (count_enrollments_ytd) is NOT affected — its triple-
defense requires is_final_stage=true; stg03/stg05 have is_final_stage=false.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zr7x8y9z0a1b2"
down_revision: Union[str, None] = "zq6w7x8y9z0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        text(
            "UPDATE consultation_status "
            "SET counts_for_funnel = true "
            "WHERE id IN ('sts13', 'sts17', 'sts18') AND counts_for_funnel = false"
        )
    )
    print(f"  [fix] sts13/sts17/sts18 counts_for_funnel → true ({result.rowcount} row(s) updated)")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE consultation_status "
            "SET counts_for_funnel = false "
            "WHERE id IN ('sts13', 'sts17', 'sts18')"
        )
    )
