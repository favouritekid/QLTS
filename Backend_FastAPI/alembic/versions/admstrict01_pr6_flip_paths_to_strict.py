"""ADM-024: flip allow_unverified_submission=false on all admission_path rows

Revision ID: admstrict01
Revises: mlharden01
Create Date: 2026-04-30

Realises PR #6's strict-mode default. Before this migration every
``admission_path`` row carried ``allow_unverified_submission = true``
(legacy compatibility set by ``aa1i2j3k4l5m``); the strict gate was
opt-in per path and never flipped on prod.

Pre-migration prod state (audit 2026-04-29 — see
``Documents/ADM-024_AUDIT_2026-04-29.md``):

- 52 ``admission_path`` rows, all ``allow_unverified_submission = true``
- 4 paths in active use (ids 106, 109, 112, 115); 48 zero-traffic
- 9 ``admission_profile`` rows, all ``applied_rules.schema_version = 1``
- 0 docs verified, 0 docs paper-submitted across 54 ``profile_document``
- All 9 in-flight profiles are officer-entered (no applicant
  self-service traffic on prod yet)

Decision (Q15a, 2026-04-30): flip every path to strict. Officer team
handles verification training as normal ops; current profiles are
officer-entered so workflow context already exists.

Safety
------
The DB trigger ``enforce_applied_rules_immutability`` keeps every
in-flight profile's snapshot intact. Submit-time validation reads
``applied_rules.allow_unverified_submission`` from the snapshot, not
from the path — so the 9 existing profiles continue to use legacy
behaviour and remain submittable with ``uploaded`` docs. Only profiles
*created after* this migration snapshot ``false`` (via
``create_profile``) and require ``verified``/``paper_submitted`` docs.

Idempotent
----------
Strict predicate ``WHERE allow_unverified_submission = TRUE`` makes
this safe to re-run on a database where some or all rows are already
flipped; matched rows = 0 on a re-run.

Downgrade caveat
----------------
``downgrade()`` flips path rows back to ``true`` but does NOT rewrite
profile snapshots. Profiles created during the strict window keep
``applied_rules.allow_unverified_submission = false`` (immutable
trigger) and continue to require verified docs even after downgrade.
This matches the snapshot contract — historical profiles are bound
to the rules that were in effect when they were created.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "admstrict01"
down_revision: Union[str, None] = "mlharden01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE admission_path
        SET allow_unverified_submission = FALSE
        WHERE allow_unverified_submission = TRUE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE admission_path
        SET allow_unverified_submission = TRUE
        WHERE allow_unverified_submission = FALSE
        """
    )
