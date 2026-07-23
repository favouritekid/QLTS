"""major-change reprice 1D — seed notification rule/template/action cho 2 event.

CLAUDE.md rule 5: "A new event WITHOUT a seeded rule row silently fires zero
notifications". Prod CÓ auto-sync (docker-entrypoint sync_notification_rules) NHƯNG
sync dùng default_resolver + text GENERIC ("Có hoạt động tài chính mới.") — KHÔNG
đọc NOTIFICATION_SEED_DEFAULTS. Migration này seed nội dung ĐÚNG (title/message
tiếng Việt + specific_users) cho 2 event đổi ngành:

* major_change_awaiting_confirmation — báo kế toán+admin (warning, browser+email)
* major_change_confirmed             — báo officer phụ trách (success, browser)

Mold q9_07_e0b: rule (WHERE NOT EXISTS) + template (ON CONFLICT template_code
DO NOTHING) + action per channel (WHERE NOT EXISTS). Idempotent. Nội dung khớp
NOTIFICATION_SEED_DEFAULTS (hardcode ở đây = version-controlled lock-in).

Revision ID: majchg1d_notif_seed_20260723
Revises: majchg1c_casbin_20260723
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "majchg1d_notif_seed_20260723"
down_revision: Union[str, None] = "majchg1c_casbin_20260723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MAJOR_CHANGE_EVENTS = (
    {
        "event": "major_change_awaiting_confirmation",
        "title": "Đổi ngành — chờ kế toán xác nhận",
        "message": (
            "Hồ sơ ${profile_code} đổi ngành ${old_major_name} → "
            "${new_major_name}, học phí đã định giá lại (chênh lệch "
            "${delta_amount}). Cần kế toán xác nhận trước khi phát giấy báo."
        ),
        "ntype": "warning",
        "link": "/finance/fees/${fee_id}",
        "channels": ("browser", "email"),
        "resolver": "specific_users",
        "category": "finance",
    },
    {
        "event": "major_change_confirmed",
        "title": "Đổi ngành — kế toán đã xác nhận",
        "message": (
            "Kế toán đã xác nhận học phí đổi ngành cho hồ sơ ${profile_code} "
            "(ngành ${new_major_name}). Có thể tiếp tục phát giấy báo nhập học."
        ),
        "ntype": "success",
        "link": "/admissions/${admission_profile_id}",
        "channels": ("browser",),
        "resolver": "specific_users",
        "category": "finance",
    },
)


def _template_code(event: str) -> str:
    return f"TPL_{event}"


def upgrade() -> None:
    bind = op.get_bind()

    for entry in MAJOR_CHANGE_EVENTS:
        # 1. notification_rule (event-keyed, WHERE NOT EXISTS).
        bind.execute(
            sa.text(
                """
                INSERT INTO notification_rule (
                    event, title_template, message_template,
                    notification_type, link_template,
                    recipient_config, condition,
                    enabled, template_id,
                    created_at, updated_at
                )
                SELECT
                    CAST(:event AS varchar), CAST(:title AS varchar), CAST(:message AS text),
                    CAST(:ntype AS varchar), CAST(:link AS varchar),
                    CAST(:recipient AS json), NULL,
                    true, NULL,
                    now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM notification_rule WHERE event = CAST(:event AS varchar)
                )
                """
            ),
            {
                "event": entry["event"],
                "title": entry["title"],
                "message": entry["message"],
                "ntype": entry["ntype"],
                "link": entry["link"],
                "recipient": (
                    f'{{"resolver_type": "{entry["resolver"]}", "params": {{}}}}'
                ),
            },
        )

        # 2. notification_template (UNIQUE template_code → ON CONFLICT DO NOTHING).
        template_code = _template_code(entry["event"])
        channels_json = "[" + ", ".join(f'"{c}"' for c in entry["channels"]) + "]"
        events_json = f'["{entry["event"]}"]'
        bind.execute(
            sa.text(
                """
                INSERT INTO notification_template (
                    name, template_code, description,
                    title_template, message_template, link_template,
                    variables, category,
                    supported_channels, allowed_events, template_type,
                    is_system, usage_count, created_by,
                    created_at, updated_at
                )
                VALUES (
                    CAST(:name AS varchar), CAST(:code AS varchar), CAST(:description AS text),
                    CAST(:title AS varchar), CAST(:message AS text), CAST(:link AS varchar),
                    NULL, CAST(:category AS varchar),
                    CAST(:channels AS jsonb), CAST(:events AS jsonb), 'system',
                    true, 0, NULL,
                    now(), now()
                )
                ON CONFLICT (template_code) DO NOTHING
                """
            ),
            {
                "name": f"Đổi ngành — {entry['title']}",
                "code": template_code,
                "description": (
                    f"System template for {entry['event']} (major-change "
                    f"reprice). Seeded by majchg1d."
                ),
                "title": entry["title"],
                "message": entry["message"],
                "link": entry["link"],
                "category": entry["category"],
                "channels": channels_json,
                "events": events_json,
            },
        )

        # 3. notification_action — 1 per channel (WHERE NOT EXISTS on rule+step).
        for step, channel in enumerate(entry["channels"], start=1):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO notification_action (
                        rule_id, step, channel, template_code,
                        delay_minutes, config,
                        recipient_config, content_mode, content_override,
                        branch_key,
                        created_at, updated_at
                    )
                    SELECT
                        r.id, :step, CAST(:channel AS varchar), CAST(:template_code AS varchar),
                        0, NULL,
                        NULL, 'inherit_default', NULL,
                        NULL,
                        now(), now()
                    FROM notification_rule r
                    WHERE r.event = CAST(:event AS varchar)
                      AND NOT EXISTS (
                          SELECT 1 FROM notification_action a
                          WHERE a.rule_id = r.id AND a.step = :step
                      )
                    """
                ),
                {
                    "event": entry["event"],
                    "step": step,
                    "channel": channel,
                    "template_code": template_code,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()

    event_values = [e["event"] for e in MAJOR_CHANGE_EVENTS]
    template_codes = [_template_code(e["event"]) for e in MAJOR_CHANGE_EVENTS]

    bind.execute(
        sa.text(
            """
            DELETE FROM notification_action
            WHERE rule_id IN (
                SELECT id FROM notification_rule WHERE event = ANY(:events)
            )
            """
        ),
        {"events": event_values},
    )
    bind.execute(
        sa.text("DELETE FROM notification_rule WHERE event = ANY(:events)"),
        {"events": event_values},
    )
    bind.execute(
        sa.text(
            "DELETE FROM notification_template WHERE template_code = ANY(:codes)"
        ),
        {"codes": template_codes},
    )
