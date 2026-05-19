"""q9_07_e0b: seed 3 PRIORITY_* event_catalog DB rows (rule + template + action)

Revision ID: q9_07_e0b
Revises: q9_07_e0a
Create Date: 2026-05-19

Q9 #07 Phase E Foundation pre-work — version-controlled seed lock-in
for 3 PRIORITY_* events introduced trong Phase E.2 + E.3:

* PRIORITY_KV_OVERRIDDEN  — officer/admin manually overrides KV
* PRIORITY_OBJECT_VERIFIED — officer verifies UT evidence
* PRIORITY_OBJECT_REJECTED — officer rejects UT evidence (candidate re-supply)

Critical per CLAUDE.md backend rule 5 + memory `notification-event-gate-required-locally`:
"A new event WITHOUT a seeded rule row silently fires zero notifications".

Pattern mirror `phase1_19c_seed_event_catalog_db_rows.py`:
* notification_rule — 1 row per event (WHERE NOT EXISTS guard)
* notification_template — 1 row per event (ON CONFLICT template_code DO NOTHING)
* notification_action — 1 row per (rule, channel) pair (WHERE NOT EXISTS guard)

Hardcoded PRIORITY_EVENTS tuple intentionally — version-controlled lock-in.
Future ``app/core/event_catalog.py`` changes do NOT retroactively change
what this migration seeds when re-applied on a different DB. Drift
detected by ``app/scripts/check_notification_event_coverage.py``.

Idempotency: WHERE NOT EXISTS / ON CONFLICT guards. Re-apply leaves
existing rows alone.

Down-revision chain: ``q9_07_e0a → q9_07_e0b``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "q9_07_e0b"
down_revision: Union[str, None] = "q9_07_e0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 3 events × (title + message + link + channels + resolver + category + priority)
# Mirror phase1_19c MILESTONE_EVENTS exact format.
PRIORITY_EVENTS = (
    {
        "event": "priority_kv_overridden",
        "title": "Khu vực ưu tiên đã được cập nhật thủ công",
        "message": (
            "Hồ sơ #$application_id: cán bộ $actor_name đã ấn định KV thành "
            "$kv_resolved. Lý do: $override_reason."
        ),
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 70,
    },
    {
        "event": "priority_object_verified",
        "title": "Đối tượng ưu tiên đã được xác minh",
        "message": (
            "Hồ sơ #$application_id: minh chứng đối tượng ưu tiên $sub_code "
            "đã được xác minh bởi $actor_name."
        ),
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 60,
    },
    {
        "event": "priority_object_rejected",
        "title": "Minh chứng đối tượng ưu tiên bị từ chối",
        "message": (
            "Hồ sơ #$application_id: minh chứng đối tượng ưu tiên $sub_code "
            "bị từ chối. Lý do: $reject_reason. Vui lòng bổ sung minh chứng đầy đủ."
        ),
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 75,
    },
)


def _template_code(event: str) -> str:
    """Build deterministic template_code from event name. UNIQUE
    constraint enforces no duplicates."""
    return f"TPL_{event}"


def upgrade() -> None:
    bind = op.get_bind()

    for entry in PRIORITY_EVENTS:
        # 1. INSERT NotificationRule — event-keyed, WHERE NOT EXISTS guard.
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
                    'info', CAST(:link AS varchar),
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
                "link": entry["link"],
                "recipient": (
                    f'{{"resolver_type": "{entry["resolver"]}", "params": {{}}}}'
                ),
            },
        )

        # 2. INSERT NotificationTemplate — UNIQUE template_code → ON CONFLICT DO NOTHING.
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
                "name": f"Priority — {entry['title']}",
                "code": template_code,
                "description": (
                    f"System template for {entry['event']} priority bonus event "
                    f"(Q9 #07 Phase E). Seeded by q9_07_e0b."
                ),
                "title": entry["title"],
                "message": entry["message"],
                "link": entry["link"],
                "category": entry["category"],
                "channels": channels_json,
                "events": events_json,
            },
        )

        # 3. INSERT NotificationAction — one per channel, step 1..N.
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

    event_values = tuple(e["event"] for e in PRIORITY_EVENTS)
    template_codes = tuple(_template_code(e["event"]) for e in PRIORITY_EVENTS)

    bind.execute(
        sa.text(
            """
            DELETE FROM notification_action
            WHERE rule_id IN (
                SELECT id FROM notification_rule WHERE event = ANY(:events)
            )
            """
        ),
        {"events": list(event_values)},
    )

    bind.execute(
        sa.text("DELETE FROM notification_rule WHERE event = ANY(:events)"),
        {"events": list(event_values)},
    )

    bind.execute(
        sa.text(
            "DELETE FROM notification_template WHERE template_code = ANY(:codes)"
        ),
        {"codes": list(template_codes)},
    )
