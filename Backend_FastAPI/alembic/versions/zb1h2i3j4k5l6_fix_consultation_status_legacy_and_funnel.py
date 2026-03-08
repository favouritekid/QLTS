"""Fix consultation_status legacy_status mappings and counts_for_funnel flags

Revision ID: zb1h2i3j4k5l6
Revises: za0g1h2i3j4k5
Create Date: 2026-03-07

Part A - Fix consultation_status table:
- sts14 (TUITION_PENDING): legacy_status 'unqualified' -> 'qualified'
  Lead already approved, waiting for tuition != "unqualified".
  Consistent with sts10 (TUITION_PAID) at same stg05.
- sts17 (APPLICATION_REVISION): legacy_status 'unqualified' -> 'qualified'
  Request for document supplement != "unqualified".
  Consistent with sts07 (APPLICATION_RECEIVED) at same stg03.
- sts02 (CONTACTED): legacy_status 'new' -> 'contacted'
  Lead already contacted should not remain "new".
- sts12 (DROPPED_OUT): counts_for_funnel true -> false
  Dropped students should NOT count toward enrollment KPI funnel.
- sts19 (CANCELLED): counts_for_funnel true -> false
  Cancelled appointments (universal/activity) should not count in funnel.

Part B - Fix existing leads with wrong lead.status:
- 27 leads at sts14 with status='unqualified' -> 'qualified'
  (Created after 2026-02-14 via StatusHelper direct legacy assignment)
- 99 leads at sts02 with status='new' -> 'contacted'
- sts17: 0 leads need fix (all 143 already 'qualified')
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'zb1h2i3j4k5l6'
down_revision: Union[str, None] = 'za0g1h2i3j4k5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    # =========================================================================
    # Part A: Fix consultation_status table
    # =========================================================================

    # sts14 (TUITION_PENDING): 'unqualified' -> 'qualified'
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'qualified' WHERE id = 'sts14'")
    )

    # sts17 (APPLICATION_REVISION): 'unqualified' -> 'qualified'
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'qualified' WHERE id = 'sts17'")
    )

    # sts02 (CONTACTED): 'new' -> 'contacted'
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'contacted' WHERE id = 'sts02'")
    )

    # sts12 (DROPPED_OUT): counts_for_funnel true -> false
    connection.execute(
        sa.text("UPDATE consultation_status SET counts_for_funnel = false WHERE id = 'sts12'")
    )

    # sts19 (CANCELLED): counts_for_funnel true -> false
    connection.execute(
        sa.text("UPDATE consultation_status SET counts_for_funnel = false WHERE id = 'sts19'")
    )

    # =========================================================================
    # Part B: Fix existing leads with wrong lead.status
    # =========================================================================

    # 27 leads at sts14 with status='unqualified' -> 'qualified'
    result_sts14 = connection.execute(
        sa.text(
            "UPDATE lead SET status = 'qualified' "
            "WHERE consultation_status_id = 'sts14' AND status = 'unqualified' AND deleted_at IS NULL"
        )
    )

    # 99 leads at sts02 with status='new' -> 'contacted'
    result_sts02 = connection.execute(
        sa.text(
            "UPDATE lead SET status = 'contacted' "
            "WHERE consultation_status_id = 'sts02' AND status = 'new' AND deleted_at IS NULL"
        )
    )

    print(
        f"Fixed consultation_status: sts14/sts17 legacy='qualified', "
        f"sts02 legacy='contacted', sts12/sts19 funnel=false. "
        f"Fixed leads: {result_sts14.rowcount} sts14 + {result_sts02.rowcount} sts02"
    )


def downgrade() -> None:
    connection = op.get_bind()

    # Revert Part B (before Part A to maintain consistency)
    # Note: sts14 revert affects all 184 leads (not just 27) because we cannot
    # distinguish migration-fixed leads from already-correct leads. This is an
    # accepted trade-off for downgrade — re-upgrading will fix them again.
    result_sts14 = connection.execute(
        sa.text(
            "UPDATE lead SET status = 'unqualified' "
            "WHERE consultation_status_id = 'sts14' AND status = 'qualified' AND deleted_at IS NULL"
        )
    )

    result_sts02 = connection.execute(
        sa.text(
            "UPDATE lead SET status = 'new' "
            "WHERE consultation_status_id = 'sts02' AND status = 'contacted' AND deleted_at IS NULL"
        )
    )

    # Revert Part A
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'unqualified' WHERE id = 'sts14'")
    )
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'unqualified' WHERE id = 'sts17'")
    )
    connection.execute(
        sa.text("UPDATE consultation_status SET legacy_status = 'new' WHERE id = 'sts02'")
    )
    connection.execute(
        sa.text("UPDATE consultation_status SET counts_for_funnel = true WHERE id = 'sts12'")
    )
    connection.execute(
        sa.text("UPDATE consultation_status SET counts_for_funnel = true WHERE id = 'sts19'")
    )

    print(
        f"Reverted consultation_status fixes. "
        f"Reverted leads: {result_sts14.rowcount} sts14 + {result_sts02.rowcount} sts02"
    )
