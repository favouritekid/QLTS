"""admission survey feedback — profile columns + feedback table

Revision ID: nn20260420001
Revises: nn20260419001
Create Date: 2026-04-20

Phase E (ZNS template 426903 — khảo sát dịch vụ tư vấn, daily scheduler
30 days post-approval). Adds two sides of the audit trail:

1. Send-side cursor on `admission_profile`:
   - `survey_sent_at timestamptz NULL` — set once when scheduler
     dispatches `APPLICATION_SURVEY_DUE`. Primary dedupe filter
     (``WHERE survey_sent_at IS NULL``).
   - `survey_tracking_id varchar(64) NULL UNIQUE` — UUID-per-profile
     passed as Zalo `tracking_id` on send. Echoed back verbatim in
     the `user_feedback` webhook, used to map feedback → profile.

2. Receive-side feedback store `admission_survey_feedback`:
   - Unique on `tracking_id` so a re-delivered webhook updates rather
     than inserts. Dedupe is intentional — Zalo may retry.
   - `profile_id` nullable: if tracking_id doesn't match any profile
     (e.g. ghost delivery, manual test), we still capture the feedback
     for ops review instead of dropping it on the floor.
   - `rate` CHECK 1..5 mirrors Zalo spec; a bad value means someone is
     spoofing us and we refuse to poison the metric.
   - `feedback_tags` follows the list-JSONB invariant from
     nn20260419001 (NOT NULL DEFAULT '[]' + CHECK jsonb_typeof=array).
   - `raw_payload` keeps the entire webhook body for future-proofing —
     Zalo has added fields mid-flight before (notably 2026-03-16 policy
     update) and re-parsing from raw is cheaper than a backfill.

Backfill is a no-op: fresh columns start NULL on all existing profiles.
Phase E scheduler also applies a baseline cutoff (see settings.py) so
old approvals never enter the scan window.
"""
from alembic import op
import sqlalchemy as sa


revision = "nn20260420001"
down_revision = "nn20260419001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Send-side cursor on admission_profile ---
    op.add_column(
        "admission_profile",
        sa.Column("survey_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "admission_profile",
        sa.Column("survey_tracking_id", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_admission_profile_survey_tracking_id",
        "admission_profile",
        ["survey_tracking_id"],
    )
    # Cursor index for the scheduler scan — WHERE survey_sent_at IS NULL
    # is the hot path; a partial index keeps it tiny after the cutover.
    op.create_index(
        "ix_admission_profile_survey_pending",
        "admission_profile",
        ["approved_at"],
        unique=False,
        postgresql_where=sa.text("survey_sent_at IS NULL AND status = 'approved'"),
    )

    # --- Receive-side feedback store ---
    op.create_table(
        "admission_survey_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tracking_id", sa.String(length=64), nullable=False),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("admission_profile.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("zalo_msg_id", sa.String(length=64), nullable=True),
        sa.Column("rate", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "feedback_tags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("submit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "raw_payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tracking_id", name="uq_admission_survey_feedback_tracking_id"
        ),
        sa.CheckConstraint("rate BETWEEN 1 AND 5", name="ck_survey_rate_range"),
        sa.CheckConstraint(
            "jsonb_typeof(feedback_tags) = 'array'",
            name="ck_survey_feedback_tags_is_array",
        ),
    )
    op.create_index(
        "ix_admission_survey_feedback_profile_id",
        "admission_survey_feedback",
        ["profile_id"],
    )
    op.create_index(
        "ix_admission_survey_feedback_received_at",
        "admission_survey_feedback",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admission_survey_feedback_received_at",
        table_name="admission_survey_feedback",
    )
    op.drop_index(
        "ix_admission_survey_feedback_profile_id",
        table_name="admission_survey_feedback",
    )
    op.drop_table("admission_survey_feedback")

    op.drop_index(
        "ix_admission_profile_survey_pending",
        table_name="admission_profile",
    )
    op.drop_constraint(
        "uq_admission_profile_survey_tracking_id",
        "admission_profile",
        type_="unique",
    )
    op.drop_column("admission_profile", "survey_tracking_id")
    op.drop_column("admission_profile", "survey_sent_at")
