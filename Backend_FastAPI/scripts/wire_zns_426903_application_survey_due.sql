-- ============================================================================
-- Wire ZNS template 426903 (Khảo sát dịch vụ tư vấn) into application_survey_due
-- ============================================================================
--
-- Target rule: notification_rule.event = 'application_survey_due'
--   Rule row is auto-created by sync_notification_rules (event has
--   notification_class=user, default_channels=('zalo',)) — this script only
--   inserts the action row mapping to template 426903.
--
-- Deploy order:
--   1. Run `python -m app.scripts.sync_notification_rules` to create the rule row
--   2. Run this script to insert the zalo action
--   3. Restart celery-beat (picks up new beat schedule from code)
--
-- Resolver choice:
--   external_resolver = 'lead_contact' — survey goes to the applicant via
--   Zalo-linked phone, not internal staff. Override at action level because
--   the APPLICATION_SURVEY_DUE catalog entry has default_resolver='specific_users'
--   (the internal default) and the action-level external_resolver supersedes
--   for this action only (dispatcher.py:580-613).
--
-- Template param mapping (see Documents/ZNS_PHASE_AB_PLAN_2026-04-19.md Phase E
-- and 2026-04-20 template preview on business.zalo.solutions):
--   ten_nguoi_hoc   ← $full_name         (profile.full_name, ≤30 chars)
--   ma_nganh        ← $program_name      (offering.program.name, ≤30 chars)
--   ma_ho_so        ← $profile_code      (profile.profile_code, ≤30 chars)
--   ngay_nop_ho_so  ← $submitted_date_vn (DD/MM/YYYY of profile.submitted_at)
--
-- Tracking ID contract:
--   Scheduler generates UUID per profile and passes it as Zalo `tracking_id`.
--   Zalo echoes it back verbatim in the `user_feedback` webhook so we can
--   map feedback → profile. Channel payload builder reads $tracking_id from
--   the dispatched event payload; it is not a template slot.
--
-- Rollback:
--   DELETE FROM notification_action
--   WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'application_survey_due')
--     AND step = 1 AND channel = 'zalo';
-- ============================================================================

BEGIN;

INSERT INTO notification_action (rule_id, step, channel, content_mode, config, delay_minutes)
SELECT
    r.id,
    1,
    'zalo',
    'channel_native',
    jsonb_build_object(
        'external_resolver', 'lead_contact',
        'zalo_template_id', 426903,
        'zalo_template_data', jsonb_build_object(
            'ten_nguoi_hoc',  '$full_name',
            'ma_nganh',       '$program_name',
            'ma_ho_so',       '$profile_code',
            'ngay_nop_ho_so', '$submitted_date_vn'
        )
    )::json,
    0
FROM notification_rule r
WHERE r.event = 'application_survey_due'
ON CONFLICT (rule_id, step) DO UPDATE
SET
    channel = EXCLUDED.channel,
    content_mode = EXCLUDED.content_mode,
    config = (COALESCE(notification_action.config::jsonb, '{}'::jsonb) || EXCLUDED.config::jsonb)::json;

-- Verification
SELECT id, rule_id, step, channel, content_mode, jsonb_pretty(config::jsonb) AS config
FROM notification_action
WHERE rule_id = (SELECT id FROM notification_rule WHERE event = 'application_survey_due')
ORDER BY step;

COMMIT;
