"""Q9 #07 Phase D.0a — Enable pg_unaccent extension.

Revision ID: q9_07_d0a
Revises: phase1_09
Create Date: 2026-05-18

Enable PostgreSQL `unaccent` extension for diacritic-insensitive school
name search (Phase D candidate FE dropdown). Required by Phase D.0b
VnSchool search endpoint (`GET /api/v2/vn-school/search`).

Why needed:
- Vietnamese names contain diacritics: "Trần Phú" vs "Tran Phu"
- Users may type either form in candidate FE search
- Without unaccent: ILIKE '%Tran Phu%' misses 'Trần Phú' → bad UX

Test post-migration:
    SELECT unaccent('Trần Phú');  -- expected: 'Tran Phu'

Extension is read-only schema — safe to enable on production. Drops are
idempotent (`CREATE EXTENSION IF NOT EXISTS`).

Memory [[verify-schema-before-proposing]]: confirmed `unaccent` NOT
in pg_extension before this migration (psql query 2026-05-18 prod=dev).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "q9_07_d0a"
down_revision: Union[str, None] = "phase1_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    # NOTE: do NOT drop unaccent on downgrade — other features may depend
    # on it (search, sort). Extension stays. Downgrade is no-op.
    pass
