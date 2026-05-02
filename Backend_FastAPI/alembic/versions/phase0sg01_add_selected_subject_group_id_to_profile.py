"""Phase 0 — add `AdmissionProfile.selected_subject_group_id` (single owner column).

The column persists, **forward-only**, the subject group the candidate
chose at submit time. Phase 1 #13 (`phase1_12_backfill_selected_subject_group_id`)
backfills historical rows via a 3-rule decision tree and is gated on
this column existing — but it does NOT re-define the column. This
migration is the single owner of the DDL.

Design notes:

* Type ``Integer NULL`` — nullable so existing rows stay valid (Phase 0
  cannot replay history; Phase 1 #13 fills what it can and writes the
  rest into ``_admission_backfill_exceptions``).
* FK ``subject_group(id)`` with ``ON DELETE SET NULL`` — matches the
  pattern already used by ``AdmissionProfile.offering_admission_config_id``
  for FK-traceability columns. ``SubjectGroup`` is catalog data with an
  ``is_active`` flag; soft-retire is the expected lifecycle, hard
  delete is rare. ``CASCADE`` would silently widen the blast radius to
  submitted profiles; ``RESTRICT`` would block catalog cleanup. ``SET
  NULL`` keeps the profile, drops the historical reference, and lets a
  future cleanup task surface affected profiles via a
  ``selected_subject_group_id IS NULL`` query.
* Named FK + named index so the downgrade can drop them deterministically
  by name (an unnamed FK requires Postgres auto-name lookup at downgrade
  time, which is brittle across revisions).
* Idempotent guards (`column_exists` / `fk_exists` / `index_exists`)
  match the precedent in
  ``q3a1b2c3d4e5_add_audit_columns_to_admission_profile.py`` so a
  partially-applied migration can be re-run safely.

Revision ID: phase0sg01
Revises: admstrict01
Create Date: 2026-05-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "phase0sg01"
down_revision: Union[str, None] = "admstrict01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable names — referenced by both upgrade and downgrade so a future
# migration can rely on them too.
TABLE = "admission_profile"
COLUMN = "selected_subject_group_id"
INDEX_NAME = "ix_admission_profile_selected_subject_group_id"
FK_NAME = "fk_admission_profile_selected_subject_group_id"
FK_TARGET_TABLE = "subject_group"
FK_TARGET_COLUMN = "id"


def column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def fk_exists(table_name: str, fk_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return fk_name in {fk["name"] for fk in inspector.get_foreign_keys(table_name)}


def upgrade() -> None:
    if not column_exists(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.Integer(),
                nullable=True,
                comment=(
                    "Subject group chosen by candidate at submit time. "
                    "Phase 0 owner; Phase 1 #13 backfills historical rows."
                ),
            ),
        )

    if not fk_exists(TABLE, FK_NAME):
        op.create_foreign_key(
            FK_NAME,
            source_table=TABLE,
            referent_table=FK_TARGET_TABLE,
            local_cols=[COLUMN],
            remote_cols=[FK_TARGET_COLUMN],
            ondelete="SET NULL",
        )

    if not index_exists(TABLE, INDEX_NAME):
        op.create_index(INDEX_NAME, TABLE, [COLUMN], unique=False)


def downgrade() -> None:
    # Reverse order: drop index → drop FK → drop column. Each guarded so a
    # partial downgrade can be re-run.
    if index_exists(TABLE, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE)

    if fk_exists(TABLE, FK_NAME):
        op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")

    if column_exists(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
