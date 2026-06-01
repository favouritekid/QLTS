"""Allow 'downloaded' in document_audit_log.action CHECK constraint.

Revision ID: docdl_audit_001
Revises: naflood001
Create Date: 2026-06-01

PR1 Commit 1 (Gap 1 — A09 Logging). The new authed document-download
endpoint
    GET /api/admissions/{profile_id}/documents/{document_id}/download
records a ``downloaded`` audit row so PII document access (CCCD, học bạ,
priority evidence) leaves a trail — the previous public ``/uploads``
static serve logged nothing. ``DocumentAuditLog.action`` is gated by the
DB CHECK constraint ``ck_document_audit_log_action``, whose enum did NOT
include ``downloaded``; inserting it would raise IntegrityError. This
migration widens the constraint by one value.

upgrade()
---------
DROP + re-ADD ``ck_document_audit_log_action`` with ``'downloaded'``
appended. Additive only — every previously-valid value stays valid, so
no existing row can violate the new constraint. ``DROP ... IF EXISTS``
keeps it idempotent.

downgrade()
-----------
Restore the original 6-value enum. SAFE because ``downloaded`` rows are
append-only audit records that no business logic reads; if any exist the
downgrade would fail the re-ADD (Postgres validates existing rows), which
is the correct fail-closed signal that the new action is already in use —
purge or retain those rows deliberately before downgrading.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "docdl_audit_001"
down_revision: Union[str, None] = "naflood001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD = "('uploaded','verified','rejected','reset','paper_submitted','deleted')"
_NEW = "('uploaded','verified','rejected','reset','paper_submitted','deleted','downloaded')"


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE document_audit_log "
            "DROP CONSTRAINT IF EXISTS ck_document_audit_log_action;"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE document_audit_log "
            "ADD CONSTRAINT ck_document_audit_log_action "
            f"CHECK (action IN {_NEW});"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE document_audit_log "
            "DROP CONSTRAINT IF EXISTS ck_document_audit_log_action;"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE document_audit_log "
            "ADD CONSTRAINT ck_document_audit_log_action "
            f"CHECK (action IN {_OLD});"
        )
    )
