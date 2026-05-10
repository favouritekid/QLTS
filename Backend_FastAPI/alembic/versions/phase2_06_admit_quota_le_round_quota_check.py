"""Phase 2 hard-review pass 2 BM-2 — Tier 2 invariant CHECK constraint

Add DB-level CHECK constraint backing service-layer Tier 2 invariant:
``admit_quota <= round_quota`` khi cả 2 set. Service validator
(``admission_quota_service.validate_tier2_path_invariant``) đã enforce,
nhưng direct SQL bypass (admin migration / hand-edit script) có thể
violate. CHECK constraint = defense-in-depth backup.

Semantics:
* CHECK passes nếu ``admit_quota IS NULL`` HOẶC ``round_quota IS NULL``
  HOẶC ``admit_quota <= round_quota``
* NULL-safe — không reject path chưa cấu hình quota

Pre-flight check: audit existing rows, raise nếu vi phạm pre-deploy.

Revision ID: phase2_06
Revises: phase2_05
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "phase2_06"
down_revision: Union[str, None] = "phase2_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pre-flight audit: bất kỳ row nào violate sẽ block migration ngay
    # (better than silent CHECK failure trên next INSERT/UPDATE).
    conn = op.get_bind()
    violations = conn.execute(
        text(
            """
            SELECT COUNT(*) FROM admission_path
            WHERE admit_quota IS NOT NULL
              AND round_quota IS NOT NULL
              AND admit_quota > round_quota
            """
        )
    ).scalar()
    if violations and int(violations) > 0:
        raise RuntimeError(
            f"Cannot add Tier 2 CHECK: {violations} rows already violate "
            f"admit_quota <= round_quota. Fix data trước khi apply."
        )

    op.execute(
        """
        ALTER TABLE admission_path
        ADD CONSTRAINT ck_admit_quota_le_round_quota
        CHECK (
            admit_quota IS NULL
            OR round_quota IS NULL
            OR admit_quota <= round_quota
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE admission_path DROP CONSTRAINT IF EXISTS ck_admit_quota_le_round_quota"
    )
