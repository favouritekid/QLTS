# app/services/notification_registry.py
"""
Notification Registry - Central configuration for all notification events.

The registry maps each SystemEvent to its:
- Notification group (for preference management)
- Resolver (to determine recipients)
- Template (title and message)
- Channels (browser, email, sms)

Template strings use Python's string.Template syntax for safe substitution.
Variables are referenced as ${variable_name}. Missing variables are left as-is
(safe_substitute behavior) to prevent crashes.

Usage:
    from app.services.notification_registry import NOTIFICATION_REGISTRY, get_event_config

    config = get_event_config(SystemEvents.LEAD_ASSIGNED)
    resolver = config["resolver"]
    template = config["template"]
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from string import Template
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.core.events import SystemEvents
from app.core.event_groups import NotificationEventGroup, EVENT_GROUP_MAPPING
from app.services.notification_resolvers import (
    BaseResolver,
    LeadOwnerResolver,
    UnitStaffResolver,
    UnitManagersResolver,
    AllAdminsResolver,
    AllUsersResolver,
    SpecificUsersResolver,
    DormResidentsResolver,
    DormStaffResolver,
    CollaboratorUserResolver,
    CompositeResolver,
    ActorExcludedResolver,
)

log = logging.getLogger(__name__)


# =============================================================================
# ENUMS FOR TYPE SAFETY
# =============================================================================


class NotificationChannel(str, Enum):
    """Supported notification delivery channels."""
    BROWSER = "browser"  # In-browser notifications (delivered via Socket.IO)
    EMAIL = "email"
    SMS = "sms"
    ZALO = "zalo"


class NotificationType(str, Enum):
    """Notification types for UI styling and behavior."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    REMINDER = "reminder"
    ADMIN_UPDATE = "admin_update"  # Admin actions affecting user
    SYSTEM = "system"              # System-level notifications



# =============================================================================
# NOTIFICATION CONFIG (FROZEN DATACLASS)
# =============================================================================


@dataclass(frozen=True)
class NotificationConfig:
    """
    Immutable configuration for a notification event.
    
    This is a frozen dataclass to prevent accidental runtime modification.
    All registry entries are defined at module load time and should not change.
    
    Attributes:
        group: The event group for preference management
        resolver: Resolver instance to determine recipients
        template: Tuple of (title, message) template strings
        channels: Tuple of delivery channels
        notification_type: Type for UI styling
        link_template: Optional URL template for notification link
        priority: Priority for queue ordering (lower = higher priority)
        dedup_key_template: Template for deduplication key generation
    """
    group: NotificationEventGroup
    resolver: BaseResolver
    template: Tuple[str, str]  # (title, message)
    channels: Tuple[NotificationChannel, ...]
    notification_type: NotificationType = NotificationType.INFO
    link_template: Optional[str] = None
    priority: int = 100  # Default priority, lower = higher priority
    dedup_key_template: Optional[str] = None  # e.g., "lead:${lead_id}:assigned"
    
    def render_title(self, payload: dict) -> str:
        """Render title template with payload data."""
        return Template(self.template[0]).safe_substitute(payload)

    def render_message(self, payload: dict) -> str:
        """Render message template with payload data."""
        return Template(self.template[1]).safe_substitute(payload)

    def render_link(self, payload: dict) -> Optional[str]:
        """Render link template with payload data if configured."""
        if not self.link_template:
            return None
        return Template(self.link_template).safe_substitute(payload)
    
    def render_dedup_key(self, payload: dict) -> Optional[str]:
        """Render deduplication key template with payload data."""
        if not self.dedup_key_template:
            return None
        return Template(self.dedup_key_template).safe_substitute(payload)
    
    @property
    def channel_values(self) -> List[str]:
        """Get channel values as list of strings (for backward compatibility)."""
        return [c.value for c in self.channels]


# =============================================================================
# NOTIFICATION REGISTRY
# =============================================================================

# Shorthand aliases for cleaner registry entries
CH = NotificationChannel
NT = NotificationType

NOTIFICATION_REGISTRY: Dict[SystemEvents, NotificationConfig] = {
    # =========================================================================
    # 🔔 LEAD EVENTS (High Volume)
    # =========================================================================

    SystemEvents.LEAD_ASSIGNED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=LeadOwnerResolver(),
        template=(
            "New Lead Assigned",
            "Lead #${lead_id} (${lead_name}) has been assigned to you."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.INFO,
        link_template="/leads/${lead_id}",
        priority=50,  # High priority for new assignments
        dedup_key_template="lead:${lead_id}:assigned:${officer_id}"
    ),

    SystemEvents.LEAD_ASSIGNMENT_FAILED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(UnitManagersResolver()),
        template=(
            "Lead Assignment Failed",
            "Lead #${lead_id} (${lead_name}) could not be assigned automatically. Reason: ${reason}. Please assign manually or adjust officer capacity."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.ERROR,
        link_template="/leads/${lead_id}",
        priority=30,  # Critical - needs attention
    ),

    SystemEvents.LEAD_REASSIGNED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=CompositeResolver([
            SpecificUsersResolver(),
            ActorExcludedResolver(UnitManagersResolver())
        ]),
        template=(
            "Lead Transferred",
            "Lead #${lead_id} has been transferred from Unit #${old_unit_id} to Unit #${new_unit_id}. Reason: ${reason}"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/leads/${lead_id}",
        priority=60,
        dedup_key_template="lead:${lead_id}:reassigned"
    ),

    SystemEvents.LEAD_STATUS_CHANGED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=LeadOwnerResolver(),
        template=(
            "Lead Status Updated",
            "Lead #${lead_id} status changed from ${old_status} to ${new_status}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/leads/${lead_id}",
        priority=100,
        dedup_key_template="lead:${lead_id}:status:${new_status}"
    ),

    SystemEvents.LEAD_CREATED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(UnitManagersResolver()),
        template=(
            "New Lead Created",
            "A new lead (${lead_name}) has been created from ${source}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.SUCCESS,
        link_template="/leads/${lead_id}",
        priority=80,
    ),

    SystemEvents.LEAD_DELETED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(CompositeResolver([
            SpecificUsersResolver(),
            UnitManagersResolver()
        ])),
        template=(
            "Lead Deleted",
            "Lead #${lead_id} (${lead_name}) has been deleted."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.WARNING,
        link_template="/leads",
        priority=100,
    ),

    SystemEvents.LEAD_UPDATED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            UnitManagersResolver()
        ])),
        template=(
            "Lead Information Updated",
            "Lead #${lead_id} updated: ${updated_summary} by ${actor_name}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/leads/${lead_id}",
        priority=150,  # Lower priority - routine updates
    ),

    # =========================================================================
    # 📞 CONSULTATION EVENTS
    # =========================================================================

    SystemEvents.CONSULTATION_CREATED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            UnitManagersResolver()
        ])),
        template=(
            "New Consultation Added",
            "A consultation has been added to Lead #${lead_id}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/leads/${lead_id}?tab=consultations",
        priority=100,
    ),

    SystemEvents.CONSULTATION_UPDATED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(LeadOwnerResolver()),
        template=(
            "Consultation Updated",
            "Consultation #${consultation_id} for Lead #${lead_id} has been updated."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/leads/${lead_id}?tab=consultations",
        priority=120,
    ),

    SystemEvents.CONSULTATION_DELETED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(LeadOwnerResolver()),
        template=(
            "Consultation Deleted",
            "Consultation #${consultation_id} for Lead #${lead_id} has been deleted."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.WARNING,
        link_template="/leads/${lead_id}?tab=consultations",
        priority=100,
    ),

    SystemEvents.CONSULTATION_REMINDER: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=LeadOwnerResolver(),
        template=(
            "⏰ Nhắc nhở: Lịch hẹn tư vấn",
            "Bạn có lịch hẹn gọi ${lead_name} (${lead_phone}) trong ${minutes_until} phút nữa."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.REMINDER,
        link_template="/leads/${lead_id}",
        priority=10,  # Very high priority for reminders
        dedup_key_template="reminder:${lead_id}:${consultation_id}"
    ),

    # =========================================================================
    # 📋 APPLICATION EVENTS
    # =========================================================================

    SystemEvents.APPLICATION_CREATED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template=(
            "New Application Created",
            "Application #${application_id} created for Lead #${lead_id} - ${major_program_name}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        link_template="/applications/${application_id}",
        priority=70,
    ),

    SystemEvents.APPLICATION_STATUS_CHANGED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template=(
            "Application Status Changed",
            "Application #${application_id} status changed from ${old_status} to ${new_status}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.INFO,
        link_template="/applications/${application_id}",
        priority=80,
        dedup_key_template="app:${application_id}:status:${new_status}"
    ),

    SystemEvents.APPLICATION_DOCUMENTS_UPDATED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template=(
            "Application Documents Updated",
            "Documents for Application #${application_id} have been updated: ${document_summary}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/applications/${application_id}",
        priority=120,
    ),

    SystemEvents.APPLICATION_DELETED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            SpecificUsersResolver(),
            AllAdminsResolver()
        ])),
        template=(
            "Application Deleted",
            "Application #${application_id} for ${lead_name} has been deleted."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.WARNING,
        link_template="/applications",
        priority=100,
    ),

    # =========================================================================
    # 💰 FINANCE EVENTS
    # =========================================================================

    SystemEvents.DORM_FEE_CREATED: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=DormResidentsResolver(),
        template=(
            "Dorm Fee Notification",
            "A new dorm fee of ${amount} has been created. Due date: ${due_date}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/finance/fees/${fee_id}",
        priority=60,
    ),

    SystemEvents.PAYMENT_RECEIVED: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=SpecificUsersResolver(),
        template=(
            "Payment Received",
            "Your payment of ${amount} for ${payment_type} has been received. Thank you!"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        link_template="/finance/payments/${payment_id}",
        priority=70,
    ),

    SystemEvents.PAYMENT_OVERDUE: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=SpecificUsersResolver(),
        template=(
            "Payment Overdue",
            "Your ${fee_type} payment of ${amount} is ${days_overdue} days overdue. Please settle immediately."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.ERROR,
        link_template="/finance/fees/${fee_id}",
        priority=20,  # Very high priority for overdue
    ),

    # =========================================================================
    # 🏠 DORM EVENTS
    # =========================================================================

    SystemEvents.DORM_ROOM_ASSIGNED: NotificationConfig(
        group=NotificationEventGroup.DORM,
        resolver=SpecificUsersResolver(),
        template=(
            "Room Assignment",
            "You have been assigned to Room ${room_id} in Dorm ${dorm_id}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        link_template="/dorm/rooms/${room_id}",
        priority=60,
    ),

    SystemEvents.DORM_MAINTENANCE_REQUEST: NotificationConfig(
        group=NotificationEventGroup.DORM,
        resolver=DormStaffResolver(),
        template=(
            "Maintenance Request [${priority}]",
            "New maintenance request for Dorm ${dorm_id}: ${description}"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/dorm/maintenance/${request_id}",
        priority=50,
    ),

    # =========================================================================
    # 🏷️ ASSET EVENTS
    # =========================================================================

    SystemEvents.ASSET_MAINTENANCE_ALERT: NotificationConfig(
        group=NotificationEventGroup.ASSET,
        resolver=ActorExcludedResolver(UnitStaffResolver()),
        template=(
            "Asset Maintenance Alert",
            "Asset '${asset_name}' requires ${maintenance_type} maintenance by ${due_date}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/assets/${asset_id}",
        priority=70,
    ),

    SystemEvents.ASSET_CHECKED_OUT: NotificationConfig(
        group=NotificationEventGroup.ASSET,
        resolver=AllAdminsResolver(),
        template=(
            "Asset Checked Out",
            "Asset '${asset_name}' has been checked out. Expected return: ${expected_return}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/assets/${asset_id}",
        priority=120,
    ),

    # =========================================================================
    # 🛠️ SYSTEM EVENTS (Admin/Operational)
    # =========================================================================

    SystemEvents.SYSTEM_ALERT: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=AllUsersResolver(),
        template=(
            "[${severity}] System Alert",
            "${message}"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="${action_url}",
        priority=10,  # Critical system alerts
    ),

    SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=AllAdminsResolver(),
        template=(
            "Lịch lễ năm ${year} chưa đầy đủ",
            "${message}"
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.WARNING,
        link_template="${action_url}",
        priority=20,
    ),

    SystemEvents.SYSTEM_ANNOUNCEMENT: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=AllUsersResolver(),
        template=(
            "${title}",
            "${message}"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.INFO,
        link_template=None,
        priority=50,
    ),

    SystemEvents.USER_ROLE_CHANGED: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=SpecificUsersResolver(),
        template=(
            "Your Role Has Changed",
            "Your role has been changed from ${old_role} to ${new_role}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.INFO,
        link_template="/profile",
        priority=40,
    ),

    SystemEvents.USER_DEACTIVATED: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=SpecificUsersResolver(),
        template=(
            "Account Deactivated",
            "Your account has been deactivated. Reason: ${reason}. Please contact administrator if you believe this is an error."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.ERROR,
        link_template=None,
        priority=5,  # Highest priority
    ),

    # =========================================================================
    # ⚙️ PIPELINE EVENTS (Admin Only)
    # =========================================================================

    SystemEvents.PIPELINE_CONFIG_UPDATED: NotificationConfig(
        group=NotificationEventGroup.PIPELINE,
        resolver=AllAdminsResolver(),
        template=(
            "Pipeline Configuration Updated",
            "${config_type} '${resource_name}' was ${operation}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/admin/pipeline",
        priority=100,
    ),

    # =========================================================================
    # 👤 OFFICER/OPERATIONAL EVENTS
    # =========================================================================

    SystemEvents.OFFICER_AVAILABILITY_CHANGED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(AllAdminsResolver()),
        template=(
            "Officer Availability Changed",
            "${username} is now ${new_status}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/admin/officers",
        priority=100,
    ),

    # =========================================================================
    # 🔐 SECURITY EVENTS
    # =========================================================================

    # =========================================================================
    # 🤝 CTV (COLLABORATOR) EVENTS
    # =========================================================================

    SystemEvents.CTV_CLAIM_SUBMITTED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=UnitManagersResolver(),
        template=(
            "CTV gửi claim mới",
            "${collaborator_name} đã gửi claim cho lead ${lead_name}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.INFO,
        link_template="/admin/collaborators/claims/${claim_id}",
        priority=60,
        dedup_key_template="ctv:claim:${claim_id}:submitted"
    ),

    SystemEvents.CTV_CLAIM_APPROVED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Claim được duyệt",
            "Claim #${claim_id} của bạn đã được duyệt. Lead đã được ghi nhận."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        link_template="/ctv/claims",
        priority=50,
        dedup_key_template="ctv:claim:${claim_id}:approved"
    ),

    SystemEvents.CTV_CLAIM_REJECTED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Claim bị từ chối",
            "Claim #${claim_id} đã bị từ chối. Lý do: ${rejection_reason}"
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/ctv/claims",
        priority=50,
        dedup_key_template="ctv:claim:${claim_id}:rejected"
    ),

    SystemEvents.CTV_APPROVED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Tài khoản CTV đã được duyệt",
            "Tài khoản CTV của bạn đã được duyệt. Bạn có thể bắt đầu giới thiệu lead."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        priority=30,
        dedup_key_template="ctv:${collaborator_id}:approved"
    ),

    SystemEvents.CTV_SUSPENDED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Tài khoản CTV bị đình chỉ",
            "Tài khoản CTV của bạn đã bị đình chỉ. Liên hệ quản lý để biết thêm chi tiết."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.ERROR,
        priority=20,
        dedup_key_template="ctv:${collaborator_id}:suspended"
    ),

    SystemEvents.CTV_LEAD_CONVERTED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Lead tiến triển",
            "Lead #${lead_id} đã chuyển sang trạng thái ${new_status}."
        ),
        channels=(CH.BROWSER,),
        notification_type=NT.SUCCESS,
        link_template="/ctv/leads",
        priority=80,
        dedup_key_template="ctv:lead:${lead_id}:converted:${new_status}"
    ),

    SystemEvents.CTV_ATTRIBUTION_EXPIRED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Quyền giới thiệu hết hạn",
            "Quyền giới thiệu cho lead #${lead_id} đã hết hạn sau 90 ngày."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/ctv/leads",
        priority=40,
        dedup_key_template="ctv:attribution:${lead_id}:expired"
    ),

    SystemEvents.CTV_COMMISSION_CREATED: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Hoa hồng mới",
            "Bạn nhận được hoa hồng ${amount} VND cho lead #${lead_id}."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.SUCCESS,
        link_template="/ctv/commissions",
        priority=30,
        dedup_key_template="ctv:commission:${commission_id}:created"
    ),

    SystemEvents.CTV_ATTRIBUTION_EXPIRING: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Quyền giới thiệu sắp hết hạn",
            "Quyền giới thiệu cho lead #${lead_id} sẽ hết hạn trong ${days_remaining} ngày."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/ctv/leads",
        priority=35,
        dedup_key_template="ctv:attribution:${lead_id}:expiring"
    ),

    SystemEvents.CTV_WEEKLY_SUMMARY: NotificationConfig(
        group=NotificationEventGroup.CTV,
        resolver=CollaboratorUserResolver(),
        template=(
            "Báo cáo tuần CTV",
            "Tuần này: ${new_leads} lead mới, ${commissions} hoa hồng."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.INFO,
        link_template="/ctv",
        priority=90,
        dedup_key_template="ctv:weekly:${collaborator_id}:${week}"
    ),

    SystemEvents.SUSPICIOUS_LOGIN: NotificationConfig(
        group=NotificationEventGroup.SECURITY,
        resolver=SpecificUsersResolver(),
        template=(
            "⚠️ Đăng nhập mới từ thiết bị lạ",
            "Phát hiện đăng nhập từ ${location} (${device}). Nếu không phải bạn, hãy bảo mật tài khoản ngay."
        ),
        channels=(CH.BROWSER, CH.EMAIL),
        notification_type=NT.WARNING,
        link_template="/settings/login-history",  # Fixed: was /settings/security
        priority=10,  # High priority for security events
        dedup_key_template="security:${user_id}:suspicious_login:${login_history_id}"
    ),
}



# =============================================================================
# REGISTRY FUNCTIONS
# =============================================================================

def get_event_config(event: SystemEvents) -> Optional[NotificationConfig]:
    """
    Get the notification configuration for an event.

    Args:
        event: The system event

    Returns:
        NotificationConfig or None if event not registered
    """
    return NOTIFICATION_REGISTRY.get(event)


def validate_registry() -> List[str]:
    """
    Validate the notification registry at startup.

    Checks:
    1. All registered events have valid configs
    2. All events have resolvers
    3. Templates can be parsed
    4. Channels are valid enums

    Note: Not all SystemEvents need to be registered - some are
    domain-only events without user notifications.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    for event, config in NOTIFICATION_REGISTRY.items():
        # Check group matches EVENT_GROUP_MAPPING (if event is mapped)
        if event in EVENT_GROUP_MAPPING:
            expected_group = EVENT_GROUP_MAPPING[event]
            if config.group != expected_group:
                errors.append(
                    f"Event {event} has group {config.group} but "
                    f"EVENT_GROUP_MAPPING says {expected_group}"
                )

        # Check resolver exists
        if not config.resolver:
            errors.append(f"Event {event} has no resolver")

        # Check template can be parsed
        try:
            Template(config.template[0])  # title
            Template(config.template[1])  # message
        except Exception as e:
            errors.append(f"Event {event} has invalid template: {str(e)}")

        # Check channels are valid NotificationChannel enums
        for channel in config.channels:
            if not isinstance(channel, NotificationChannel):
                errors.append(
                    f"Event {event} has invalid channel type: {channel} (expected NotificationChannel)"
                )
        
        # Check notification_type is valid enum
        if not isinstance(config.notification_type, NotificationType):
            errors.append(
                f"Event {event} has invalid notification_type: {config.notification_type}"
            )

    return errors


def initialize_registry():
    """
    Initialize and validate the notification registry.

    Should be called at application startup.

    Raises:
        RuntimeError: If validation fails
    """
    log.info("Initializing notification registry...")

    errors = validate_registry()

    if errors:
        error_msg = "Notification registry validation failed:\n" + "\n".join(errors)
        log.error(error_msg)
        raise RuntimeError(error_msg)

    log.info(
        f"Notification registry initialized successfully with "
        f"{len(NOTIFICATION_REGISTRY)} events"
    )


def get_registered_events() -> List[SystemEvents]:
    """Get all registered events."""
    return list(NOTIFICATION_REGISTRY.keys())


def get_events_by_channel(channel: str) -> List[SystemEvents]:
    """Get all events that use a specific channel."""
    return [
        event for event, config in NOTIFICATION_REGISTRY.items()
        if channel in config.channels
    ]
