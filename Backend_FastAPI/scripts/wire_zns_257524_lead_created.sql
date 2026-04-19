-- ============================================================================
-- Wire ZNS template 257524 (Xác nhận thông tin tư vấn) into lead_created pipeline
-- ============================================================================
--
-- Target rule: notification_rule.event = 'lead_created'
--   Current on prod: rule_id = 5, one action (step=1, channel=browser).
--   This script upserts a NEW action row (step=2, channel=zalo) — uses
--   ON CONFLICT (rule_id, step) DO UPDATE so rerunning is idempotent and
--   safely merges config without wiping other keys.
--
-- Merge strategy for existing row (if any):
--   config = (COALESCE(notification_action.config::jsonb, '{}'::jsonb) || EXCLUDED.config::jsonb)::json
--   - Column is declared Column(JSON, ...) in app/models/notification.py:300
--     which maps to Postgres `json` (not jsonb). JSON does not support ||,
--     so we cast to jsonb for the merge then back to json on assignment.
--   - Preserves any pre-existing keys (external_resolver, other channel-native keys).
--   - Overwrites only the 3 keys we own.
--
-- Resolver choice:
--   external_resolver = 'lead_contact' — the ZNS is delivered to the lead's
--   Zalo-linked phone (external), NOT to unit_managers (which is the internal
--   default at event_catalog.py:260). Action-level external_resolver overrides
--   rule-level recipient_config for this action only (dispatcher.py:580-613).
--
-- Template param mapping (see Documents/ZNS_PHASE_AB_PLAN_2026-04-19.md):
--   customer_name  ← $lead_name
--   ma_hoc_vien    ← $lead_code        (LEAD-{id:06d})
--   ten_nganh_hoc  ← $major_name       (lead.offering.program.name[:30] or 'N/A')
--   ngay_dang_ky   ← $created_date_vn  (DD/MM/YYYY from lead.created_at)
--
-- Deploy order: run THIS script BEFORE restarting backend/celery-worker.
-- Ensures any LEAD_CREATED dispatch post-restart already has the new config.
--
-- Rollback:
--   DELETE FROM notification_action
--   WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'lead_created')
--     AND step = 2 AND channel = 'zalo';
-- ============================================================================

BEGIN;

INSERT INTO notification_action (rule_id, step, channel, content_mode, config, delay_minutes)
SELECT
    r.id,
    2,
    'zalo',
    'channel_native',
    jsonb_build_object(
        'external_resolver', 'lead_contact',
        'zalo_template_id', 257524,
        'zalo_template_data', jsonb_build_object(
            'customer_name', '$lead_name',
            'ma_hoc_vien',   '$lead_code',
            'ten_nganh_hoc', '$major_name',
            'ngay_dang_ky',  '$created_date_vn'
        )
    )::json,
    0
FROM notification_rule r
WHERE r.event = 'lead_created'
ON CONFLICT (rule_id, step) DO UPDATE
SET
    channel = EXCLUDED.channel,
    content_mode = EXCLUDED.content_mode,
    config = (COALESCE(notification_action.config::jsonb, '{}'::jsonb) || EXCLUDED.config::jsonb)::json;

-- Verification
SELECT id, rule_id, step, channel, content_mode, jsonb_pretty(config::jsonb) AS config
FROM notification_action
WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'lead_created')
ORDER BY step;

COMMIT;
