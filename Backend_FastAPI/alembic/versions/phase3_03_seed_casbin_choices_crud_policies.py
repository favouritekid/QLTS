"""Phase 3 PR-3D fixup — seed missing Casbin /choices CRUD policies

Wave 3 Fix Bundle E2E (2026-05-16):

PROBLEM — F2 from QA_E2E_FINDINGS_2026-05-15.md
    `policy_templates.py` declares choice CRUD policies for OFFICER
    (lines 182, 191-194) + DENY for ACCOUNTANT (lines 354-357), but
    these were NEVER seeded into prod casbin_rule table — sync script
    (`scripts/sync_casbin_templates.py`) historically only ran for
    officer role + skipped re-sync after template additions.

    Symptom: officer (chính chủ profile) POST
    /api/v2/admissions/{id}/choices → 403 PERMISSION_DENIED. Only
    admin pass via wildcard `/*`. Multi-NV CREATE flow blocked
    end-to-end despite FE wire complete.

FIX — seed 9 policy rows idempotently:
    - role:officer ALLOW (5 endpoints)
        GET    /api/v2/admissions/*/choices
        POST   /api/v2/admissions/*/choices
        DELETE /api/v2/admissions/*/choices/*
        PATCH  /api/v2/admissions/*/choices/*
        PATCH  /api/v2/admissions/*/choices/*/scores

    - role:accountant DENY (4 endpoints — separation-of-duties guard)
        POST   /api/v2/admissions/*/choices
        DELETE /api/v2/admissions/*/choices/*
        PATCH  /api/v2/admissions/*/choices/*
        PATCH  /api/v2/admissions/*/choices/*/scores

    Manager + admin inherit officer ALLOW via `g` edges (no direct
    policy needed). Admin retains wildcard `/*` ALLOW.

IDEMPOTENCY:
    Upgrade uses INSERT ... WHERE NOT EXISTS so re-run is safe.
    Downgrade DELETEs only the rows this migration added (matching
    composite key of v0+v1+v2+v3).

VERIFICATION (post-deploy):
    SELECT COUNT(*) FROM casbin_rule
    WHERE ptype='p' AND v1 LIKE '%/v2/admissions/%/choices%';
    -- Expected: 9 (5 officer ALLOW + 4 accountant DENY)

    SELECT v0, v2, v3 FROM casbin_rule
    WHERE ptype='p' AND v1 LIKE '%/v2/admissions/%/choices%'
    ORDER BY v0, v2;
    -- Expected: officer 5 ALLOW + accountant 4 DENY

Revision ID: phase3_03
Revises: phase3_02
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_03"
down_revision: Union[str, None] = "phase3_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (subject, object, action, eft) tuples — must match policy_templates.py
# OFFICER_TEMPLATE + ACCOUNTANT_TEMPLATE exactly for prod parity.
_OFFICER_ALLOW = [
    ("role:officer", "/api/v2/admissions/*/choices", "GET", "allow"),
    ("role:officer", "/api/v2/admissions/*/choices", "POST", "allow"),
    ("role:officer", "/api/v2/admissions/*/choices/*", "DELETE", "allow"),
    ("role:officer", "/api/v2/admissions/*/choices/*", "PATCH", "allow"),
    ("role:officer", "/api/v2/admissions/*/choices/*/scores", "PATCH", "allow"),
]

_ACCOUNTANT_DENY = [
    ("role:accountant", "/api/v2/admissions/*/choices", "POST", "deny"),
    ("role:accountant", "/api/v2/admissions/*/choices/*", "DELETE", "deny"),
    ("role:accountant", "/api/v2/admissions/*/choices/*", "PATCH", "deny"),
    ("role:accountant", "/api/v2/admissions/*/choices/*/scores", "PATCH", "deny"),
]

_ALL_POLICIES = _OFFICER_ALLOW + _ACCOUNTANT_DENY


def upgrade() -> None:
    """Seed 9 /choices policy rows idempotently."""
    conn = op.get_bind()

    # Pre-flight count for sanity log
    pre_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM casbin_rule
            WHERE ptype='p' AND v1 LIKE '%/v2/admissions/%/choices%'
            """
        )
    ).scalar()
    print(f"[phase3_03] Pre-flight: existing /choices policy rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _ALL_POLICIES:
        # Explicit CAST avoids asyncpg `AmbiguousParameterError` when same
        # placeholder appears in both INSERT VALUES (text) and WHERE clause
        # (varchar column comparison).
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_phase3_03_choices_crud',
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

    print(f"[phase3_03] Seeded {inserted} new policy row(s) (skipped duplicates).")


def downgrade() -> None:
    """Remove only the rows this migration added (matched by composite key)."""
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _ALL_POLICIES:
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

    print(f"[phase3_03] Removed {deleted} policy row(s).")
