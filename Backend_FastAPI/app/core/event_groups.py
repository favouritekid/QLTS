# app/core/event_groups.py
"""
Notification Event Groups - Categorizes events for preference management.

Event groups allow users to configure notification preferences at a category level
rather than for each individual event. This provides a cleaner UX and scales
better as new events are added.

Usage:
    from app.core.event_groups import NotificationEventGroup, EVENT_GROUP_MAPPING

    # Get group for an event
    group = EVENT_GROUP_MAPPING[SystemEvents.LEAD_ASSIGNED]  # "lead"

    # Check user preference for group
    if user_preferences["lead"]["browser"]:
        send_browser_notification()
"""
from enum import Enum
from typing import Dict, List

from .events import SystemEvents


class NotificationEventGroup(str, Enum):
    """
    Notification event groups for preference management.

    Each group represents a category of events that users can configure
    notification preferences for (browser, email, sms).
    """

    LEAD = "lead"
    """Lead management events: assignment, reassignment, status changes"""

    CONSULTATION = "consultation"
    """Consultation events: created, updated, deleted"""

    APPLICATION = "application"
    """Application events: created, status changes, document updates"""

    FINANCE = "finance"
    """Finance events: fees, payments, overdue alerts"""

    DORM = "dorm"
    """Dorm events: room assignment, maintenance requests"""

    ASSET = "asset"
    """Asset management events: maintenance alerts, checkouts"""

    SYSTEM = "system"
    """System events: alerts, announcements, role changes"""

    PIPELINE = "pipeline"
    """Pipeline configuration events: stage/status updates"""

    ORGANIZATION = "organization"
    """Organization events: unit, program, offering changes (Admin only)"""

    SECURITY = "security"
    """Security events: suspicious logins, password changes, device changes"""

    CTV = "ctv"
    """CTV (Collaborator) events: claims, commissions, attribution"""


# Mapping from SystemEvents to NotificationEventGroup
# This determines which preference group controls each event
EVENT_GROUP_MAPPING: Dict[SystemEvents, NotificationEventGroup] = {
    # Lead events
    SystemEvents.LEAD_ASSIGNED: NotificationEventGroup.LEAD,
    SystemEvents.LEAD_REASSIGNED: NotificationEventGroup.LEAD,
    SystemEvents.LEAD_STATUS_CHANGED: NotificationEventGroup.LEAD,
    SystemEvents.LEAD_CREATED: NotificationEventGroup.LEAD,
    SystemEvents.LEAD_UPDATED: NotificationEventGroup.LEAD,  # ✅ Added - was missing!
    SystemEvents.LEAD_ASSIGNMENT_FAILED: NotificationEventGroup.LEAD,
    SystemEvents.LEAD_DELETED: NotificationEventGroup.LEAD,
    SystemEvents.OFFICER_AVAILABILITY_CHANGED: NotificationEventGroup.LEAD,  # Affects lead distribution

    # Consultation events
    SystemEvents.CONSULTATION_CREATED: NotificationEventGroup.CONSULTATION,
    SystemEvents.CONSULTATION_UPDATED: NotificationEventGroup.CONSULTATION,
    SystemEvents.CONSULTATION_DELETED: NotificationEventGroup.CONSULTATION,
    SystemEvents.CONSULTATION_REMINDER: NotificationEventGroup.CONSULTATION,

    # Application events
    SystemEvents.APPLICATION_CREATED: NotificationEventGroup.APPLICATION,
    SystemEvents.APPLICATION_STATUS_CHANGED: NotificationEventGroup.APPLICATION,
    SystemEvents.APPLICATION_DELETED: NotificationEventGroup.APPLICATION,

    # Finance events
    SystemEvents.DORM_FEE_CREATED: NotificationEventGroup.FINANCE,
    SystemEvents.PAYMENT_RECEIVED: NotificationEventGroup.FINANCE,
    SystemEvents.PAYMENT_OVERDUE: NotificationEventGroup.FINANCE,
    SystemEvents.PAYMENT_VERIFIED: NotificationEventGroup.FINANCE,

    # Dorm events
    SystemEvents.DORM_ROOM_ASSIGNED: NotificationEventGroup.DORM,
    SystemEvents.DORM_MAINTENANCE_REQUEST: NotificationEventGroup.DORM,

    # Asset events
    SystemEvents.ASSET_MAINTENANCE_ALERT: NotificationEventGroup.ASSET,
    SystemEvents.ASSET_CHECKED_OUT: NotificationEventGroup.ASSET,

    # System events
    SystemEvents.SYSTEM_ALERT: NotificationEventGroup.SYSTEM,
    SystemEvents.SYSTEM_ANNOUNCEMENT: NotificationEventGroup.SYSTEM,
    SystemEvents.USER_ROLE_CHANGED: NotificationEventGroup.SYSTEM,
    SystemEvents.USER_DEACTIVATED: NotificationEventGroup.SYSTEM,

    # Pipeline events
    SystemEvents.PIPELINE_CONFIG_UPDATED: NotificationEventGroup.PIPELINE,

    # Organization events
    SystemEvents.UNIT_CREATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.UNIT_UPDATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.UNIT_DELETED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.PROGRAM_CREATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.PROGRAM_UPDATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.PROGRAM_DELETED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.OFFERING_CREATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.OFFERING_UPDATED: NotificationEventGroup.ORGANIZATION,
    SystemEvents.OFFERING_DELETED: NotificationEventGroup.ORGANIZATION,

    # Security events
    SystemEvents.SUSPICIOUS_LOGIN: NotificationEventGroup.SECURITY,

    # CTV events
    SystemEvents.CTV_CLAIM_SUBMITTED: NotificationEventGroup.CTV,
    SystemEvents.CTV_CLAIM_APPROVED: NotificationEventGroup.CTV,
    SystemEvents.CTV_CLAIM_REJECTED: NotificationEventGroup.CTV,
    SystemEvents.CTV_APPROVED: NotificationEventGroup.CTV,
    SystemEvents.CTV_SUSPENDED: NotificationEventGroup.CTV,
    SystemEvents.CTV_LEAD_CONVERTED: NotificationEventGroup.CTV,
    SystemEvents.CTV_ATTRIBUTION_EXPIRING: NotificationEventGroup.CTV,
    SystemEvents.CTV_ATTRIBUTION_EXPIRED: NotificationEventGroup.CTV,
    SystemEvents.CTV_COMMISSION_CREATED: NotificationEventGroup.CTV,
    SystemEvents.CTV_WEEKLY_SUMMARY: NotificationEventGroup.CTV,
}


def get_event_group(event: SystemEvents) -> NotificationEventGroup:
    """
    Get the notification group for an event.

    Args:
        event: The system event

    Returns:
        The NotificationEventGroup for this event

    Raises:
        KeyError: If event is not mapped to a group (configuration error)
    """
    if event not in EVENT_GROUP_MAPPING:
        raise KeyError(
            f"Event {event} is not mapped to any group. "
            "Please update EVENT_GROUP_MAPPING in event_groups.py"
        )
    return EVENT_GROUP_MAPPING[event]


def get_events_by_group(group: NotificationEventGroup) -> List[SystemEvents]:
    """
    Get all events belonging to a notification group.

    Args:
        group: The notification event group

    Returns:
        List of SystemEvents belonging to this group
    """
    return [
        event for event, event_group in EVENT_GROUP_MAPPING.items()
        if event_group == group
    ]


# Human-readable labels for event groups (for frontend display)
EVENT_GROUP_LABELS: Dict[NotificationEventGroup, Dict[str, str]] = {
    NotificationEventGroup.LEAD: {
        "en": "Lead Management",
        "vi": "Quản lý Lead",
        "description_en": "Notifications about lead assignments and status changes",
        "description_vi": "Thông báo về phân công và thay đổi trạng thái lead"
    },
    NotificationEventGroup.CONSULTATION: {
        "en": "Consultations",
        "vi": "Tư vấn",
        "description_en": "Notifications about consultation records",
        "description_vi": "Thông báo về hồ sơ tư vấn"
    },
    NotificationEventGroup.APPLICATION: {
        "en": "Applications",
        "vi": "Hồ sơ",
        "description_en": "Notifications about application progress",
        "description_vi": "Thông báo về tiến độ hồ sơ"
    },
    NotificationEventGroup.FINANCE: {
        "en": "Finance",
        "vi": "Tài chính",
        "description_en": "Notifications about fees and payments",
        "description_vi": "Thông báo về học phí và thanh toán"
    },
    NotificationEventGroup.DORM: {
        "en": "Dormitory",
        "vi": "Ký túc xá",
        "description_en": "Notifications about dorm room assignments and maintenance",
        "description_vi": "Thông báo về phòng ở và bảo trì ký túc xá"
    },
    NotificationEventGroup.ASSET: {
        "en": "Asset Management",
        "vi": "Quản lý tài sản",
        "description_en": "Notifications about asset maintenance and checkouts",
        "description_vi": "Thông báo về bảo trì và mượn/trả tài sản"
    },
    NotificationEventGroup.SYSTEM: {
        "en": "System",
        "vi": "Hệ thống",
        "description_en": "System alerts and announcements",
        "description_vi": "Thông báo và cảnh báo hệ thống"
    },
    NotificationEventGroup.PIPELINE: {
        "en": "Pipeline Configuration",
        "vi": "Cấu hình Pipeline",
        "description_en": "Notifications about pipeline stage changes (Admin only)",
        "description_vi": "Thông báo về thay đổi cấu hình pipeline (Chỉ Admin)"
    },
    NotificationEventGroup.ORGANIZATION: {
        "en": "Organization Management",
        "vi": "Quản lý Tổ chức",
        "description_en": "Notifications about unit, program, and offering changes (Admin only)",
        "description_vi": "Thông báo về thay đổi đơn vị, chương trình, loại hình đào tạo (Chỉ Admin)"
    },
    NotificationEventGroup.SECURITY: {
        "en": "Security",
        "vi": "Bảo mật",
        "description_en": "Notifications about suspicious logins and security events",
        "description_vi": "Thông báo về đăng nhập đáng ngờ và sự kiện bảo mật"
    },
    NotificationEventGroup.CTV: {
        "en": "Collaborator (CTV)",
        "vi": "Cộng tác viên (CTV)",
        "description_en": "Notifications about CTV claims, commissions, and attribution",
        "description_vi": "Thông báo về claim, hoa hồng, và quyền giới thiệu CTV"
    },
}


# Available notification channels
class NotificationChannel(str, Enum):
    """Available notification delivery channels."""

    BROWSER = "browser"
    """In-app browser notification (Socket.IO + Database)"""

    EMAIL = "email"
    """Email notification"""

    SMS = "sms"
    """SMS notification (future feature)"""


# Default channel settings for each group
DEFAULT_GROUP_CHANNELS: Dict[NotificationEventGroup, Dict[NotificationChannel, bool]] = {
    NotificationEventGroup.LEAD: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.CONSULTATION: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: False,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.APPLICATION: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.FINANCE: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.DORM: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: False,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.ASSET: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: False,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.SYSTEM: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.PIPELINE: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: False,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.ORGANIZATION: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: False,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.SECURITY: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
    NotificationEventGroup.CTV: {
        NotificationChannel.BROWSER: True,
        NotificationChannel.EMAIL: True,
        NotificationChannel.SMS: False,
    },
}
