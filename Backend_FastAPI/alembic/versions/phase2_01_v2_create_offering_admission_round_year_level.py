"""phase2_01_v2: create offering_admission_round table at academic_year level.

Revision ID: phase2_01_v2
Revises: phase1_15a
Create Date: 2026-05-09

#184 Phase 2 PR-2A v2 (Option A schema redesign per plan v8.2 chốt
2026-05-09). Round entity at academic_year level, NOT per-academic_info
(superseded v6 schema từ tag ``phase2-pr-2a-v6-archived``).

Plan
----
* Plan file ``C:\\Users\\Admin\\.claude\\plans\\noble-launching-cocoa.md``
  v8.2 (8 audit rounds: v1 → v2 → v3 → v4 → v5 → v6 → v8 → v8.1 → v8.2).
* Memory ``phase2-plan-locked`` v8.2.
* PLAN Phần 9 "Phase 2 — Schema design pivot Option A (2026-05-09)".

Schema delta vs v6 (PLAN §2.1 line 532-535)
-------------------------------------------
v6 (archived tag ``phase2-pr-2a-v6-archived``):
    OfferingAdmissionRound.academic_info_id FK → per-academic_info nest
    UNIQUE(academic_info_id, round_code)
    Quota fields ON THIS TABLE (round_quota, admit_quota, submission_count)

v8.2 Option A (this migration):
    OfferingAdmissionRound.academic_year INT → year-level globally
    UNIQUE(academic_year, round_code)
    Quota fields MOVED to admission_path (PR-2B v2 phase2_02_v2)

Rationale (PLAN Phần 9):
    Round metadata replication problem trong v6 (extend/archive/notify
    cost N atomic UPDATEs). Year-level: 1 đợt = 1 row, time-window edit
    = single UPDATE.

Decisions Q1-Q8 (LOCKED 2026-05-09)
-----------------------------------
* Q1: Schema = Option A (year-level)
* Q3: Round metadata = time-window only Phase 2 (notification template
  defer Phase 3)
* Q7: admission_path.admission_round_id ON DELETE RESTRICT (PR-2B v2)
* Q8: round_code = pure string + UI convention

Final migration constraint: NO DROP TABLE prod path (v6 schema chưa vào
prod, dev rollback only handled via separate downgrade).

Backfill DOT_1 per distinct academic_year
-----------------------------------------
Pre-flight Phase A audit 2026-05-08 verified dev/prod 1:1 match — only
distinct academic_year = 2026 → 1 DOT_1 row created globally cho cả
trường năm 2026.

Idempotent guards
-----------------
* ``CREATE TABLE`` raises ``DuplicateTable`` on re-run (alembic semantics)
* Backfill INSERT uses ``ON CONFLICT (academic_year, round_code) DO
  NOTHING`` — re-runnable safely.

Concern β v5 carry forward — archive_expired_rounds_task cron DEFER
Phase 3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase2_01_v2"
down_revision: Union[str, None] = "phase1_15a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "offering_admission_round"
UNIQUE_NAME = "uq_offering_admission_round_year_code"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "academic_year",
            sa.Integer,
            nullable=False,
            index=True,
            comment="Year-level grouping. UNIQUE per (academic_year, round_code).",
        ),
        sa.Column(
            "round_code",
            sa.String(20),
            nullable=False,
            comment="Round identifier: DOT_1 / DOT_2 / DOT_3 / BO_SUNG / DOT_1_VLVH (Q8 v8.2 — pure string)",
        ),
        sa.Column(
            "round_name",
            sa.String(100),
            nullable=False,
            comment='Localized display: "Đợt 1 - 2026"',
        ),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            comment="Toggle hide round khỏi storefront + path config dropdown",
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Soft-archive marker — set by admin DELETE endpoint. "
                "Phase 3 future: archive_expired_rounds_task cron will "
                "move profiles to existing _archived_admission_profile "
                "table (phase1_16) at end_date+6mo per PLAN §2.1.a Rule 3."
            ),
        ),
        # SPEC §2.1.a Rule 2 — admin extend audit fields
        sa.Column(
            "extended_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last admin end_date extension timestamp",
        ),
        sa.Column(
            "extended_by_user_id",
            sa.Integer,
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
            comment="Admin user who last extended end_date",
        ),
        sa.Column(
            "extension_reason",
            sa.Text,
            nullable=True,
            comment="Reason ≥10 chars mandatory for extend endpoint",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("academic_year", "round_code", name=UNIQUE_NAME),
    )

    # Backfill DOT_1 per distinct academic_year (Q1 v8.2 — year-level
    # globally, NOT per academic_info). Idempotent ON CONFLICT.
    # Pre-flight Phase A 2026-05-08: dev/prod has only academic_year=2026
    # active → 1 DOT_1 row created.
    op.execute(
        """
        INSERT INTO offering_admission_round
            (academic_year, round_code, round_name,
             start_date, end_date, is_active,
             archived_at, extended_at, extended_by_user_id, extension_reason,
             created_at, updated_at)
        SELECT DISTINCT
            oai.academic_year,
            'DOT_1',
            'Đợt 1 - ' || oai.academic_year::text,
            NULL::date,
            NULL::date,
            true,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::int,
            NULL::text,
            NOW(),
            NOW()
        FROM offering_academic_info oai
        WHERE oai.is_deleted = false
        ON CONFLICT (academic_year, round_code) DO NOTHING;
        """
    )


def downgrade() -> None:
    """Reversible — drop table cascades all backfilled rounds.

    Safe pre-Phase-2-prod-cutover. Post-cutover (PR-2C v2 ⚠ ONE-WAY ships
    NOT NULL admission_round_id on admission_path), this downgrade would
    break path FK invariants — handle via PR-2C downgrade playbook chain
    (Documents/PHASE2_ROLLBACK_PLAYBOOK_V8.md).
    """
    op.drop_table(TABLE)
