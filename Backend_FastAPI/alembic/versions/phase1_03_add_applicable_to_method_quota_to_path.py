"""phase1_03: add applicable_to + method_quota to admission_path

Revision ID: phase1_03
Revises: phase1_02
Create Date: 2026-05-04

#184 Wave 1 PR-1B' — third migration in Phase 1 Schema chain
(PLAN §4 line 2636-2657). Two columns + one PostgreSQL ENUM type
+ one GIN index ship together because the two columns are one
semantic unit (audience filter + per-method quota tier) and the
PLAN file title spells them as a pair:
``add_applicable_to_method_quota_to_path``.

Schema additions
----------------
* ``admission_audience`` ENUM type — 5 candidate-education-level
  buckets per PLAN line 605-606: ``POST_THCS``, ``POST_THPT``,
  ``LIEN_THONG_TC``, ``LIEN_THONG_CD``, ``VLVH``. Created BEFORE
  the column add so the array element type resolves cleanly. Down
  migration drops the type AFTER the column to satisfy FK/dep
  ordering.

* ``admission_path.applicable_to`` ``admission_audience[]`` nullable.
  Audience filter for storefront / admin path-list query. NULL =
  legacy path applicable to every audience (Phase 1+2 contract):
  query MUST preserve NULL via
  ``WHERE (applicable_to IS NULL OR applicable_to @> ARRAY[:audience]::admission_audience[])``
  per PLAN line 2649-2655. Phase 3 enables strict filter only after
  validator gate "X path null applicable_to → admin set trước".

* ``admission_path.method_quota`` integer nullable. Per-method
  quota tier between annual `admission_round` quota (Phase 2) and
  per-criteria `group_quota` (existing). NULL = no method-level
  cap; service derives effective quota from round/group fallback.

* ``ix_admission_path_applicable_to`` GIN index on
  ``applicable_to``. REQUIRED because the query contract (PLAN
  line 2646-2657) is ``@>`` containment and ``&&`` overlap. The
  ANTI-PATTERN ``WHERE :audience = ANY(applicable_to)`` produces
  correct results but the Postgres planner cannot pick GIN for
  ``= ANY(arr)`` → seq-scan on every storefront audience filter.
  Smoke test (staging clone D12-D14): ``EXPLAIN ANALYZE`` must
  show ``Bitmap Index Scan on ix_admission_path_applicable_to``
  for the audience-filter endpoint; ``Seq Scan`` means the
  repository is using the wrong operator.

Idempotency
-----------
Pure additive — no backfill statements, no UPDATE/DELETE/INSERT
gated WHERE clauses needed. Re-applying upgrade after partial
failure: the ``IF NOT EXISTS`` guards on the ENUM type creation
catch the early failure mode where the type was created but the
column add raised; the column add itself raises a clear
``DuplicateColumn`` if already present (alembic operator does
not silently no-op, but that signal is the cleanest way to flag
the partial-state bug for ops to bisect).

Down-revision chain: ``phase1_19b → phase1_01 → phase1_02 →
phase1_03``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_03"
down_revision: Union[str, None] = "phase1_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ENUM values per PLAN line 605-606. Frozen here as the migration
# is the source-of-truth for the type definition; the SQLAlchemy
# model mirrors these values via ``postgresql.ENUM(name=...,
# create_type=False)`` so model drift can't silently extend the type.
ADMISSION_AUDIENCE_VALUES: tuple[str, ...] = (
    "POST_THCS",
    "POST_THPT",
    "LIEN_THONG_TC",
    "LIEN_THONG_CD",
    "VLVH",
)


def upgrade() -> None:
    # 1. Create the admission_audience ENUM type. ``checkfirst=True``
    #    (alembic default for ENUM ``create``) makes the call
    #    idempotent on partial-failure replay.
    audience_enum = postgresql.ENUM(
        *ADMISSION_AUDIENCE_VALUES,
        name="admission_audience",
        create_type=False,
    )
    audience_enum.create(op.get_bind(), checkfirst=True)

    # 2. admission_path.applicable_to — array of admission_audience.
    #    NULL = legacy path / no audience filter (Phase 1+2 query
    #    contract preserves NULL via OR branch).
    op.add_column(
        "admission_path",
        sa.Column(
            "applicable_to",
            postgresql.ARRAY(audience_enum),
            nullable=True,
            comment=(
                "Audience filter ARRAY of admission_audience enum. "
                "NULL = applicable to every audience (legacy path / "
                "Phase 1+2 contract). Query MUST use @> containment "
                "or && overlap (NEVER = ANY) to hit the GIN index."
            ),
        ),
    )

    # 3. admission_path.method_quota — per-method quota tier.
    #    NULL = no method-level cap (round/group fallback).
    op.add_column(
        "admission_path",
        sa.Column(
            "method_quota",
            sa.Integer(),
            nullable=True,
            comment=(
                "Per-method admission quota. NULL = inherit from "
                "round.admit_quota (Phase 2). Service-layer guard "
                "(Phase 2 line 3973): sum(method_quota for path in "
                "round.paths) <= round.admit_quota."
            ),
        ),
    )

    # 4. GIN index for the @>/&& query contract. Required for the
    #    storefront audience filter endpoint to hit an index path.
    op.create_index(
        "ix_admission_path_applicable_to",
        "admission_path",
        ["applicable_to"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Inverse order — index → column → enum type.
    op.drop_index(
        "ix_admission_path_applicable_to",
        table_name="admission_path",
    )
    op.drop_column("admission_path", "method_quota")
    op.drop_column("admission_path", "applicable_to")

    # Drop the ENUM type LAST so PG doesn't error on type-still-in-use
    # (the ARRAY column referenced it). ``checkfirst=True`` keeps the
    # downgrade re-runnable.
    audience_enum = postgresql.ENUM(
        *ADMISSION_AUDIENCE_VALUES,
        name="admission_audience",
        create_type=False,
    )
    audience_enum.drop(op.get_bind(), checkfirst=True)
