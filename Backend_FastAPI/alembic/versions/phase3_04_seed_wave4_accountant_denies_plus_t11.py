"""Phase 3 Wave 4+5 — seed accountant DENY rules: 23 admissions/leads + 1 waitlist-reject

2026-05-16 ship bundle:

PROBLEM 1 — Wave 4 accountant DENY rules synced dev (sync_casbin_templates.py)
    nhưng prod DB chưa có. Accountant inherit officer ALLOW via g-edge →
    accountant GET /api/admissions returns 200 (defensive code "Unexpected
    role" leak) + GET /api/leads returns 200 với 391 leads PII.

    Fix: seed 23 deny rules trên prod casbin_rule, mirror
    `policy_templates.py` ACCOUNTANT_TEMPLATE B1 deny block (Wave 4 commit
    `69661b20`).

PROBLEM 2 — Wave 5 ship T11 waitlist-reject endpoint (commit này).
    Phase 3 PR-3D backlog declared template entry deny for accountant +
    allow for manager/officer/admin. phase3_02 dropped accountant DENY
    because endpoint was dead. Now endpoint exists — re-add deny for
    separation-of-duties (waitlist-reject là admission decision, NOT
    finance op).

FIX (24 deny rows total):
    - 23 admissions+leads deny cho accountant (Wave 4 — F8 + F9)
    - 1 waitlist-reject deny cho accountant (Wave 5 — T11 endpoint live)

Idempotent INSERT WHERE NOT EXISTS — safe re-run + handles partial
prior sync (e.g. dev DB đã sync trước qua script).

VERIFICATION (post-deploy):
    SELECT COUNT(*) FROM casbin_rule
    WHERE ptype='p' AND v0='role:accountant' AND v3='deny';
    -- Pre-fix prod: 6 (4 from phase3_03 + 2 pre-existing)
    -- Post-fix:   30 (6 + 24 from this migration)

Revision ID: phase3_04
Revises: phase3_03
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_04"
down_revision: Union[str, None] = "phase3_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 23 Wave 4 accountant DENY rules — mirror policy_templates.py
# ACCOUNTANT_TEMPLATE B1 deny block (lines added by Wave 4 commit
# `69661b20`). Match exactly — sync drift detection relies on parity.
_WAVE4_ACCOUNTANT_DENIES = [
    # 12 admissions DENY
    ("/api/admissions", "GET"),
    ("/api/admissions/{id}", "GET"),
    ("/api/admissions/{id}", "PUT"),
    ("/api/admissions", "POST"),
    ("/api/admissions/{id}/submit", "POST"),
    ("/api/admissions/{id}/resubmit", "POST"),
    ("/api/admissions/{id}/withdraw", "POST"),
    ("/api/admissions/{id}/minor-correction", "POST"),
    ("/api/admissions/{id}/send-confirmation", "POST"),
    ("/api/admissions/stats", "GET"),
    ("/api/admissions/status-counts", "GET"),
    ("/api/admissions/academic-years", "GET"),
    # 11 leads DENY
    ("/api/leads", "GET"),
    ("/api/leads", "POST"),
    ("/api/leads/{id}", "GET"),
    ("/api/leads/{id}", "PUT"),
    ("/api/leads/{id}/timeline", "GET"),
    ("/api/leads/{id}/insights", "GET"),
    ("/api/leads/{id}/audit-logs", "GET"),
    ("/api/leads/{id}/consultations", "GET"),
    ("/api/leads/check-duplicate", "GET"),
    ("/api/leads/import", "POST"),
    ("/api/leads/import/template", "GET"),
]

# Wave 5 — T11 waitlist-reject accountant DENY (endpoint shipped this wave).
# phase3_02 dropped this row vì endpoint was dead; now endpoint exists +
# template re-declares deny → re-add cho separation-of-duties.
_WAVE5_WAITLIST_REJECT_DENY = [
    ("/api/v2/admissions/*/waitlist-reject", "POST"),
]

_ALL_DENIES = [
    ("role:accountant", obj, act, "deny")
    for obj, act in (_WAVE4_ACCOUNTANT_DENIES + _WAVE5_WAITLIST_REJECT_DENY)
]


def upgrade() -> None:
    """Seed 24 accountant DENY rows idempotently."""
    conn = op.get_bind()

    pre_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='p' AND v0='role:accountant' AND v3='deny'
            """
        )
    ).scalar()
    print(f"[phase3_04] Pre-flight: existing accountant deny rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _ALL_DENIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_phase3_04_wave4_5_accountant_denies',
                       NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype='p'
                      AND v0=CAST(:v0 AS VARCHAR)
                      AND v1=CAST(:v1 AS VARCHAR)
                      AND v2=CAST(:v2 AS VARCHAR)
                      AND v3=CAST(:v3 AS VARCHAR)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        inserted += result.rowcount

    print(f"[phase3_04] Seeded {inserted} new deny row(s) (skipped duplicates).")


def downgrade() -> None:
    """Remove only the rows this migration added (matched by composite key)."""
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _ALL_DENIES:
        result = conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        deleted += result.rowcount

    print(f"[phase3_04] Removed {deleted} deny row(s).")
