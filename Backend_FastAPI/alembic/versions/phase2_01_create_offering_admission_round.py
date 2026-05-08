"""phase2_01: create offering_admission_round table.

Revision ID: phase2_01
Revises: phase1_15a
Create Date: 2026-05-09

#184 Phase 2 PR-2A — Foundation table cho multi-round capability per
academic_info. Backfill 1 DOT_1 round per active OfferingAcademicInfo
với round_quota = academic_info.annual_admission_quota (full annual
ban đầu) + dates NULL (admin edit qua UI sau).

Plan
----
* Plan file ``C:\\Users\\Admin\\.claude\\plans\\noble-launching-cocoa.md``
  v6 (5 audit rounds) chốt 2026-05-08.
* Memory ``phase2-plan-locked`` (v6).

Spec refs (Documents/ADMISSION_REFACTOR_PLAN.md)
------------------------------------------------
* §2.1 line 530-560 — round table schema (round_code/round_name/
  round_quota/admit_quota/submission_count/extension audit fields).
* §2.1.a line 562-611 — round lifecycle (cutoff submit + admin extend
  + 6mo archive + engine scope 30-day retroactive).
* §4 line 3577-3580 — phase2_01 migration body + DOT_1 backfill spec.
* §4.1 line 4100-4127 — atomic submission_count increment pattern.
* §4 line 3622 — score precision deferred to phase2_04 (PR-2E).
* Phần 9 Phase 2 deviation log (2026-05-08) — Q3 dates NULL deviation
  (oai.start_date/end_date column not exist verified via model).

Phase A pre-flight audit (verified 2026-05-08)
----------------------------------------------
* Dev qlts_dev: alembic phase1_15a, 20 active offering_academic_info,
  9 admission_profile (0 has admission_round_id — greenfield).
* Prod qlts_production 1:1 dev — same counts. Backfill expects 20
  DOT_1 rounds (1 per active academic_info).

Idempotent guards
-----------------
* ``CREATE TABLE IF NOT EXISTS`` skipped because alembic semantics
  expect ``op.create_table`` raises on duplicate. Half-applied state
  surfaces clean ``DuplicateTable`` error.
* Backfill INSERT uses ``ON CONFLICT (academic_info_id, round_code)
  DO NOTHING`` — re-runnable safely.

Concern β v5 — archive_expired_rounds_task cron DEFER Phase 3
-------------------------------------------------------------
``archived_at`` column added Phase 2 cho admin manual soft-archive
(DELETE endpoint sets it). Cron task `archive_expired_rounds_task`
moves profiles to existing ``_archived_admission_profile`` table
(phase1_16 migration) at end_date+6mo — DEFER Phase 3 per memory
``outstanding-debt`` P3-C archive task dormant pattern + first
DOT_1 created 2026-05-09 doesn't expire until ~Q4 2026 anyway.

Concern A v4 — extension audit fields per SPEC line 552-557
-----------------------------------------------------------
``extended_at``, ``extended_by_user_id``, ``extension_reason`` track
admin endpoint ``POST /api/v2/admin/rounds/{id}/extend`` (per SPEC
2.1.a Rule 2). Reason ≥10 chars enforced at service layer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase2_01"
down_revision: Union[str, None] = "phase1_15a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "offering_admission_round"
UNIQUE_NAME = "uq_offering_admission_round_code"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "academic_info_id",
            sa.Integer,
            sa.ForeignKey("offering_academic_info.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "round_code",
            sa.String(20),
            nullable=False,
            comment="UNIQUE per academic_info: DOT_1 / DOT_2 / BO_SUNG (PLAN line 535)",
        ),
        sa.Column(
            "round_name",
            sa.String(100),
            nullable=False,
            comment='Localized display: "Đợt 1 - 2026" (PLAN line 536)',
        ),
        sa.Column(
            "start_date",
            sa.Date,
            nullable=True,
            comment="Round start date — NULL initially, admin edit via UI",
        ),
        sa.Column(
            "end_date",
            sa.Date,
            nullable=True,
            comment="Round end date — NULL initially; engine scope check + cutoff submit per SPEC 2.1.a Rule 1/4",
        ),
        sa.Column(
            "round_quota",
            sa.Integer,
            nullable=True,
            comment=(
                "Submission slot cap. Sum ≤ academic_info.annual_admission_quota "
                "enforced at service layer (PLAN §5 tier 1). NULL = no cap."
            ),
        ),
        sa.Column(
            "admit_quota",
            sa.Integer,
            nullable=True,
            comment=(
                "Admit slot cap. NULL = inherit round_quota. Engine T7 guard "
                "count(admitted) < admit_quota (PLAN line 540-547)."
            ),
        ),
        sa.Column(
            "submission_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment=(
                "Atomic high-watermark counter — increment on submit per "
                "PLAN line 4100-4107. KHÔNG decrement on withdraw/reject "
                "(historical count semantic)."
            ),
        ),
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
        sa.Column(
            "extended_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last admin end_date extension timestamp (PLAN §2.1.a Rule 2)",
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
            comment="Reason ≥10 chars mandatory for extend endpoint (PLAN §2.1.a)",
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
        sa.UniqueConstraint("academic_info_id", "round_code", name=UNIQUE_NAME),
    )

    # Backfill DOT_1 per active OfferingAcademicInfo. Idempotent ON
    # CONFLICT — re-runnable. Dates set NULL (oai.start_date/end_date
    # don't exist on model — verified phần 9 Phase 2 deviation log).
    # round_quota = oai.annual_admission_quota (full annual ban đầu);
    # admit_quota NULL = inherit round_quota.
    op.execute(
        """
        INSERT INTO offering_admission_round
            (academic_info_id, round_code, round_name,
             start_date, end_date,
             round_quota, admit_quota, submission_count, is_active,
             archived_at, extended_at, extended_by_user_id, extension_reason,
             created_at, updated_at)
        SELECT
            oai.id,
            'DOT_1',
            'Đợt 1 - ' || oai.academic_year::text,
            NULL::date,
            NULL::date,
            oai.annual_admission_quota,
            NULL,
            0,
            true,
            NULL,
            NULL,
            NULL,
            NULL,
            NOW(),
            NOW()
        FROM offering_academic_info oai
        WHERE oai.is_deleted = false
        ON CONFLICT (academic_info_id, round_code) DO NOTHING;
        """
    )


def downgrade() -> None:
    """Reversible — drop table cascades all backfilled rounds.

    Safe pre-Phase-2-prod-cutover. Post-cutover (PR-2C ⚠ ONE-WAY ships
    NOT NULL admission_round_id on admission_path), this downgrade
    would break path FK invariants — handle via PR-2C downgrade
    playbook chain (Documents/PHASE2_ROLLBACK_PLAYBOOK.md).
    """
    op.drop_table(TABLE)
