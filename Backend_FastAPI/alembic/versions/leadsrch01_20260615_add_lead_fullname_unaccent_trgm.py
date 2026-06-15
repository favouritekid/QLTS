"""Lead search unaccent — pg_trgm + f_unaccent wrapper + GIN trgm index on lead.full_name.

Revision ID: leadsrch01
Revises: sms20260611_seed
Create Date: 2026-06-15

Diacritic-insensitive lead name search (LEAD_FILTER_UX_PLAN §3). Typing
"nguyen van" should match "Nguyễn Văn". The `unaccent` extension is already
enabled by q9_07_d0a (2026-05-18, for VnSchool search) — this migration only
adds the parts still missing (verified dev 2026-06-15: unaccent present,
pg_trgm absent):

- pg_trgm extension → trigram GIN index keeps ILIKE fast at any scale.
- f_unaccent(text) IMMUTABLE wrapper. Raw unaccent() is only STABLE, so it
  cannot be used inside a functional index. The 2-argument dictionary form
  unaccent('public.unaccent', $1) pins the dictionary → deterministic →
  safe to declare IMMUTABLE.
- functional GIN trgm index on f_unaccent(full_name).

Repo uses `f_unaccent(full_name) ILIKE f_unaccent(:term)` — see the search
branch in lead_repository.py._build_filters.

Idempotent (IF NOT EXISTS / CREATE OR REPLACE). Downgrade drops the index +
wrapper function only; it does NOT drop the pg_trgm / unaccent extensions
because other features (VnSchool search, sort) may depend on them.

Memory [[migration-predicate-safety]], [[migration-rollback-data-preservation-review]].
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "leadsrch01"
down_revision: Union[str, None] = "sms20260611_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # unaccent already enabled by q9_07_d0a (2026-05-18) — do NOT recreate.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Immutable wrapper around unaccent so it can be used in a functional index.
    # The 2-arg form pins the dictionary, making the result deterministic.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION f_unaccent(text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE PARALLEL SAFE STRICT
        AS $func$ SELECT public.unaccent('public.unaccent', $1) $func$
        """
    )

    # Functional GIN trigram index → fast diacritic-insensitive ILIKE on name.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_lead_fullname_unaccent_trgm
        ON lead USING gin (f_unaccent(full_name) gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lead_fullname_unaccent_trgm")
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
    # Keep pg_trgm + unaccent extensions — other features may rely on them.
