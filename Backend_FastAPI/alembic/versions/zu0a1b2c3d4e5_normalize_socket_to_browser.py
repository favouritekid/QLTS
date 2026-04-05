"""normalize channel value 'socket' to 'browser' in notification tables

Revision ID: zu0a1b2c3d4e5
Revises: zt9z0a1b2c3d4
Create Date: 2026-03-24

Normalizes legacy channel value 'socket' to canonical 'browser' in:
- notification_rule.channels (JSON array)
- notification_action.channel (VARCHAR)
- notification_template.supported_channels (JSONB array)
- notification_template column default

This migration is reversible: downgrade restores 'browser' back to 'socket'
in the same columns.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'zu0a1b2c3d4e5'
down_revision: Union[str, None] = '1a25aa8e2984'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- Pre-check: count affected rows ---
    rule_count = conn.execute(text(
        "SELECT COUNT(*) FROM notification_rule "
        "WHERE channels::text LIKE '%socket%'"
    )).scalar()

    action_count = conn.execute(text(
        "SELECT COUNT(*) FROM notification_action "
        "WHERE channel = 'socket'"
    )).scalar()

    template_count = conn.execute(text(
        "SELECT COUNT(*) FROM notification_template "
        "WHERE supported_channels::text LIKE '%socket%'"
    )).scalar()

    print(f"[socket→browser] Pre-check: "
          f"rules={rule_count}, actions={action_count}, templates={template_count}")

    # --- 1. notification_rule.channels: replace "socket" with "browser" in JSON array ---
    # channels column is JSON (not JSONB), jsonb_array_elements_text returns plain text
    if rule_count > 0:
        conn.execute(text("""
            UPDATE notification_rule
            SET channels = (
                SELECT json_agg(
                    CASE WHEN elem = 'socket' THEN 'browser' ELSE elem END
                )
                FROM jsonb_array_elements_text(channels::jsonb) AS elem
            )
            WHERE channels::text LIKE '%socket%'
        """))

    # --- 2. notification_action.channel: simple string replace ---
    if action_count > 0:
        conn.execute(text("""
            UPDATE notification_action
            SET channel = 'browser'
            WHERE channel = 'socket'
        """))

    # --- 3. notification_template.supported_channels: replace in JSONB array ---
    if template_count > 0:
        conn.execute(text("""
            UPDATE notification_template
            SET supported_channels = (
                SELECT jsonb_agg(
                    CASE WHEN elem = 'socket' THEN 'browser' ELSE elem END
                )
                FROM jsonb_array_elements_text(supported_channels) AS elem
            )
            WHERE supported_channels::text LIKE '%socket%'
        """))

    # --- 4. Update column default for supported_channels ---
    op.alter_column(
        'notification_template',
        'supported_channels',
        server_default=text("'[\"browser\"]'::jsonb"),
    )

    # --- Post-check: verify no socket remains ---
    remaining_rules = conn.execute(text(
        "SELECT COUNT(*) FROM notification_rule "
        "WHERE channels::text LIKE '%socket%'"
    )).scalar()

    remaining_actions = conn.execute(text(
        "SELECT COUNT(*) FROM notification_action "
        "WHERE channel = 'socket'"
    )).scalar()

    remaining_templates = conn.execute(text(
        "SELECT COUNT(*) FROM notification_template "
        "WHERE supported_channels::text LIKE '%socket%'"
    )).scalar()

    total_remaining = remaining_rules + remaining_actions + remaining_templates
    print(f"[socket→browser] Post-check: "
          f"rules={remaining_rules}, actions={remaining_actions}, "
          f"templates={remaining_templates}")

    if total_remaining > 0:
        raise RuntimeError(
            f"Migration verification failed: {total_remaining} rows still contain 'socket'"
        )

    print("[socket→browser] Migration complete. 0 rows with 'socket' remaining.")


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: browser → socket in all three tables
    conn.execute(text("""
        UPDATE notification_rule
        SET channels = (
            SELECT json_agg(
                CASE WHEN elem = 'browser' THEN 'socket' ELSE elem END
            )
            FROM jsonb_array_elements_text(channels::jsonb) AS elem
        )
        WHERE channels::text LIKE '%browser%'
    """))

    conn.execute(text("""
        UPDATE notification_action
        SET channel = 'socket'
        WHERE channel = 'browser'
    """))

    conn.execute(text("""
        UPDATE notification_template
        SET supported_channels = (
            SELECT jsonb_agg(
                CASE WHEN elem = 'browser' THEN 'socket' ELSE elem END
            )
            FROM jsonb_array_elements_text(supported_channels) AS elem
        )
        WHERE supported_channels::text LIKE '%browser%'
    """))

    op.alter_column(
        'notification_template',
        'supported_channels',
        server_default=text("'[\"socket\"]'::jsonb"),
    )

    print("[browser→socket] Downgrade complete.")
