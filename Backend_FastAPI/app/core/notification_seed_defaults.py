"""
Per-event seed defaults for notification_rule bootstrapping.

Carries the fields that `EventDefinition` does not own:
 - `title_template`, `message_template` (notification content)
 - `notification_type` (severity enum value as string)
 - `recipient_config` (serialized resolver tree, preserving composite /
   actor-excluded shapes — catalog's `default_resolver` is a single
   string name and cannot round-trip those shapes)

The dict was extracted from `NOTIFICATION_REGISTRY` at Wave 1 Step 0
cutover (2026-04-21) to guarantee byte-identical seed output after the
seeder stops importing the legacy registry module.

Channel list + link template are NOT duplicated here: they come from
`app.core.event_catalog.EVENT_CATALOG[event].default_channels /
link_strategy`, which was reconciled with registry values in Step 0.

`LEGACY_REGISTRY_EVENTS` is the frozen set of event names that were
seeded by the pre-Wave-1 registry; `reset_notification_rules_dev.py`
uses it to reproduce the "registry_events" term in its target-events
union after the registry import is removed.
"""

from __future__ import annotations

from typing import Any, Dict

from app.core.events import SystemEvents


NOTIFICATION_SEED_DEFAULTS: Dict[SystemEvents, Dict[str, Any]] = {
    SystemEvents.APPLICATION_CREATED: {
        "title_template": "New Application Created",
        "message_template": "Application #${application_id} created for Lead #${lead_id} - ${major_program_name}.",
        "notification_type": "success",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "lead_owner", "params": {}},
                        {"resolver_type": "all_admins", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.APPLICATION_DELETED: {
        "title_template": "Application Deleted",
        "message_template": "Application #${application_id} for ${lead_name} has been deleted.",
        "notification_type": "warning",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "specific_users", "params": {}},
                        {"resolver_type": "all_admins", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.APPLICATION_STATUS_CHANGED: {
        "title_template": "Application Status Changed",
        "message_template": "Application #${application_id} status changed from ${old_status} to ${new_status}.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "lead_owner", "params": {}},
                        {"resolver_type": "all_admins", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.ASSET_CHECKED_OUT: {
        "title_template": "Asset Checked Out",
        "message_template": "Asset '${asset_name}' has been checked out. Expected return: ${expected_return}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "all_admins", "params": {}},
    },
    SystemEvents.ASSET_MAINTENANCE_ALERT: {
        "title_template": "Asset Maintenance Alert",
        "message_template": "Asset '${asset_name}' requires ${maintenance_type} maintenance by ${due_date}.",
        "notification_type": "warning",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "unit_staff", "params": {}}},
        },
    },
    SystemEvents.CONSULTATION_CREATED: {
        "title_template": "New Consultation Added",
        "message_template": "A consultation has been added to Lead #${lead_id}.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "lead_owner", "params": {}},
                        {"resolver_type": "unit_managers", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.CONSULTATION_DELETED: {
        "title_template": "Consultation Deleted",
        "message_template": "Consultation #${consultation_id} for Lead #${lead_id} has been deleted.",
        "notification_type": "warning",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "lead_owner", "params": {}}},
        },
    },
    # NOTE: seed default stays browser-only. Prod enriches this rule
    # with a Zalo action (zalo_template_id=333738, external resolver)
    # via admin UI — that per-action config is not representable in
    # this dict today. See inline comment at
    # event_catalog.py::CONSULTATION_REMINDER.
    SystemEvents.CONSULTATION_REMINDER: {
        "title_template": "⏰ Nhắc nhở: Lịch hẹn tư vấn",
        "message_template": "Bạn có lịch hẹn gọi ${lead_name} (${lead_phone}) trong ${minutes_until} phút nữa.",
        "notification_type": "reminder",
        "recipient_config": {"resolver_type": "lead_owner", "params": {}},
    },
    SystemEvents.CONSULTATION_UPDATED: {
        "title_template": "Consultation Updated",
        "message_template": "Consultation #${consultation_id} for Lead #${lead_id} has been updated.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "lead_owner", "params": {}}},
        },
    },
    SystemEvents.CTV_APPROVED: {
        "title_template": "Tài khoản CTV đã được duyệt",
        "message_template": "Tài khoản CTV của bạn đã được duyệt. Bạn có thể bắt đầu giới thiệu lead.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_ATTRIBUTION_EXPIRED: {
        "title_template": "Quyền giới thiệu hết hạn",
        "message_template": "Quyền giới thiệu cho lead #${lead_id} đã hết hạn sau 90 ngày.",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_ATTRIBUTION_EXPIRING: {
        "title_template": "Quyền giới thiệu sắp hết hạn",
        "message_template": "Quyền giới thiệu cho lead #${lead_id} sẽ hết hạn trong ${days_remaining} ngày.",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_CLAIM_APPROVED: {
        "title_template": "Claim được duyệt",
        "message_template": "Claim #${claim_id} của bạn đã được duyệt. Lead đã được ghi nhận.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_CLAIM_REJECTED: {
        "title_template": "Claim bị từ chối",
        "message_template": "Claim #${claim_id} đã bị từ chối. Lý do: ${rejection_reason}",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_CLAIM_SUBMITTED: {
        "title_template": "CTV gửi claim mới",
        "message_template": "${collaborator_name} đã gửi claim cho lead ${lead_name}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "unit_managers", "params": {}},
    },
    SystemEvents.CTV_COMMISSION_CREATED: {
        "title_template": "Hoa hồng mới",
        "message_template": "Bạn nhận được hoa hồng ${amount} VND cho lead #${lead_id}.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_LEAD_CONVERTED: {
        "title_template": "Lead tiến triển",
        "message_template": "Lead #${lead_id} đã chuyển sang trạng thái ${new_status}.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_SUSPENDED: {
        "title_template": "Tài khoản CTV bị đình chỉ",
        "message_template": "Tài khoản CTV của bạn đã bị đình chỉ. Liên hệ quản lý để biết thêm chi tiết.",
        "notification_type": "error",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.CTV_WEEKLY_SUMMARY: {
        "title_template": "Báo cáo tuần CTV",
        "message_template": "Tuần này: ${new_leads} lead mới, ${commissions} hoa hồng.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "collaborator_user", "params": {}},
    },
    SystemEvents.DORM_FEE_CREATED: {
        "title_template": "Dorm Fee Notification",
        "message_template": "A new dorm fee of ${amount} has been created. Due date: ${due_date}.",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "dorm_residents", "params": {}},
    },
    SystemEvents.DORM_MAINTENANCE_REQUEST: {
        "title_template": "Maintenance Request [${priority}]",
        "message_template": "New maintenance request for Dorm ${dorm_id}: ${description}",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "dorm_staff", "params": {}},
    },
    SystemEvents.DORM_ROOM_ASSIGNED: {
        "title_template": "Room Assignment",
        "message_template": "You have been assigned to Room ${room_id} in Dorm ${dorm_id}.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.FEE_FULLY_PAID: {
        "title_template": "Học phí thanh toán đủ",
        "message_template": "Học phí kỳ ${semester_no} với số tiền ${amount} đã được thanh toán đầy đủ.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE: {
        "title_template": "Lịch lễ năm ${year} chưa đầy đủ",
        "message_template": "${message}",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "all_admins", "params": {}},
    },
    SystemEvents.INVOICE_ISSUED: {
        "title_template": "Hóa đơn được phát hành",
        "message_template": "Hóa đơn ${invoice_number} với số tiền ${amount} đã được phát hành. Hạn: ${due_date}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.LEAD_ASSIGNED: {
        "title_template": "New Lead Assigned",
        "message_template": "Lead #${lead_id} (${lead_name}) has been assigned to you.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "lead_owner", "params": {}},
    },
    SystemEvents.LEAD_ASSIGNMENT_FAILED: {
        "title_template": "Lead Assignment Failed",
        "message_template": "Lead #${lead_id} (${lead_name}) could not be assigned automatically. Reason: ${reason}. Please assign manually or adjust officer capacity.",
        "notification_type": "error",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
        },
    },
    SystemEvents.LEAD_CREATED: {
        "title_template": "New Lead Created",
        "message_template": "A new lead (${lead_name}) has been created from ${source}.",
        "notification_type": "success",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
        },
    },
    SystemEvents.LEAD_DELETED: {
        "title_template": "Lead Deleted",
        "message_template": "Lead #${lead_id} (${lead_name}) has been deleted.",
        "notification_type": "warning",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "specific_users", "params": {}},
                        {"resolver_type": "unit_managers", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.LEAD_IMPORTED: {
        "title_template": "Leads Imported",
        "message_template": "${total_imported} leads imported from ${filename} by ${actor_name}.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
        },
    },
    SystemEvents.LEAD_REASSIGNED: {
        "title_template": "Lead Transferred",
        "message_template": "Lead #${lead_id} has been transferred from Unit #${old_unit_id} to Unit #${new_unit_id}. Reason: ${reason}",
        "notification_type": "warning",
        "recipient_config": {
            "resolver_type": "composite",
            "params": {"resolvers": [
                {"resolver_type": "specific_users", "params": {}},
                {
                    "resolver_type": "actor_excluded",
                    "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
                },
            ]},
        },
    },
    SystemEvents.LEAD_RESTORED: {
        "title_template": "Lead Restored",
        "message_template": "Lead #${lead_id} (${lead_name}) has been restored.",
        "notification_type": "success",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "lead_owner", "params": {}},
                        {"resolver_type": "unit_managers", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.LEAD_STATUS_CHANGED: {
        "title_template": "Lead Status Updated",
        "message_template": "Lead #${lead_id} status changed from ${old_status} to ${new_status}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "lead_owner", "params": {}},
    },
    SystemEvents.LEAD_UPDATED: {
        "title_template": "Lead Information Updated",
        "message_template": "Lead #${lead_id} updated: ${updated_summary} by ${actor_name}.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {
                "inner_resolver": {
                    "resolver_type": "composite",
                    "params": {"resolvers": [
                        {"resolver_type": "lead_owner", "params": {}},
                        {"resolver_type": "unit_managers", "params": {}},
                    ]},
                },
            },
        },
    },
    SystemEvents.OFFICER_AVAILABILITY_CHANGED: {
        "title_template": "Officer Availability Changed",
        "message_template": "${username} is now ${new_status}.",
        "notification_type": "info",
        "recipient_config": {
            "resolver_type": "actor_excluded",
            "params": {"inner_resolver": {"resolver_type": "all_admins", "params": {}}},
        },
    },
    SystemEvents.PAYMENT_OVERDUE: {
        "title_template": "Thanh toán quá hạn",
        "message_template": "Hóa đơn ${invoice_number} với số tiền ${amount} đã quá hạn ${days_overdue} ngày.",
        "notification_type": "error",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.PAYMENT_RECEIVED: {
        "title_template": "Payment Received",
        "message_template": "Your payment of ${amount} for ${payment_type} has been received. Thank you!",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.PAYMENT_REJECTED: {
        "title_template": "Thanh toán bị từ chối",
        "message_template": "Khoản thanh toán ${amount} đã bị từ chối. Lý do: ${rejection_reason}",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.PAYMENT_VERIFIED: {
        "title_template": "Thanh toán được xác nhận",
        "message_template": "Thanh toán ${amount} đã được xác nhận thành công.",
        "notification_type": "success",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.PIPELINE_CONFIG_UPDATED: {
        "title_template": "Pipeline Configuration Updated",
        "message_template": "${config_type} '${resource_name}' was ${operation}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "all_admins", "params": {}},
    },
    SystemEvents.REFUND_PROCESSED: {
        "title_template": "Hoàn tiền đã xử lý",
        "message_template": "Khoản hoàn tiền ${amount} đã được xử lý thành công.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.SUSPICIOUS_LOGIN: {
        "title_template": "⚠️ Đăng nhập mới từ thiết bị lạ",
        "message_template": "Phát hiện đăng nhập từ ${location} (${device}). Nếu không phải bạn, hãy bảo mật tài khoản ngay.",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.SYSTEM_ALERT: {
        "title_template": "[${severity}] System Alert",
        "message_template": "${message}",
        "notification_type": "warning",
        "recipient_config": {"resolver_type": "all_users", "params": {}},
    },
    SystemEvents.SYSTEM_ANNOUNCEMENT: {
        "title_template": "${title}",
        "message_template": "${message}",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "all_users", "params": {}},
    },
    SystemEvents.USER_DEACTIVATED: {
        "title_template": "Account Deactivated",
        "message_template": "Your account has been deactivated. Reason: ${reason}. Please contact administrator if you believe this is an error.",
        "notification_type": "error",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.USER_PROFILE_UPDATED: {
        "title_template": "Your profile has been updated",
        "message_template": "An administrator updated your profile. Changed fields: ${updated_fields}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
    SystemEvents.USER_ROLE_CHANGED: {
        "title_template": "Your Role Has Changed",
        "message_template": "Your role has been changed from ${old_role} to ${new_role}.",
        "notification_type": "info",
        "recipient_config": {"resolver_type": "specific_users", "params": {}},
    },
}


# Frozen snapshot (2026-04-21) of the event names seeded by the
# pre-Wave-1 `NOTIFICATION_REGISTRY`. DO NOT derive this from
# `NOTIFICATION_SEED_DEFAULTS.keys()` — that would let any future
# addition to the seed-defaults map silently widen the tombstone scope
# in `reset_notification_rules_dev.py`, reintroducing the coupling this
# refactor removes. New events should be added to
# `NOTIFICATION_SEED_DEFAULTS` only; leave this set alone unless a row
# is genuinely being retired from the legacy registry surface.
LEGACY_REGISTRY_EVENTS: frozenset[str] = frozenset({
    "application_created",
    "application_deleted",
    "application_status_changed",
    "asset_checked_out",
    "asset_maintenance_alert",
    "consultation_created",
    "consultation_deleted",
    "consultation_reminder",
    "consultation_updated",
    "ctv_approved",
    "ctv_attribution_expired",
    "ctv_attribution_expiring",
    "ctv_claim_approved",
    "ctv_claim_rejected",
    "ctv_claim_submitted",
    "ctv_commission_created",
    "ctv_lead_converted",
    "ctv_suspended",
    "ctv_weekly_summary",
    "dorm_fee_created",
    "dorm_maintenance_request",
    "dorm_room_assigned",
    "fee_fully_paid",
    "holiday_calendar_incomplete",
    "invoice_issued",
    "lead_assigned",
    "lead_assignment_failed",
    "lead_created",
    "lead_deleted",
    "lead_imported",
    "lead_reassigned",
    "lead_restored",
    "lead_status_changed",
    "lead_updated",
    "officer_availability_changed",
    "payment_overdue",
    "payment_received",
    "payment_rejected",
    "payment_verified",
    "pipeline_config_updated",
    "refund_processed",
    "suspicious_login",
    "system_alert",
    "system_announcement",
    "user_deactivated",
    "user_profile_updated",
    "user_role_changed",
})
