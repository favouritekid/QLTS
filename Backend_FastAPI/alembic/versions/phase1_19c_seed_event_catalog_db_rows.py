"""phase1_19c: seed 12 ADMISSION_* event_catalog DB rows (rule + action + template)

Revision ID: phase1_19c
Revises: phase1_10
Create Date: 2026-05-05

#184 Wave 5-A — version-controlled seed lock-in for the 12
ADMISSION_* milestone events. Closes the template-gap risk during
cold cutover where ``RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false``
skips ``sync_notification_rules.py`` and
``seed_notification_template_library.py --apply`` is forgotten:
without the seed, ``notification_dispatcher.py`` silent-fails on
template lookup → 12 events fire 0 notifications.

Renamed from spec ``phase1_19b`` per Q2 cascade chốt 2026-05-03
(slot 19b chiếm bởi B1 casbin migration ship via PR #201).

PLAN refs
---------
* §3.3.d (line 1644-1657) — 12 milestone events table (event /
  audience / outbox / bypass_consent / payload).
* §4 P1 fix #3 (line 107) — migration phase1_19 seeds notification_
  rule + notification_template tables (CHỈ DB rows, KHÔNG đụng
  Python module dict — that ships in B2 code).
* §4 line 3807 — ownership: phase1_19c is sole owner of the 12
  ADMISSION_* row set in DB (post-cascade rename).
* CLAUDE.md backend rule 5 — "Four primitives: SystemEvents enum +
  EventDefinition catalog + notification_rule DB table row +
  dispatch(). A new event WITHOUT a seeded rule row silently fires
  zero notifications".

Scope (b2 chốt 2026-05-05 sau Codex round 18 audit)
---------------------------------------------------
Idempotent INSERT into 3 tables for each of the 12 events:

* ``notification_rule`` — 1 row per event (event-keyed; no UNIQUE
  constraint on the column so we use ``WHERE NOT EXISTS`` guard).
* ``notification_action`` — 1 row per (rule, channel) pair; step
  enumerated ``1..N`` per event's default_channels. UNIQUE
  ``(rule_id, step)`` exists so the same guard pattern applies.
* ``notification_template`` — 1 row per event (template_code is
  UNIQUE so ``ON CONFLICT (template_code) DO NOTHING`` works).

Hardcoded MILESTONE_EVENTS tuple intentionally — version-controlled
lock-in. Future ``app/core/event_catalog.py`` changes do NOT
retroactively change what this migration seeds when re-applied
on a different DB. Drift between migration seed and live catalog
is detected by ``app/scripts/check_notification_event_coverage.py``
script (memory ``event-coverage-script``).

Idempotency
-----------
Each INSERT uses ``WHERE NOT EXISTS`` (rule, action) or ``ON
CONFLICT (template_code) DO NOTHING`` (template). Re-applying
upgrade after a partial-run leaves existing rows alone.

Down-revision chain: ``phase1_10 → phase1_19c``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "phase1_19c"
down_revision: Union[str, None] = "phase1_10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 12 milestone events — frozen here as the migration is the version-
# controlled source-of-truth. Each entry's title/message/link reflect
# PLAN §3.3.d table line 1644-1657 contract. Channels follow each
# event's ``default_channels`` from ``app/core/event_catalog.py``
# at this commit time.
MILESTONE_EVENTS: tuple[dict, ...] = (
    {
        "event": "ADMISSION_PROFILE_SUBMITTED",
        "title": "Hồ sơ tuyển sinh đã nộp",
        "message": "Hồ sơ tuyển sinh #$application_id đã được nộp lúc $submitted_at_iso.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 80,
    },
    {
        "event": "ADMISSION_REVISION_REQUESTED",
        "title": "Yêu cầu bổ sung hồ sơ",
        "message": "Hồ sơ #$application_id cần bổ sung. Lý do: $revision_reason.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "specific_users",
        "category": "application",
        "priority": 70,
    },
    {
        "event": "ADMISSION_RESUBMITTED",
        "title": "Hồ sơ đã được nộp lại",
        "message": "Hồ sơ #$application_id đã được nộp lại sau khi chỉnh sửa.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 60,
    },
    {
        "event": "ADMISSION_RESULT_PUBLISHED",
        "title": "Kết quả tuyển sinh đã công bố",
        "message": "Kết quả tuyển sinh đã được công bố lúc $published_at_iso. $decision_summary",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 90,
    },
    {
        "event": "ADMISSION_DECISION_ADMITTED",
        "title": "Chúc mừng — bạn đã trúng tuyển",
        "message": "Hồ sơ #$application_id trúng tuyển NV$choice_priority. Tổng điểm: $total_score.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 90,
    },
    {
        "event": "ADMISSION_DECISION_WAITLISTED",
        "title": "Hồ sơ vào danh sách chờ",
        "message": "Hồ sơ #$application_id vào danh sách chờ — vị trí $waitlist_rank.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 70,
    },
    {
        "event": "ADMISSION_DECISION_REJECTED",
        "title": "Kết quả tuyển sinh — không trúng tuyển",
        "message": "Hồ sơ #$application_id không trúng tuyển trong đợt này.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 70,
    },
    {
        "event": "ADMISSION_WAITLIST_PROMOTED",
        "title": "Bạn đã được gọi từ danh sách chờ",
        "message": "Hồ sơ #$application_id đã được gọi nhập học từ danh sách chờ lúc $promoted_at_iso.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email", "zalo"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 80,
    },
    {
        "event": "ADMISSION_CONFIRMED",
        "title": "Đã xác nhận nhập học",
        "message": "Hồ sơ #$application_id đã được xác nhận nhập học qua $confirmed_via.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 50,
    },
    {
        "event": "ADMISSION_ENROLLED",
        "title": "Đã hoàn tất nhập học",
        "message": "Hồ sơ #$application_id đã hoàn tất nhập học. Mã sinh viên: $student_id.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 20,
    },
    {
        "event": "ADMISSION_WITHDRAWN",
        "title": "Hồ sơ đã được rút",
        "message": "Hồ sơ #$application_id đã được rút từ trạng thái $from_status. Lý do: $reason.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 70,
    },
    {
        "event": "ADMISSION_ROLLED_BACK",
        "title": "Hồ sơ đã được khôi phục về nháp (admin)",
        "message": "Admin đã khôi phục hồ sơ #$application_id từ $from_status về nháp. Lý do: $override_reason.",
        "link": "/admissions/$application_id",
        "channels": ("browser", "email"),
        "resolver": "lead_owner",
        "category": "application",
        "priority": 60,
    },
)


def _template_code(event: str) -> str:
    """Build deterministic template_code from event name. UNIQUE
    constraint enforces no duplicates."""
    return f"TPL_{event}"


def upgrade() -> None:
    bind = op.get_bind()

    for entry in MILESTONE_EVENTS:
        # 1. INSERT NotificationRule (event-keyed; WHERE NOT EXISTS
        #    guard since notification_rule.event has no UNIQUE).
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

        # 2. INSERT NotificationTemplate — UNIQUE template_code enforced
        #    so ON CONFLICT (template_code) DO NOTHING is the canonical
        #    idempotent shape.
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
                "name": f"Admission — {entry['title']}",
                "code": template_code,
                "description": (
                    f"System template for {entry['event']} milestone "
                    f"event (PLAN §3.3.d). Seeded by phase1_19c."
                ),
                "title": entry["title"],
                "message": entry["message"],
                "link": entry["link"],
                "category": entry["category"],
                "channels": channels_json,
                "events": events_json,
            },
        )

        # 3. INSERT NotificationAction rows — one per channel, step 1..N.
        #    Linked via the rule we just inserted (or pre-existing).
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

    # Inverse — actions cascade-delete via FK ON DELETE CASCADE,
    # but explicit DELETE keeps the audit trail clear in alembic logs.
    # Order: actions → rules → templates (templates can stand alone
    # if any other migration's rule references them via template_code).
    event_values = tuple(e["event"] for e in MILESTONE_EVENTS)
    template_codes = tuple(_template_code(e["event"]) for e in MILESTONE_EVENTS)

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
        sa.text(
            "DELETE FROM notification_rule WHERE event = ANY(:events)"
        ),
        {"events": list(event_values)},
    )

    bind.execute(
        sa.text(
            "DELETE FROM notification_template WHERE template_code = ANY(:codes)"
        ),
        {"codes": list(template_codes)},
    )
