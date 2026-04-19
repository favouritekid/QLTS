"""enforce array-shape invariant on admission_profile list JSONB fields

Revision ID: nn20260419001
Revises: pr6a_subject_weight
Create Date: 2026-04-19

Locks `family_info` + `academic_history` to be JSONB arrays at the
source of truth:
  1. Backfill any legacy NULL rows to '[]'
  2. NOT NULL + DEFAULT '[]'::jsonb
  3. CHECK `jsonb_typeof(...) = 'array'` so direct SQL / seed scripts
     can't slip in `{}`, a string, or another non-array shape

Background: GET /api/admissions crashed (HTTP 500) when any single
profile had NULL in these columns — Pydantic response schema declares
them as List[...] (non-optional) and the list-type validator rejects
None, poisoning the whole batch. Response-layer coercion was shipped in
`b3134f94` as a belt-and-suspenders defense; this migration closes the
loop at the source of truth so new list fields added later don't
rediscover the same bug. The CHECK constraint covers the residual risk
where something writes a non-NULL but non-array JSONB value.

`admission_service.create_admission_profile()` already seeds [] on create
so in-service writes never produced bad shapes. The bad shapes that did
appear came from seed scripts, partial migrations, or direct SQL.
Backfill handles NULLs retroactively; any non-array legacy rows will
surface during the CHECK constraint add and must be fixed before this
migration can apply (expected to be zero in prod per dev DB audit).
"""
from alembic import op
import sqlalchemy as sa


revision = "nn20260419001"
down_revision = "pr6a_subject_weight"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill any existing NULL rows before flipping NOT NULL so the
    # constraint add doesn't fail on legacy data.
    op.execute(
        "UPDATE admission_profile SET family_info = '[]'::jsonb "
        "WHERE family_info IS NULL"
    )
    op.execute(
        "UPDATE admission_profile SET academic_history = '[]'::jsonb "
        "WHERE academic_history IS NULL"
    )

    op.alter_column(
        "admission_profile",
        "family_info",
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )
    op.alter_column(
        "admission_profile",
        "academic_history",
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )

    # Shape invariant — reject any non-array JSONB value written
    # through direct SQL / seed scripts. Pydantic's List[...] validator
    # at the response layer only catches None; a stray `{}` or string
    # would still poison the list endpoint the same way NULL did.
    op.create_check_constraint(
        "ck_admission_profile_family_info_is_array",
        "admission_profile",
        "jsonb_typeof(family_info) = 'array'",
    )
    op.create_check_constraint(
        "ck_admission_profile_academic_history_is_array",
        "admission_profile",
        "jsonb_typeof(academic_history) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_admission_profile_academic_history_is_array",
        "admission_profile",
        type_="check",
    )
    op.drop_constraint(
        "ck_admission_profile_family_info_is_array",
        "admission_profile",
        type_="check",
    )
    op.alter_column(
        "admission_profile",
        "academic_history",
        server_default=None,
        nullable=True,
    )
    op.alter_column(
        "admission_profile",
        "family_info",
        server_default=None,
        nullable=True,
    )
