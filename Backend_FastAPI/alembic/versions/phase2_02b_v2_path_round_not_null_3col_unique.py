"""Phase 2 v8.2 PR-2C v2 ⚠ ONE-WAY: NOT NULL + 3-col UNIQUE swap (Option A)

⚠ ONE-WAY MIGRATION — KHÔNG có downgrade safe path. Trước merge PHẢI:
- Verify 0 NULL admission_round_id (qua pre-check raise)
- Backup prod database (mandatory thứ 2 sau pre-Phase-2 backup)
- Manual rollback playbook ``Documents/PHASE2_ROLLBACK_PLAYBOOK_V8.md``
  ready cho production rollback scenarios

Changes:
- ALTER ``admission_path.admission_round_id`` SET NOT NULL
- DROP UNIQUE ``uq_admission_path_offering_method``
  (academic_info_id, admission_method_id) — 2-col
- CREATE UNIQUE ``uq_admission_path_round_acad_method``
  (admission_round_id, academic_info_id, admission_method_id) — 3-col Q5 v8.2

Rationale (Q5 v8.2):
- Story 3 walk-through: 4 đợt × 30 majors × 3 methods = 360 paths năm 2026
- Path identity = round + major + method (NOT just major + method)
- 2-col UNIQUE blocks → only 90 paths total (1/4 capacity)

Archive table created cho safety net (manual rollback playbook):
- ``_archive_admission_path_dup`` — admin có thể manually move
  duplicates trước downgrade attempt

Revision ID: phase2_02b_v2
Revises: phase2_02_v2
Create Date: 2026-05-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "phase2_02b_v2"
down_revision: Union[str, None] = "phase2_02_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ============================================================
    # Pre-check: 0 NULL admission_round_id required
    # ============================================================
    # PR-2B v2 audit guard already enforced this; double-verify
    # before NOT NULL ALTER cho defense-in-depth.
    null_count = bind.execute(
        text(
            "SELECT COUNT(*) FROM admission_path "
            "WHERE admission_round_id IS NULL"
        )
    ).scalar()
    if null_count and null_count > 0:
        raise RuntimeError(
            f"PR-2C v2 abort: {null_count} admission_path rows have NULL "
            f"admission_round_id. PR-2B v2 backfill should have populated "
            f"all rows. Manual investigation required before re-running."
        )

    # ============================================================
    # Archive table cho manual rollback safety net
    # ============================================================
    # If admin needs to downgrade to 2-col UNIQUE, duplicates by
    # (academic_info_id, admission_method_id) phải được move sang
    # archive trước. CREATE IF NOT EXISTS — idempotent.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS _archive_admission_path_dup (
            LIKE admission_path INCLUDING DEFAULTS,
            archived_at TIMESTAMPTZ DEFAULT NOW(),
            archive_reason TEXT
        );
        """
    )

    # ============================================================
    # NOT NULL swap on admission_round_id
    # ============================================================
    op.alter_column(
        "admission_path",
        "admission_round_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # ============================================================
    # UNIQUE constraint swap: 2-col → 3-col (Q5 v8.2)
    # ============================================================
    # Drop OLD 2-col constraint
    op.drop_constraint(
        "uq_admission_path_offering_method",
        "admission_path",
        type_="unique",
    )
    # Create NEW 3-col constraint
    op.create_unique_constraint(
        "uq_admission_path_round_acad_method",
        "admission_path",
        ["admission_round_id", "academic_info_id", "admission_method_id"],
    )


def downgrade() -> None:
    """⚠ DESTRUCTIVE — manual rollback playbook required.

    KHÔNG safe automated downgrade vì:
    - 3-col UNIQUE relaxation → 2-col UNIQUE swap có thể tạo duplicate
      conflict (multiple rounds chia sẻ cùng (academic_info, method))
    - Admin phải manually move duplicates sang ``_archive_admission_path_dup``
      trước khi alembic downgrade này chạy

    Reference: ``Documents/PHASE2_ROLLBACK_PLAYBOOK_V8.md``
    """
    bind = op.get_bind()

    # Sanity check: 0 duplicates by (academic_info_id, admission_method_id)
    dup_count = bind.execute(
        text(
            "SELECT COUNT(*) FROM ("
            "  SELECT academic_info_id, admission_method_id "
            "  FROM admission_path "
            "  GROUP BY academic_info_id, admission_method_id "
            "  HAVING COUNT(*) > 1"
            ") dups"
        )
    ).scalar()
    if dup_count and dup_count > 0:
        raise RuntimeError(
            f"PR-2C v2 downgrade abort: {dup_count} duplicate "
            f"(academic_info_id, admission_method_id) groups exist. "
            f"Use manual rollback playbook (Documents/"
            f"PHASE2_ROLLBACK_PLAYBOOK_V8.md) to archive duplicates "
            f"before retrying downgrade."
        )

    op.drop_constraint(
        "uq_admission_path_round_acad_method",
        "admission_path",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_admission_path_offering_method",
        "admission_path",
        ["academic_info_id", "admission_method_id"],
    )
    op.alter_column(
        "admission_path",
        "admission_round_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
