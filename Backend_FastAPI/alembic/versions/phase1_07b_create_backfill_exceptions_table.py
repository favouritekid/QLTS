"""phase1_07b: create _admission_backfill_exceptions audit table

Revision ID: phase1_07b
Revises: phase1_06
Create Date: 2026-05-04

#184 Wave 1 PR-1D — seventh migration in Phase 1 Schema chain
(PLAN §4 line 2689-2693). Pure DDL — creates the audit sink that
later migrations + scripts (M-1-12 selected_subject_group backfill,
M-3-01 profile choice migrate) write into when a per-row backfill
predicate cannot resolve cleanly.

Schema
------

* ``_admission_backfill_exceptions`` (note: leading underscore to
  signal "internal / not a domain table"):
  - ``id`` SERIAL PK
  - ``profile_id`` integer FK → ``admission_profile(id)`` ON DELETE
    CASCADE (orphan exception rows when profile is hard-deleted —
    auditing should NOT keep references to deleted PII).
  - ``exception_type`` varchar(64) — caller-defined tag (e.g.
    ``selected_subject_group_ambiguous`` / ``gpa_out_of_range`` /
    ``grad_year_unparseable``). One value per backfill task.
  - ``details`` JSONB — caller-defined payload (input snapshot,
    rule that triggered, suggested resolution).
  - ``created_at`` timestamptz NOT NULL DEFAULT now() — when the
    backfill task surfaced the exception.
  - ``resolved_at`` timestamptz nullable — when admin / ops closed
    the exception (NULL = unresolved).
  - ``resolved_by_user_id`` integer FK → ``user(id)`` ON DELETE SET
    NULL — who resolved.
  - ``resolution_notes`` text nullable — free text from admin.

* UNIQUE ``(profile_id, exception_type)`` — chặn cùng một caller
  từ insert duplicate rows cho cùng profile across re-runs.
  Re-runs with ON CONFLICT DO UPDATE để cập nhật ``details`` thay
  vì duplicate.

* INDEX ``(exception_type)`` — admin filter "show me all
  ``selected_subject_group_ambiguous`` exceptions".

* INDEX ``(resolved_at)`` partial WHERE NULL — open-exception
  filter (admin queue UI sẽ chỉ load chưa resolved).

Down-revision chain: ``phase1_06 → phase1_07b``. Note that
phase1_07 (demographics) is DEFERRED Q1/2027 per Q9 chốt
2026-05-01; phase1_07b ships now because it's required by M-1-12
backfill which runs trong Wave 2.

Idempotency
-----------
Pure CREATE TABLE — no backfill, no seed. ``checkfirst`` on
``op.create_table`` not directly available, but the alembic
revision pointer guards against re-running.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "phase1_07b"
down_revision: Union[str, None] = "phase1_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Audit sink — leading underscore signals "internal table,
    # not a domain entity". Admin queue UI reads this directly;
    # there is no service abstraction (caller migrations + backfill
    # scripts INSERT directly using sa.text with explicit columns).
    op.create_table(
        "_admission_backfill_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("admission_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exception_type",
            sa.String(64),
            nullable=False,
            comment=(
                "Caller-defined tag (e.g. selected_subject_group_ambiguous, "
                "gpa_out_of_range, grad_year_unparseable)."
            ),
        ),
        sa.Column(
            "details",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Caller-defined payload (input snapshot, rule, suggested resolution)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "profile_id", "exception_type",
            name="uq_admission_backfill_exceptions_profile_type",
        ),
    )

    # Admin queue filter — most common index hit.
    op.create_index(
        "ix_admission_backfill_exceptions_type",
        "_admission_backfill_exceptions",
        ["exception_type"],
    )

    # Open-exception partial index — admin queue typically filters
    # ``WHERE resolved_at IS NULL``. Partial keeps the index small;
    # rows resolve over time and the closed set grows much faster
    # than the open set.
    op.create_index(
        "ix_admission_backfill_exceptions_open",
        "_admission_backfill_exceptions",
        ["created_at"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    # Inverse — indexes first, then table. ``op.drop_table`` cascades
    # the FK constraints automatically.
    op.drop_index(
        "ix_admission_backfill_exceptions_open",
        table_name="_admission_backfill_exceptions",
    )
    op.drop_index(
        "ix_admission_backfill_exceptions_type",
        table_name="_admission_backfill_exceptions",
    )
    op.drop_table("_admission_backfill_exceptions")
