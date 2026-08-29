"""PATCH-20 — create `_archived_admission_profile` table for round-end archive.

PLAN §2.1 Rule 3 (line 558-572) + §2.5 helper (line 922-934) + §1 PATCH-20 cheat
sheet (line 90) ship 2 archive tables:

* ``_archived_admission_profile`` (this migration, slot phase1_16)
* ``_archived_notification_outbox`` (phase1_17, Wave 5-E)

The cron task ``archive_expired_rounds_task`` (NOT shipped in Phase 1; lands in
a later code phase) moves profile rows whose source round end_date has passed
NOW() - INTERVAL '6 months' into this archive table. Source rows are NOT
deleted — the round is marked ``archived_at`` so the cron filter
``round.archived_at IS NULL`` prevents re-archive.

Helper ``Lead.current_admission_profile(year)`` (P1 fix #6 v2.12, PLAN line
911-928) UNIONs active + archive query so officer dashboard sees lead history
even after archive cron has run; the
``ix_archived_profile_lead_year`` index here keeps that lookup fast.

Schema parity rules
-------------------

* Mirror ALL columns of ``admission_profile`` exactly (types + nullability +
  server_default), so cron INSERT can ``SELECT * FROM admission_profile``
  without coercion.

  .. warning:: ĐÍNH CHÍNH 29-08-2026 (``arch20260829``) — dòng ngay trên SAI.

     Đo read-only trên PostgreSQL dev: 62/64 cột chung nằm ở
     ``ordinal_position`` KHÁC nhau (cột thứ 3 của nguồn là ``citizen_id``,
     của archive là ``offering_admission_config_id``); ``archived_at`` ở vị
     trí 65 nên cột thêm sau này rơi xuống 66..77; và ``server_default`` của
     ``id``/``created_at``/``updated_at`` khác bản nguồn một cách CỐ Ý (hàng
     archive giữ id + dấu thời gian GỐC, không sinh lại).

     Nên ``SELECT *`` theo VỊ TRÍ không an toàn — nó nhét ``citizen_id`` vào
     ``offering_admission_config_id``. Mọi đường ghi archive BẮT BUỘC liệt kê
     CỘT ĐÍCH TƯỜNG MINH. Parity thật sự có (và được test khoá) là parity
     THEO TÊN + kiểu + nullability. Xem docstring của ``arch20260829``.

     Chỉ sửa docstring — KHÔNG đụng DDL của migration đã áp ở production.
* Add ONE archive-metadata column ``archived_at TIMESTAMPTZ NOT NULL DEFAULT
  now()`` — set automatically when cron INSERTs the row.
* NO foreign keys (archive must outlive source row deletes — cron does not
  delete source today, but a later retention policy might).
* NO unique constraints (preserve historical violators if active table
  contract evolves; e.g., the Wave 4 (lead_id, academic_year) composite swap
  cannot retroactively reject a row already archived under the old contract).
* NO check constraints for the same reason; Wave 3 phase1_11 will extend the
  status CHECK from 10 to 14 values, and an archive row from before that
  extend must not be rejected on round-trip.
* Re-use existing ENUM type ``conduct_grade`` (created by phase1_09a) via
  ``create_type=False``.

Idempotent guards via SQLAlchemy ``inspector`` mirror the phase1_19a template:

* table create skipped if ``_archived_admission_profile`` already present;
* named index skipped if already present;
* downgrade short-circuits if the table is gone.

Defer to follow-up (NOT in Wave 5-D D-i scope)
----------------------------------------------

* ORM class ``ArchivedAdmissionProfile`` (ship together with the
  ``Lead.current_admission_profile`` helper or in a paired follow-up).
* The cron task itself — ``archive_expired_rounds_task`` is a code-phase
  shipment, not Phase 1.
* ``archive_reason`` discriminator + ``original_round_id`` extract — only
  needed when multi-trigger archive lands; today the single round-end-date
  trigger keeps the table append-only and uniform.

Revision ID: phase1_16
Revises: phase1_19c
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_16"
# Chain link updated 2026-05-25: insert phase1_19c5 between phase1_19c
# (UPPERCASE seed) and this migration so the lowercase conversion runs
# before phase3_01's pre-flight check. See phase1_19c5 module docstring
# for root cause + memory references.
down_revision: Union[str, None] = "phase1_19c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "_archived_admission_profile"
INDEX_LEAD_YEAR = "ix_archived_profile_lead_year"


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


# ENUM ``conduct_grade`` is owned by phase1_09a; re-use here without re-creating.
_conduct_grade = postgresql.ENUM(
    "TB", "KHA", "TOT", name="conduct_grade", create_type=False
)


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            # ── Identity / FK references (FK constraints intentionally omitted) ──
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("offering_admission_config_id", sa.Integer(), nullable=True),
            sa.Column("selected_subject_group_id", sa.Integer(), nullable=True),
            sa.Column("academic_year", sa.Integer(), nullable=False),
            sa.Column("citizen_id", sa.String(12), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'draft'"),
            ),
            # ── Personal info ──
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("dob", sa.Date(), nullable=True),
            sa.Column("gender", sa.String(50), nullable=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("social_insurance_number", sa.String(50), nullable=True),
            sa.Column("nationality", sa.String(100), nullable=True),
            sa.Column("ethnicity", sa.String(100), nullable=True),
            sa.Column("religion", sa.String(100), nullable=True),
            sa.Column("disability_type", sa.String(100), nullable=True),
            sa.Column("permanent_province", sa.String(100), nullable=True),
            sa.Column("permanent_district", sa.String(100), nullable=True),
            sa.Column("permanent_ward", sa.String(100), nullable=True),
            sa.Column("permanent_residential_group", sa.String(150), nullable=True),
            sa.Column("permanent_street_address", sa.String(255), nullable=True),
            sa.Column("place_of_birth", sa.String(255), nullable=True),
            sa.Column("native_place", sa.String(255), nullable=True),
            sa.Column("union_entry_date", sa.DateTime(), nullable=True),
            sa.Column("party_entry_date", sa.DateTime(), nullable=True),
            sa.Column("party_official_entry_date", sa.DateTime(), nullable=True),
            # ── Optimistic lock ──
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            # ── Snapshot / JSONB ──
            sa.Column("applied_rules", postgresql.JSONB(), nullable=False),
            sa.Column(
                "family_info",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "academic_history",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            # ── Source timestamps ──
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            # ── Approval audit ──
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_by_id", sa.Integer(), nullable=True),
            sa.Column("approval_notes", sa.Text(), nullable=True),
            # ── Phase E survey ──
            sa.Column("survey_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("survey_tracking_id", sa.String(64), nullable=True),
            # ── Rejection audit ──
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_by_id", sa.Integer(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            # ── Revision-request audit ──
            sa.Column("revision_requested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revision_requested_by_id", sa.Integer(), nullable=True),
            sa.Column("revision_reason", sa.Text(), nullable=True),
            # ── Resubmit audit ──
            sa.Column("resubmitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resubmitted_by_id", sa.Integer(), nullable=True),
            sa.Column("resubmit_notes", sa.Text(), nullable=True),
            # ── Override audit ──
            sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("overridden_by_id", sa.Integer(), nullable=True),
            sa.Column("override_reason", sa.Text(), nullable=True),
            # ── Confirmation audit ──
            sa.Column("confirmed_by_id", sa.Integer(), nullable=True),
            sa.Column("assigned_reviewer_id", sa.Integer(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_via", sa.String(20), nullable=True),
            # ── Drop-out side-channel ──
            sa.Column(
                "is_dropped",
                sa.Boolean(),
                nullable=True,
                server_default=sa.text("false"),
            ),
            sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dropped_by_id", sa.Integer(), nullable=True),
            sa.Column("dropped_reason", sa.Text(), nullable=True),
            # ── Wave 2 eligibility scalars (phase1_09a) ──
            sa.Column("gpa_overall", sa.Numeric(precision=4, scale=2), nullable=True),
            sa.Column("conduct", _conduct_grade, nullable=True),
            sa.Column("health_category", sa.SmallInteger(), nullable=True),
            sa.Column("graduation_year", sa.SmallInteger(), nullable=True),
            # ── Wave 1 PR-1D multi-NV gate (phase1_08) ──
            sa.Column(
                "uses_choice_engine",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            # ── Archive metadata (1 column only) ──
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not index_exists(TABLE, INDEX_LEAD_YEAR):
        op.create_index(
            INDEX_LEAD_YEAR,
            TABLE,
            ["lead_id", "academic_year"],
        )


def downgrade() -> None:
    if not table_exists(TABLE):
        return

    if index_exists(TABLE, INDEX_LEAD_YEAR):
        op.drop_index(INDEX_LEAD_YEAR, table_name=TABLE)

    op.drop_table(TABLE)
