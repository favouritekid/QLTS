"""add minor_correction_allowed_fields to admission_path

Revision ID: dd4l5m6n7o8p
Revises: cc3k4l5m6n7o
Create Date: 2026-04-25

Per-path allowlist for post-approval minor corrections. Governance
setting — admin opts in field-by-field for each AdmissionPath. Default
empty list (no corrections allowed) means every path explicitly grants
fields; the SAFE catalog cap stays the absolute upper bound regardless
of what admin selects.

Rationale:
- JSONB array (not Postgres array) for forward-compat with future
  metadata (e.g. per-field expiry dates, per-role caps).
- NOT NULL with server_default '[]'::jsonb so missing-key reads always
  return [] without app-side coalesce.
- Check constraint asserts the column is always a JSONB array — defense
  against accidental dict/string assignment in service code.
- No backfill: empty default for every existing path. Admin must
  explicitly enable each field per path. Hồ sơ cũ vẫn không sửa được
  cho đến khi admin bật.

Rollback drops the column (and the check constraint with it).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "dd4l5m6n7o8p"
down_revision: Union[str, None] = "cc3k4l5m6n7o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE admission_path
        ADD COLUMN IF NOT EXISTS minor_correction_allowed_fields JSONB
        NOT NULL DEFAULT '[]'::jsonb
        """
    )
    op.create_check_constraint(
        "ck_admission_path_minor_correction_is_array",
        "admission_path",
        "jsonb_typeof(minor_correction_allowed_fields) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_admission_path_minor_correction_is_array",
        "admission_path",
        type_="check",
    )
    op.drop_column("admission_path", "minor_correction_allowed_fields")
