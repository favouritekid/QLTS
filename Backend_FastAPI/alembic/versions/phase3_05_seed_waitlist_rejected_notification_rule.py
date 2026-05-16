"""Phase 3 Wave 6 — seed NotificationRule cho ADMISSION_WAITLIST_REJECTED

2026-05-16 ship: T11 endpoint shipped Wave 5 với event catalog declared,
nhưng notification_rule chưa seed → dispatcher fail-closed (zero
notification sent khi manager click reject).

Wave 6 closes the gap: seed minimal in-app rule mirror existing
admission_waitlist_promoted row (id=73 trên dev) — same shape,
recipient_config=specific_users (broadcast tới list users), default
empty params.

Sau deploy, operator có thể tune via /admin/notification-rules:
  - Đổi recipient_config sang lead_owner / lead_contact (candidate email)
  - Add channels qua notification_action rows (email cho candidate)
  - Customize message_template

IDEMPOTENT — INSERT WHERE NOT EXISTS check by event column.

VERIFICATION (post-deploy):
    SELECT id, event FROM notification_rule
    WHERE event='admission_waitlist_rejected';
    -- Expected: 1 row

Revision ID: phase3_05
Revises: phase3_04
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_05"
down_revision: Union[str, None] = "phase3_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed ADMISSION_WAITLIST_REJECTED notification rule."""
    conn = op.get_bind()

    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM notification_rule WHERE event='admission_waitlist_rejected'"
        )
    ).scalar()
    print(f"[phase3_05] Pre-flight: existing waitlist_rejected rules={pre_count}")

    # Mirror existing admission_waitlist_promoted shape — minimal in-app
    # notification, specific_users resolver (operator customize qua admin UI).
    result = conn.execute(
        sa.text(
            """
            INSERT INTO notification_rule (
                event,
                title_template,
                message_template,
                notification_type,
                recipient_config,
                enabled,
                bypass_consent
            )
            SELECT
                CAST('admission_waitlist_rejected' AS VARCHAR),
                CAST('Bị loại khỏi danh sách dự bị' AS VARCHAR),
                CAST('Có cập nhật mới liên quan đến hồ sơ #$application_id (bị loại khỏi danh sách dự bị).' AS TEXT),
                CAST('info' AS VARCHAR),
                CAST('{"resolver_type": "specific_users", "params": {}}' AS JSON),
                TRUE,
                FALSE
            WHERE NOT EXISTS (
                SELECT 1 FROM notification_rule
                WHERE event='admission_waitlist_rejected'
            )
            """
        )
    )
    print(f"[phase3_05] Seeded {result.rowcount} rule row(s) (skipped if exists).")


def downgrade() -> None:
    """Remove the seeded rule (idempotent — delete by event)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "DELETE FROM notification_rule WHERE event='admission_waitlist_rejected'"
        )
    )
    print(f"[phase3_05] Removed {result.rowcount} rule row(s).")
