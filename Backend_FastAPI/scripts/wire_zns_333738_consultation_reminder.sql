-- ============================================================================
-- Wire ZNS template 333738 (Nhắc lịch hẹn) into consultation_reminder pipeline
-- ============================================================================
--
-- Target row: notification_action.id = 63
--   rule_id       = 11  (event = consultation_reminder)
--   step          = 2
--   channel       = zalo
--   content_mode  = channel_native
--
-- Merge strategy: (COALESCE(config::jsonb, '{}'::jsonb) || jsonb_build_object(...))::json
--   - Column is declared Column(JSON, ...) in app/models/notification.py:300
--     which maps to Postgres `json` (not jsonb). JSON does not support ||,
--     so we cast to jsonb for the merge then back to json on assignment.
--   - Handles NULL config safely (column is nullable).
--   - Preserves any pre-existing keys (e.g. a prior external_resolver or
--     other channel-native keys that dispatcher reads at
--     app/services/notification_dispatcher.py:822).
--   - Overwrites only the 3 keys we own: external_resolver,
--     zalo_template_id, zalo_template_data.
--
-- Resolver choice:
--   external_resolver = 'lead_contact' — reminder is delivered to the lead
--   (external recipient) via their phone, not to the officer. The action-level
--   external_resolver overrides rule-level recipient_config for this action
--   (verified at notification_dispatcher.py:580-613).
--
-- Template param mapping (see Documents/ZNS_PHASE_AB_PLAN_2026-04-19.md):
--   schedule_time  ← $scheduled_time_vn  (DD/MM/YYYY HH:MM, ≤16 chars)
--   customer_name  ← $lead_name           (≤30 chars; cap in builder if needed)
--   address        ← literal SCHOOL_ADDRESS (Phase A default)
--   booking_code   ← $booking_code        (CONS-{id:06d})
--   ten_nganh_hoc  ← $major_name          (≤30 chars, cap in builder)
--   ma_hoc_vien    ← $lead_code           (LEAD-{id:06d})
--
-- Deploy order: run THIS script BEFORE restarting celery-beat/celery-worker.
-- Beat cadence is 60s (celery_app.py:108); applying SQL first prevents a
-- tick with mismatched code vs config.
--
-- Rollback:
--   UPDATE notification_action
--   SET config = config - 'external_resolver' - 'zalo_template_id' - 'zalo_template_data'
--   WHERE id = 63;
-- ============================================================================

BEGIN;

UPDATE notification_action
SET config = (COALESCE(config::jsonb, '{}'::jsonb) || jsonb_build_object(
    'external_resolver', 'lead_contact',
    'zalo_template_id', 333738,
    'zalo_template_data', jsonb_build_object(
        'schedule_time', '$scheduled_time_vn',
        'customer_name', '$lead_name',
        'address',       '02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk',
        'booking_code',  '$booking_code',
        'ten_nganh_hoc', '$major_name',
        'ma_hoc_vien',   '$lead_code'
    )
))::json
WHERE id = 63;

-- Verification: dump the merged config so the deployer can eyeball it.
SELECT id, rule_id, step, channel, content_mode, jsonb_pretty(config::jsonb) AS config
FROM notification_action
WHERE id = 63;

COMMIT;
