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
from string import Template
from typing import Any, Dict, List, Optional

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
    CompositeResolver,
    ActorExcludedResolver,
)

log = logging.getLogger(__name__)


# Type definitions for registry entries
class NotificationConfig:
    """Configuration for a notification event."""

    def __init__(
        self,
        group: NotificationEventGroup,
        resolver: BaseResolver,
        template: Dict[str, str],
        channels: List[str],
        notification_type: str = "info",
        link_template: Optional[str] = None,
    ):
        """
        Initialize notification configuration.

        Args:
            group: The event group for preference management
            resolver: Resolver instance to determine recipients
            template: Dict with "title" and "message" template strings
            channels: List of channels: "browser", "email", "sms"
            notification_type: Type for UI styling: info, success, warning, error
            link_template: Optional URL template for notification link
        """
        self.group = group
        self.resolver = resolver
        self.template = template
        self.channels = channels
        self.notification_type = notification_type
        self.link_template = link_template

    def render_title(self, payload: dict) -> str:
        """Render title template with payload data."""
        return Template(self.template["title"]).safe_substitute(payload)

    def render_message(self, payload: dict) -> str:
        """Render message template with payload data."""
        return Template(self.template["message"]).safe_substitute(payload)

    def render_link(self, payload: dict) -> Optional[str]:
        """Render link template with payload data if configured."""
        if not self.link_template:
            return None
        return Template(self.link_template).safe_substitute(payload)


# =============================================================================
# NOTIFICATION REGISTRY
# =============================================================================

NOTIFICATION_REGISTRY: Dict[SystemEvents, NotificationConfig] = {
    # =========================================================================
    # LEAD EVENTS
    # =========================================================================

    SystemEvents.LEAD_ASSIGNED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=LeadOwnerResolver(),
        template={
            "title": "New Lead Assigned",
            "message": "Lead #${lead_id} (${lead_name}) has been assigned to you."
        },
        channels=["browser", "email"],
        notification_type="info",
        link_template="/leads/${lead_id}"
    ),

    SystemEvents.LEAD_REASSIGNED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=CompositeResolver([
            SpecificUsersResolver(),  # Will use old_officer_id and new_officer_id
            ActorExcludedResolver(UnitManagersResolver())
        ]),
        template={
            "title": "Lead Transferred",
            "message": "Lead #${lead_id} has been transferred from Unit #${old_unit_id} to Unit #${new_unit_id}. Reason: ${reason}"
        },
        channels=["browser", "email"],
        notification_type="warning",
        link_template="/leads/${lead_id}"
    ),

    SystemEvents.LEAD_STATUS_CHANGED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=LeadOwnerResolver(),
        template={
            "title": "Lead Status Updated",
            "message": "Lead #${lead_id} status changed from ${old_status} to ${new_status}."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/leads/${lead_id}"
    ),

    SystemEvents.LEAD_CREATED: NotificationConfig(
        group=NotificationEventGroup.LEAD,
        resolver=ActorExcludedResolver(UnitManagersResolver()),
        template={
            "title": "New Lead Created",
            "message": "A new lead (${lead_name}) has been created from ${source}."
        },
        channels=["browser"],
        notification_type="success",
        link_template="/leads/${lead_id}"
    ),

    # =========================================================================
    # CONSULTATION EVENTS
    # =========================================================================

    SystemEvents.CONSULTATION_CREATED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            UnitManagersResolver()
        ])),
        template={
            "title": "New Consultation Added",
            "message": "A consultation has been added to Lead #${lead_id}."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/leads/${lead_id}?tab=consultations"
    ),

    SystemEvents.CONSULTATION_UPDATED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(LeadOwnerResolver()),
        template={
            "title": "Consultation Updated",
            "message": "Consultation #${consultation_id} for Lead #${lead_id} has been updated."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/leads/${lead_id}?tab=consultations"
    ),

    SystemEvents.CONSULTATION_DELETED: NotificationConfig(
        group=NotificationEventGroup.CONSULTATION,
        resolver=ActorExcludedResolver(LeadOwnerResolver()),
        template={
            "title": "Consultation Deleted",
            "message": "Consultation #${consultation_id} for Lead #${lead_id} has been deleted."
        },
        channels=["browser"],
        notification_type="warning",
        link_template="/leads/${lead_id}?tab=consultations"
    ),

    # =========================================================================
    # APPLICATION EVENTS
    # =========================================================================

    SystemEvents.APPLICATION_CREATED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template={
            "title": "New Application Created",
            "message": "Application #${application_id} created for Lead #${lead_id} - ${major_program_name}."
        },
        channels=["browser", "email"],
        notification_type="success",
        link_template="/applications/${application_id}"
    ),

    SystemEvents.APPLICATION_STATUS_CHANGED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template={
            "title": "Application Status Changed",
            "message": "Application #${application_id} status changed from ${old_status} to ${new_status}."
        },
        channels=["browser", "email"],
        notification_type="info",
        link_template="/applications/${application_id}"
    ),

    SystemEvents.APPLICATION_DOCUMENTS_UPDATED: NotificationConfig(
        group=NotificationEventGroup.APPLICATION,
        resolver=ActorExcludedResolver(CompositeResolver([
            LeadOwnerResolver(),
            AllAdminsResolver()
        ])),
        template={
            "title": "Application Documents Updated",
            "message": "Documents for Application #${application_id} have been updated: ${document_summary}."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/applications/${application_id}"
    ),

    # =========================================================================
    # FINANCE EVENTS
    # =========================================================================

    SystemEvents.DORM_FEE_CREATED: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=DormResidentsResolver(),
        template={
            "title": "Dorm Fee Notification",
            "message": "A new dorm fee of ${amount} has been created. Due date: ${due_date}."
        },
        channels=["browser", "email"],
        notification_type="warning",
        link_template="/finance/fees/${fee_id}"
    ),

    SystemEvents.PAYMENT_RECEIVED: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=SpecificUsersResolver(),
        template={
            "title": "Payment Received",
            "message": "Your payment of ${amount} for ${payment_type} has been received. Thank you!"
        },
        channels=["browser", "email"],
        notification_type="success",
        link_template="/finance/payments/${payment_id}"
    ),

    SystemEvents.PAYMENT_OVERDUE: NotificationConfig(
        group=NotificationEventGroup.FINANCE,
        resolver=SpecificUsersResolver(),
        template={
            "title": "Payment Overdue",
            "message": "Your ${fee_type} payment of ${amount} is ${days_overdue} days overdue. Please settle immediately."
        },
        channels=["browser", "email"],
        notification_type="error",
        link_template="/finance/fees/${fee_id}"
    ),

    # =========================================================================
    # DORM EVENTS
    # =========================================================================

    SystemEvents.DORM_ROOM_ASSIGNED: NotificationConfig(
        group=NotificationEventGroup.DORM,
        resolver=SpecificUsersResolver(),
        template={
            "title": "Room Assignment",
            "message": "You have been assigned to Room ${room_id} in Dorm ${dorm_id}."
        },
        channels=["browser", "email"],
        notification_type="success",
        link_template="/dorm/rooms/${room_id}"
    ),

    SystemEvents.DORM_MAINTENANCE_REQUEST: NotificationConfig(
        group=NotificationEventGroup.DORM,
        resolver=DormStaffResolver(),
        template={
            "title": "Maintenance Request [${priority}]",
            "message": "New maintenance request for Dorm ${dorm_id}: ${description}"
        },
        channels=["browser", "email"],
        notification_type="warning",
        link_template="/dorm/maintenance/${request_id}"
    ),

    # =========================================================================
    # ASSET EVENTS
    # =========================================================================

    SystemEvents.ASSET_MAINTENANCE_ALERT: NotificationConfig(
        group=NotificationEventGroup.ASSET,
        resolver=ActorExcludedResolver(UnitStaffResolver()),
        template={
            "title": "Asset Maintenance Alert",
            "message": "Asset '${asset_name}' requires ${maintenance_type} maintenance by ${due_date}."
        },
        channels=["browser", "email"],
        notification_type="warning",
        link_template="/assets/${asset_id}"
    ),

    SystemEvents.ASSET_CHECKED_OUT: NotificationConfig(
        group=NotificationEventGroup.ASSET,
        resolver=AllAdminsResolver(),
        template={
            "title": "Asset Checked Out",
            "message": "Asset '${asset_name}' has been checked out. Expected return: ${expected_return}."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/assets/${asset_id}"
    ),

    # =========================================================================
    # SYSTEM EVENTS
    # =========================================================================

    SystemEvents.SYSTEM_ALERT: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=AllUsersResolver(),
        template={
            "title": "[${severity}] System Alert",
            "message": "${message}"
        },
        channels=["browser", "email"],
        notification_type="warning",  # Will be overridden by severity
        link_template="${action_url}"
    ),

    SystemEvents.SYSTEM_ANNOUNCEMENT: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=AllUsersResolver(),
        template={
            "title": "${title}",
            "message": "${message}"
        },
        channels=["browser", "email"],
        notification_type="info",
        link_template=None
    ),

    SystemEvents.USER_ROLE_CHANGED: NotificationConfig(
        group=NotificationEventGroup.SYSTEM,
        resolver=SpecificUsersResolver(),
        template={
            "title": "Your Role Has Changed",
            "message": "Your role has been changed from ${old_role} to ${new_role}."
        },
        channels=["browser", "email"],
        notification_type="info",
        link_template="/profile"
    ),

    # =========================================================================
    # PIPELINE EVENTS
    # =========================================================================

    SystemEvents.PIPELINE_CONFIG_UPDATED: NotificationConfig(
        group=NotificationEventGroup.PIPELINE,
        resolver=AllAdminsResolver(),
        template={
            "title": "Pipeline Configuration Updated",
            "message": "${config_type} '${resource_name}' was ${operation}."
        },
        channels=["browser"],
        notification_type="info",
        link_template="/admin/pipeline"
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
    1. All events have valid groups
    2. All events have resolvers
    3. Templates can be parsed

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    for event in SystemEvents:
        # Check if event is registered
        if event not in NOTIFICATION_REGISTRY:
            errors.append(f"Event {event} is not registered in NOTIFICATION_REGISTRY")
            continue

        config = NOTIFICATION_REGISTRY[event]

        # Check group matches EVENT_GROUP_MAPPING
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
            Template(config.template["title"])
            Template(config.template["message"])
        except Exception as e:
            errors.append(f"Event {event} has invalid template: {str(e)}")

        # Check channels are valid
        valid_channels = {"browser", "email", "sms"}
        invalid_channels = set(config.channels) - valid_channels
        if invalid_channels:
            errors.append(
                f"Event {event} has invalid channels: {invalid_channels}"
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
