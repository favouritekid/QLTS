"""Phase 3 PR-3D fixup — drop Casbin admin→accountant diamond + dead waitlist-reject DENY

Wave 1 Fix Bundle E2E (2026-05-15):

PROBLEM 1 — Diamond inheritance leaks accountant DENYs to admin
    Casbin has edge `g, role:admin, role:accountant`. Accountant has 6
    explicit DENY entries (claim, request-revision, publish-result,
    waitlist-promote, admin-rollback, plus 4 choice CRUD denies).
    Per Casbin deny-first effect with role inheritance, admin inherits
    these DENYs and gets 403 on the listed endpoints despite having a
    wildcard ALLOW (`/*.*`).
    PR #294 hotfix only removed accountant's publish-result DENY row.
    This migration removes the root cause: the diamond edge itself.

PROBLEM 2 — Dead Casbin policy for non-existent /waitlist-reject endpoint
    Policy `role:accountant DENY /api/v2/admissions/*/waitlist-reject`
    exists in DB (seeded by phase1_19b), but no router handler exists
    for waitlist-reject. The endpoint was planned (T11) but never
    implemented. Dead policy = noise. Drop it.

FIX (per plan indexed-skipping-duckling.md Wave 1):
    1. DELETE FROM casbin_rule WHERE ptype='g' AND v0='role:admin'
       AND v1='role:accountant'
    2. DELETE FROM casbin_rule WHERE ptype='p' AND v0='role:accountant'
       AND v1='/api/v2/admissions/*/waitlist-reject' AND v2='POST'
       AND v3='deny'

Tree shape post-fix (admin inherits from manager only):
    admin → manager → officer → user
                  ↘ accountant → officer → user

Admin retains full access via wildcard ALLOW `/*.*` (not inheritance).
Separation-of-duties preserved (admin ≠ accountant in audit trail).
Zero regression risk for officer/manager/accountant.

IDEMPOTENCY:
- Upgrade uses DELETE which is idempotent if rows already missing.
- Downgrade uses INSERT WHERE NOT EXISTS to handle partial restore.

VERIFICATION (post-deploy):
    SELECT COUNT(*) FROM casbin_rule
    WHERE ptype='g' AND v0='role:admin' AND v1='role:accountant';
    -- Expected: 0

    SELECT COUNT(*) FROM casbin_rule
    WHERE ptype='p' AND v0='role:accountant'
      AND v1='/api/v2/admissions/*/waitlist-reject';
    -- Expected: 0

Revision ID: phase3_02
Revises: phase3_01
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_02"
down_revision: Union[str, None] = "phase3_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop diamond edge + dead waitlist-reject DENY.

    Both DELETEs are idempotent. Safe to re-run.
    """
    conn = op.get_bind()

    # ============================================================
    # PRE-FLIGHT AUDIT — count rows before delete for sanity check
    # ============================================================
    g_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='g' AND v0='role:admin' AND v1='role:accountant'
            """
        )
    ).scalar() or 0

    waitlist_reject_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='p'
              AND v0='role:accountant'
              AND v1='/api/v2/admissions/*/waitlist-reject'
              AND v2='POST'
              AND v3='deny'
            """
        )
    ).scalar() or 0

    print(
        f"[phase3_02] Pre-flight: g_diamond_rows={g_count}, "
        f"dead_waitlist_reject_rows={waitlist_reject_count}"
    )

    # ============================================================
    # 1. Drop diamond inheritance edge
    # ============================================================
    op.execute(
        sa.text(
            """
            DELETE FROM casbin_rule
            WHERE ptype = 'g'
              AND v0 = 'role:admin'
              AND v1 = 'role:accountant'
            """
        )
    )

    # ============================================================
    # 2. Drop dead waitlist-reject DENY (endpoint không tồn tại)
    # ============================================================
    op.execute(
        sa.text(
            """
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:accountant'
              AND v1 = '/api/v2/admissions/*/waitlist-reject'
              AND v2 = 'POST'
              AND v3 = 'deny'
            """
        )
    )

    # ============================================================
    # POST-FLIGHT AUDIT — verify cleanup
    # ============================================================
    post_g = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='g' AND v0='role:admin' AND v1='role:accountant'
            """
        )
    ).scalar() or 0

    post_wr = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='p'
              AND v0='role:accountant'
              AND v1='/api/v2/admissions/*/waitlist-reject'
            """
        )
    ).scalar() or 0

    if post_g != 0 or post_wr != 0:
        raise RuntimeError(
            f"[phase3_02] Post-flight FAIL: g_diamond={post_g} (expect 0), "
            f"dead_waitlist_reject={post_wr} (expect 0)"
        )

    print(
        f"[phase3_02] Cleanup complete. Removed {g_count} diamond row(s) + "
        f"{waitlist_reject_count} dead-waitlist-reject row(s)."
    )


def downgrade() -> None:
    """Restore diamond edge + dead waitlist-reject DENY (idempotent INSERT)."""
    # Restore diamond inheritance edge (only if missing)
    op.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1)
            SELECT 'g', 'role:admin', 'role:accountant'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='g' AND v0='role:admin' AND v1='role:accountant'
            )
            """
        )
    )

    # Restore dead waitlist-reject DENY (only if missing)
    op.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
            SELECT 'p', 'role:accountant',
                   '/api/v2/admissions/*/waitlist-reject', 'POST', 'deny'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='p'
                  AND v0='role:accountant'
                  AND v1='/api/v2/admissions/*/waitlist-reject'
                  AND v2='POST'
                  AND v3='deny'
            )
            """
        )
    )
