"""PR #6: allow_unverified_submission per AdmissionPath + backfill profiles

Revision ID: aa1i2j3k4l5m
Revises: zz7h8i9j0k1l2
Create Date: 2026-04-24

Before PR #6, the submit validator (``_validate_documents``) accepted
any doc with ``status == 'uploaded'`` as long as it had a file_path.
That means an applicant could submit the profile the moment they
uploaded a file, even if the officer hadn't verified the document —
effectively short-circuiting the verification step.

PR #6 switches the default to require verified (or paper-submitted)
documents. For backward compatibility:

1. Add ``allow_unverified_submission`` column to ``admission_path``,
   default false, and set it to TRUE on every row that exists at
   deploy time — preserves the pre-PR behaviour for paths already in
   use. Admins opt into strict mode by flipping each path back to
   false when they're ready.

2. Backfill ``admission_profile.applied_rules`` with the key
   ``allow_unverified_submission: true`` plus a ``schema_version: 1``
   marker on every profile in a status that can still submit (draft,
   submitted, rejected, revision_requested, resubmitted). The
   validator reads from the profile's snapshot — without the
   backfill, legacy drafts would suddenly be blocked on submit. New
   profiles created after this migration get ``schema_version: 2``
   with the path's current flag value.

Rollback: ``downgrade()`` drops the column. The schema_version/flag
in profile.applied_rules is left alone on downgrade — harmless
noise; the legacy validator simply ignored those keys.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aa1i2j3k4l5m"
down_revision: Union[str, None] = "zz7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New path-level flag, default FALSE for fresh paths. IF NOT
    #    EXISTS guards against dev DBs where the column was added
    #    ahead of the migration via metadata sync.
    op.execute(
        """
        ALTER TABLE admission_path
        ADD COLUMN IF NOT EXISTS allow_unverified_submission BOOLEAN
        NOT NULL DEFAULT FALSE
        """
    )

    # 2. Preserve behaviour for existing paths — set True on every
    #    row at deploy time. Safe to re-run: UPDATE is idempotent.
    op.execute(
        "UPDATE admission_path SET allow_unverified_submission = TRUE"
    )

    # 3. Backfill applied_rules on profiles that can still reach /submit.
    #    A DB trigger (enforce_applied_rules_immutability) normally blocks
    #    any UPDATE touching this column — by design, to keep the snapshot
    #    stable for scoring. We disable it for this single migration
    #    statement and re-enable immediately, so the one legitimate
    #    post-creation write happens and the guarantee is restored.
    op.execute(
        "ALTER TABLE admission_profile DISABLE TRIGGER enforce_applied_rules_immutability"
    )
    try:
        op.execute(
            """
            UPDATE admission_profile
            SET applied_rules =
                COALESCE(applied_rules, '{}'::jsonb)
                || jsonb_build_object(
                    'allow_unverified_submission', TRUE,
                    'schema_version', 1
                )
            WHERE status IN (
                'draft', 'submitted', 'rejected', 'revision_requested', 'resubmitted'
            )
            """
        )
    finally:
        op.execute(
            "ALTER TABLE admission_profile ENABLE TRIGGER enforce_applied_rules_immutability"
        )


def downgrade() -> None:
    op.drop_column("admission_path", "allow_unverified_submission")
