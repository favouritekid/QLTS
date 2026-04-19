-- ============================================================================
-- Wire ZNS template 557767 (Thông báo thu học phí) into invoice_issued pipeline
-- ============================================================================
--
-- Target rule: notification_rule.event = 'invoice_issued'
--   On prod: rule_id present with existing browser+email action(s).
--   This script upserts a NEW action row (step=2, channel=zalo) for the rule.
--
-- Merge strategy for existing row (if any):
--   config = (COALESCE(notification_action.config::jsonb, '{}'::jsonb)
--             || EXCLUDED.config::jsonb)::json
--   Preserves any pre-existing keys (external_resolver, other channel-native
--   keys); overwrites only the 3 keys we own.
--
-- Resolver choice:
--   external_resolver = 'lead_contact' — ZNS delivers to the lead's Zalo-linked
--   phone (external), NOT the officer. INVOICE_ISSUED catalog default resolver
--   is 'specific_users' (internal officer); the action-level external_resolver
--   overrides for this action only (dispatcher.py:580-613).
--
-- Template param mapping (see Documents/ZNS_PHASE_AB_PLAN_2026-04-19.md Phase D):
--   ma_ho_so              ← $profile_code          (HS-{admission_profile_id:06d})
--   ten_nganh             ← $major_name            (lead.offering.program.name[:30])
--   trinh_do              ← $degree_level          (program.degree_level[:30])
--   ho_va_ten             ← $lead_full_name        (lead.full_name[:30])
--   so_tien               ← $amount_vnd            (int(Decimal(amount)))
--   ngay                  ← $due_date_vn           (DD/MM/YYYY)
--   thon_tin_chuyen_khoan ← $bank_transfer_note    (ASCII alphanumeric+space ≤90)
--
-- Guard: dispatcher call site in invoice_service.py keeps the existing
--   `if not _invoice_payload.get("user_id"): return` gate so invoices on
--   unassigned leads do not fire ZNS (business rule: only assigned leads get
--   tuition notifications).
--
-- Deploy order: run this script BEFORE restarting backend/celery-worker.
--
-- Rollback:
--   DELETE FROM notification_action
--   WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'invoice_issued')
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
        'zalo_template_id', 557767,
        'zalo_template_data', jsonb_build_object(
            'ma_ho_so',              '$profile_code',
            'ten_nganh',             '$major_name',
            'trinh_do',              '$degree_level',
            'ho_va_ten',             '$lead_full_name',
            'so_tien',               '$amount_vnd',
            'ngay',                  '$due_date_vn',
            'thon_tin_chuyen_khoan', '$bank_transfer_note'
        )
    )::json,
    0
FROM notification_rule r
WHERE r.event = 'invoice_issued'
ON CONFLICT (rule_id, step) DO UPDATE
SET
    channel = EXCLUDED.channel,
    content_mode = EXCLUDED.content_mode,
    config = (COALESCE(notification_action.config::jsonb, '{}'::jsonb) || EXCLUDED.config::jsonb)::json;

-- Verification
SELECT id, rule_id, step, channel, content_mode, jsonb_pretty(config::jsonb) AS config
FROM notification_action
WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'invoice_issued')
ORDER BY step;

COMMIT;
