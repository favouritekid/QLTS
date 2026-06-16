"""add document_debt JSONB to admission_profile (fast-track nợ giấy tờ — C1)

## Why

Fast-track prepay/giữ chỗ (TUITION_PREPAY_FASTTRACK_PLAN.md C1) lets an
officer submit a profile that is eligible in every other respect but still
missing mandatory documents ("Nộp kèm nợ giấy tờ"). The system records a
snapshot of that debt — ``{codes, reason, by_user_id, at}`` — so the FE can
show "đã từng nợ + lý do" while the live badge counts the COMPUTED
``outstanding_debt_codes`` (snapshot codes ∩ docs still missing now).

## Why a SEPARATE column (not applied_rules)

The ``prevent_applied_rules_update`` trigger (``ardockeys01``) whitelists
only 7 keys (fee_* + mandatory_docs/doc_configs); any other key change on
``applied_rules`` RAISEs on UPDATE. ``document_debt`` is mutable
post-create (written at submit-with-debt time, well after creation), so it
MUST live in its own column with no immutability guard.

## What

Add ``admission_profile.document_debt JSONB NULL``. NULL = no debt ever
recorded. No backfill (existing rows simply have no debt). No index — the
column is read per-profile alongside the row, never filtered/aggregated.

## Downgrade

Drop the column. Safe: the feature is additive and the column is nullable
with no FK/constraint dependents.

Revision ID: docdebt01
Revises: leadsrch01
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "docdebt01"
down_revision: Union[str, Sequence[str], None] = "leadsrch01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable document_debt JSONB column to admission_profile."""
    op.add_column(
        "admission_profile",
        sa.Column(
            "document_debt",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Nợ giấy tờ snapshot {codes, reason, by_user_id, at} captured "
                "at staff submit-with-debt. NULL = no debt ever recorded. "
                "Separate column (NOT applied_rules) to dodge the immutability "
                "trigger."
            ),
        ),
    )


def downgrade() -> None:
    """Drop the document_debt column."""
    op.drop_column("admission_profile", "document_debt")
