"""phase1_06: add admission_path_id FK + partial index to document_group

Revision ID: phase1_06
Revises: phase1_05
Create Date: 2026-05-04

#184 Wave 1 PR-1C' — sixth migration in Phase 1 Schema chain
(PLAN §4 line 2668-2683). One nullable FK column + one partial
index. Pure additive — existing 2-tier resolution
(method-specific override + shared) keeps working unchanged
because legacy document_group rows have ``admission_path_id IS
NULL``.

Schema additions
----------------
* ``document_group.admission_path_id`` integer nullable FK to
  ``admission_path(id)`` ON DELETE SET NULL. NULL semantic:
  - With ``admission_method_id`` non-null + path NULL → legacy
    method-specific override (existing tier 2).
  - With ``admission_method_id`` NULL + path NULL → legacy
    shared / offering_type default (existing tier 3).
  - With ``admission_path_id`` non-null → NEW path-specific
    override (tier 1) — wins over both legacy tiers when the
    profile's path matches.

* ``ix_doc_group_path`` partial btree index on
  ``admission_path_id`` WHERE ``admission_path_id IS NOT NULL``.
  Partial because most rows are legacy (method or shared) →
  index only the path-specific rows for a smaller / hotter
  index; the resolution rule's tier-1 query
  ``WHERE admission_path_id = X`` is the only consumer.

Service-layer invariant (NOT enforced by DB)
--------------------------------------------
Per PLAN line 2671-2682, when admin creates / updates a
DocumentGroup with ``admission_path_id`` set, the service must
validate:

* ``DocumentGroup.offering_type_id == path.academic_info.offering.offering_type_id``
* ``DocumentGroup.admission_method_id`` is None OR equals
  ``path.admission_method_id``

Mismatch → ``BusinessRuleViolation``. Reason: the resolution
rule chooses path-level groups BEFORE checking offering_type /
method, so an inconsistent group would silently leak into a
profile that doesn't match the path's offering.

The invariant lives in ``DocumentGroupService.create`` /
``update`` — see PR-1C' BE diff. Migration owns the schema only.

Down-revision chain: ``phase1_03 → phase1_05 → phase1_06``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "phase1_06"
down_revision: Union[str, None] = "phase1_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add admission_path_id nullable FK. ON DELETE SET NULL means
    #    deleting a path doesn't cascade-kill its document groups —
    #    they fall back to the method / shared tier automatically.
    op.add_column(
        "document_group",
        sa.Column(
            "admission_path_id",
            sa.Integer(),
            nullable=True,
            comment=(
                "Path-level override (tier 1 of 3-tier resolution). "
                "NULL = legacy method/shared override. ON DELETE SET "
                "NULL so path delete falls back to lower tiers."
            ),
        ),
    )
    op.create_foreign_key(
        "fk_document_group_admission_path",
        "document_group",
        "admission_path",
        ["admission_path_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Partial btree index on the FK column. Tier-1 query is
    #    ``WHERE admission_path_id = X`` so a btree on the column
    #    is the right shape; partial keeps it small (most rows are
    #    legacy = NULL).
    op.create_index(
        "ix_doc_group_path",
        "document_group",
        ["admission_path_id"],
        postgresql_where=sa.text("admission_path_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Inverse order — index → FK → column.
    op.drop_index("ix_doc_group_path", table_name="document_group")
    op.drop_constraint(
        "fk_document_group_admission_path",
        "document_group",
        type_="foreignkey",
    )
    op.drop_column("document_group", "admission_path_id")
