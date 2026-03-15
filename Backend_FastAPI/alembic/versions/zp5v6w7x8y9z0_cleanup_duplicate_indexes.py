"""cleanup: remove duplicate indexes on admission_confirmation_token and student

Revision ID: zp5v6w7x8y9z0
Revises: zo4u5v6w7x8y9
Create Date: 2026-03-15 19:00:00.000000

DB-first cleanup to align with SQLAlchemy model expectations.

admission_confirmation_token:
  - DB has unique constraints (admission_confirmation_token_profile_id_key,
    admission_confirmation_token_token_key) which automatically create unique
    indexes, PLUS redundant plain indexes (ix_admission_confirmation_token_profile_id,
    ix_admission_confirmation_token_token).
  - Model uses `unique=True, index=True` which expects unique indexes only.
  - Fix: drop the unique constraints (keeping the data from unique indexes created
    by the model pattern), then drop the redundant plain indexes.
    Net result: 2 unique indexes (matching model), no constraints, no plain dupes.

student:
  - student_code has unique constraint `uq_student_code` (creates unique index)
    PLUS unique index `ix_student_student_code` (from model `unique=True, index=True`).
  - Fix: drop the explicit unique constraint `uq_student_code`, keep
    `ix_student_student_code` which is the model-created unique index.
  - Similarly admission_profile_id has `ix_student_admission_profile_id` (unique)
    which is the model's `unique=True, index=True` — no change needed there.

No enforcement is lost: uniqueness remains via the unique indexes.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zp5v6w7x8y9z0"
down_revision: Union[str, None] = "zo4u5v6w7x8y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # admission_confirmation_token: consolidate to unique indexes only
    # =========================================================================

    # Step 1: Drop redundant plain indexes (unique constraints already cover these)
    for idx_name in [
        "ix_admission_confirmation_token_profile_id",
        "ix_admission_confirmation_token_token",
    ]:
        result = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name"
        ).bindparams(name=idx_name))
        if result.fetchone():
            op.drop_index(idx_name, table_name="admission_confirmation_token")
            print(f"  [token] Dropped redundant index {idx_name}")

    # Step 2: Drop unique constraints (their backing indexes will be dropped too)
    for con_name in [
        "admission_confirmation_token_profile_id_key",
        "admission_confirmation_token_token_key",
    ]:
        result = conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :name"
        ).bindparams(name=con_name))
        if result.fetchone():
            op.drop_constraint(con_name, "admission_confirmation_token", type_="unique")
            print(f"  [token] Dropped unique constraint {con_name}")

    # Step 3: Re-create as unique indexes (matching model `unique=True, index=True`)
    for idx_name, col_name in [
        ("ix_admission_confirmation_token_profile_id", "profile_id"),
        ("ix_admission_confirmation_token_token", "token"),
    ]:
        result = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name"
        ).bindparams(name=idx_name))
        if not result.fetchone():
            op.create_index(idx_name, "admission_confirmation_token", [col_name], unique=True)
            print(f"  [token] Created unique index {idx_name}")

    # =========================================================================
    # student.student_code: consolidate to one unique index
    # =========================================================================

    # Drop the explicit unique constraint (its backing index uq_student_code will go too)
    result = conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'uq_student_code'"
    ))
    if result.fetchone():
        op.drop_constraint("uq_student_code", "student", type_="unique")
        print("  [student] Dropped duplicate unique constraint uq_student_code")
        print("  [student] Uniqueness still enforced by ix_student_student_code (UNIQUE INDEX)")


def downgrade() -> None:
    conn = op.get_bind()

    # Restore student unique constraint
    result = conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = 'uq_student_code'"
    ))
    if not result.fetchone():
        op.create_unique_constraint("uq_student_code", "student", ["student_code"])

    # Restore admission_confirmation_token unique constraints + plain indexes
    # Drop the unique indexes first
    for idx_name in [
        "ix_admission_confirmation_token_profile_id",
        "ix_admission_confirmation_token_token",
    ]:
        result = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name"
        ).bindparams(name=idx_name))
        if result.fetchone():
            op.drop_index(idx_name, table_name="admission_confirmation_token")

    # Re-create unique constraints
    op.create_unique_constraint(
        "admission_confirmation_token_profile_id_key",
        "admission_confirmation_token", ["profile_id"]
    )
    op.create_unique_constraint(
        "admission_confirmation_token_token_key",
        "admission_confirmation_token", ["token"]
    )

    # Re-create plain indexes
    op.create_index(
        "ix_admission_confirmation_token_profile_id",
        "admission_confirmation_token", ["profile_id"]
    )
    op.create_index(
        "ix_admission_confirmation_token_token",
        "admission_confirmation_token", ["token"]
    )
