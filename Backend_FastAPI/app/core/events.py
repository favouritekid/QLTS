# app/core/events.py
"""
System Events Enum - Defines all events that can trigger notifications.

Each event must have a documented payload schema to ensure consistent usage
across the application and prevent payload key mismatches.

Usage:
    from app.core.events import SystemEvents

    await dispatch(
        db=db,
        event=SystemEvents.LEAD_ASSIGNED,
        payload={"lead_id": 123, "officer_id": 456, "actor_id": 789}
    )
"""
from enum import Enum


class SystemEvents(str, Enum):
    """
    All system events that can trigger notifications.

    IMPORTANT: Each event MUST have a documented payload schema.
    This helps prevent runtime errors from missing or incorrect payload keys.
    """

    # =========================================================================
    # LEAD EVENTS
    # =========================================================================

    LEAD_ASSIGNED = "lead_assigned"
    """
    Triggered when a lead is assigned to an officer.

    Payload Schema:
        {
            "lead_id": int,           # Required: ID of the lead being assigned
            "officer_id": int,        # Required: ID of the officer receiving the lead
            "actor_id": int,          # Required: ID of the user who performed the assignment
            "lead_name": Optional[str],    # Name of the lead
            "lead_phone": Optional[str],   # Phone number of the lead
            "offering_name": Optional[str] # Name of the offering/program
        }

    Recipients: The assigned officer (officer_id)
    """

    LEAD_ASSIGNMENT_FAILED = "lead_assignment_failed"
    """
    Triggered when automatic lead assignment fails.

    Payload Schema:
        {
            "lead_id": int,           # Required: ID of the lead that couldn't be assigned
            "unit_id": int,           # Required: Unit that was trying to assign
            "reason": str,            # Required: Failure reason ("no_officers_available" | "all_officers_at_capacity")
            "lead_name": Optional[str],    # Name of the lead
            "actor_id": int           # System actor (0 for automatic assignments)
        }

    Recipients: Unit managers (need to take action)
    """

    LEAD_REASSIGNED = "lead_reassigned"
    """
    Triggered when a lead is transferred to a different unit/officer.

    Payload Schema:
        {
            "lead_id": int,               # Required: ID of the lead
            "old_officer_id": Optional[int],  # Previous officer (if any)
            "new_officer_id": Optional[int],  # New officer (if assigned)
            "old_unit_id": int,           # Previous unit ID
            "new_unit_id": int,           # New unit ID
            "actor_id": int,              # User who performed the transfer
            "reason": Optional[str]       # Reason for reassignment
        }

    Recipients: Old officer (if any), new unit staff
    """

    LEAD_STATUS_CHANGED = "lead_status_changed"
    """
    Triggered when a lead's pipeline stage changes.

    Payload Schema:
        {
            "lead_id": int,               # Required: ID of the lead
            "officer_id": Optional[int],  # Assigned officer
            "old_status": str,            # Previous pipeline stage
            "new_status": str,            # New pipeline stage
            "actor_id": int               # User who changed the status
        }

    Recipients: The assigned officer
    """

    LEAD_CREATED = "lead_created"
    """
    Triggered when a new lead is created.

    Payload Schema:
        {
            "lead_id": int,               # Required: ID of the new lead
            "unit_id": int,               # Unit responsible for this lead
            "lead_name": Optional[str],   # Name of the lead
            "source": Optional[str],      # Lead source
            "actor_id": int               # User who created the lead
        }

    Recipients: Unit staff (managers, admins)
    """

    LEAD_DELETED = "lead_deleted"
    """
    Triggered when a lead is soft-deleted.

    Payload Schema:
        {
            "lead_id": int,               # Required: ID of the deleted lead
            "lead_name": Optional[str],   # Name of the lead
            "unit_id": int,               # Unit of the lead
            "officer_id": Optional[int],  # Previously assigned officer (if any)
            "actor_id": int               # Admin who deleted the lead
        }

    Recipients: Previously assigned officer, unit managers
    """

    # =========================================================================
    # CONSULTATION EVENTS
    # =========================================================================

    CONSULTATION_CREATED = "consultation_created"
    """
    Triggered when a consultation record is created.

    Payload Schema:
        {
            "consultation_id": int,       # Required: ID of the consultation
            "lead_id": int,               # Required: ID of the lead
            "officer_id": Optional[int],  # Officer who conducted/created
            "status_id": str,             # Consultation status
            "actor_id": int               # User who created the record
        }

    Recipients: The lead's assigned officer, unit managers
    """

    CONSULTATION_UPDATED = "consultation_updated"
    """
    Triggered when a consultation record is updated.

    Payload Schema:
        {
            "consultation_id": int,       # Required: ID of the consultation
            "lead_id": int,               # Required: ID of the lead
            "officer_id": Optional[int],  # Assigned officer
            "old_status_id": Optional[str],  # Previous status
            "new_status_id": str,         # New status
            "actor_id": int               # User who made the update
        }

    Recipients: The lead's assigned officer
    """

    CONSULTATION_DELETED = "consultation_deleted"
    """
    Triggered when a consultation record is deleted.

    Payload Schema:
        {
            "consultation_id": int,       # Required: ID of the deleted consultation
            "lead_id": int,               # Required: ID of the lead
            "officer_id": Optional[int],  # Assigned officer
            "actor_id": int               # User who deleted the record
        }

    Recipients: The lead's assigned officer
    """

    CONSULTATION_REMINDER = "consultation_reminder"
    """
    Triggered by Celery Beat scheduler when a consultation is due soon.

    Payload Schema:
        {
            "consultation_id": int,       # Required: ID of the consultation
            "lead_id": int,               # Required: ID of the lead
            "lead_name": str,             # Lead's full name for display
            "lead_phone": str,            # Lead's phone number
            "officer_id": int,            # Officer to be reminded
            "scheduled_at": str,          # ISO datetime of the scheduled time
            "minutes_until": int          # Minutes until the scheduled time
        }

    Recipients: The officer assigned to the consultation
    """

    # =========================================================================
    # APPLICATION EVENTS
    # =========================================================================

    APPLICATION_CREATED = "application_created"
    """
    Triggered when a new application is created.

    Payload Schema:
        {
            "application_id": int,        # Required: ID of the application
            "lead_id": int,               # Required: ID of the lead
            "officer_id": int,            # Required: Officer handling the application
            "major_program_name": Optional[str],  # Program name
            "actor_id": int               # User who created the application
        }

    Recipients: The officer, unit managers/admins
    """

    APPLICATION_STATUS_CHANGED = "application_status_changed"
    """
    Triggered when an application's status changes.

    Payload Schema:
        {
            "application_id": int,        # Required: ID of the application
            "lead_id": int,               # Required: ID of the lead
            "officer_id": int,            # Required: Officer handling the application
            "old_status": str,            # Previous status
            "new_status": str,            # New status
            "actor_id": int               # User who changed the status
        }

    Recipients: The officer, admins
    """

    APPLICATION_DOCUMENTS_UPDATED = "application_documents_updated"
    """
    Triggered when application documents are updated.

    Payload Schema:
        {
            "application_id": int,        # Required: ID of the application
            "lead_id": int,               # Required: ID of the lead
            "officer_id": int,            # Required: Officer handling the application
            "document_summary": Optional[str],  # Brief summary of changes
            "actor_id": int               # User who updated documents
        }

    Recipients: The officer, admins
    """

    APPLICATION_DELETED = "application_deleted"
    """
    Triggered when an application is deleted.

    Payload Schema:
        {
            "application_id": int,        # Required: ID of the deleted application
            "lead_id": int,               # Required: ID of the lead
            "officer_id": int,            # Required: Officer who was handling the application
            "lead_name": Optional[str],   # Name of the lead
            "actor_id": int               # Admin who deleted the application
        }

    Recipients: The officer, admins
    """

    # =========================================================================
    # FINANCE EVENTS (Future: Dorm, Tuition, etc.)
    # =========================================================================

    DORM_FEE_CREATED = "dorm_fee_created"
    """
    Triggered when a dorm fee is created.

    Payload Schema:
        {
            "dorm_id": int,               # Required: ID of the dorm
            "fee_id": int,                # Required: ID of the fee record
            "amount": int,                # Fee amount
            "due_date": Optional[str],    # Due date (ISO 8601)
            "actor_id": int               # User who created the fee
        }

    Recipients: Dorm residents, finance staff
    """

    PAYMENT_RECEIVED = "payment_received"
    """
    Triggered when a payment is recorded.

    Payload Schema:
        {
            "payment_id": int,            # Required: ID of the payment
            "user_id": int,               # Required: User who made the payment
            "amount": int,                # Payment amount
            "payment_type": str,          # Type: tuition, dorm, etc.
            "actor_id": int               # User who recorded the payment
        }

    Recipients: The user who made payment, finance staff
    """

    PAYMENT_OVERDUE = "payment_overdue"
    """
    Triggered when a payment becomes overdue.

    Payload Schema:
        {
            "fee_id": int,                # Required: ID of the overdue fee
            "user_id": int,               # Required: User with overdue payment
            "amount": int,                # Overdue amount
            "days_overdue": int,          # Number of days overdue
            "fee_type": str               # Type: tuition, dorm, etc.
        }

    Recipients: The user with overdue payment, finance staff
    """

    # =========================================================================
    # DORM EVENTS (Future)
    # =========================================================================

    DORM_ROOM_ASSIGNED = "dorm_room_assigned"
    """
    Triggered when a student is assigned to a dorm room.

    Payload Schema:
        {
            "dorm_id": int,               # Required: ID of the dorm
            "room_id": int,               # Required: ID of the room
            "student_id": int,            # Required: ID of the student
            "actor_id": int               # User who made the assignment
        }

    Recipients: The student, dorm managers
    """

    DORM_MAINTENANCE_REQUEST = "dorm_maintenance_request"
    """
    Triggered when a maintenance request is submitted.

    Payload Schema:
        {
            "request_id": int,            # Required: ID of the request
            "dorm_id": int,               # Required: ID of the dorm
            "room_id": Optional[int],     # Room (if applicable)
            "priority": str,              # Priority: low, medium, high, urgent
            "description": str,           # Brief description
            "reporter_id": int            # User who reported the issue
        }

    Recipients: Dorm maintenance staff, dorm managers
    """

    # =========================================================================
    # ASSET EVENTS (Future)
    # =========================================================================

    ASSET_MAINTENANCE_ALERT = "asset_maintenance_alert"
    """
    Triggered when an asset needs maintenance.

    Payload Schema:
        {
            "asset_id": int,              # Required: ID of the asset
            "asset_name": str,            # Name of the asset
            "maintenance_type": str,      # Type: scheduled, emergency
            "due_date": Optional[str],    # Maintenance due date
            "unit_id": Optional[int]      # Unit responsible for asset
        }

    Recipients: Asset managers, unit staff
    """

    ASSET_CHECKED_OUT = "asset_checked_out"
    """
    Triggered when an asset is checked out.

    Payload Schema:
        {
            "asset_id": int,              # Required: ID of the asset
            "asset_name": str,            # Name of the asset
            "borrower_id": int,           # User who borrowed the asset
            "expected_return": Optional[str],  # Expected return date
            "actor_id": int               # User who processed checkout
        }

    Recipients: Asset managers
    """

    # =========================================================================
    # SYSTEM EVENTS
    # =========================================================================

    SYSTEM_ALERT = "system_alert"
    """
    General system alert for important notifications.

    Payload Schema:
        {
            "severity": str,              # Required: "info" | "warning" | "error"
            "message": str,               # Required: Alert message
            "action_url": Optional[str],  # URL for action (if any)
            "expires_at": Optional[str]   # Expiration time (ISO 8601)
        }

    Recipients: All active users or specified user_ids
    """

    SYSTEM_ANNOUNCEMENT = "system_announcement"
    """
    System-wide announcement.

    Payload Schema:
        {
            "title": str,                 # Required: Announcement title
            "message": str,               # Required: Announcement message
            "priority": str,              # Priority: normal, high
            "actor_id": int               # Admin who created the announcement
        }

    Recipients: All active users
    """

    USER_ROLE_CHANGED = "user_role_changed"
    """
    Triggered when a user's role is changed.

    Payload Schema:
        {
            "user_id": int,               # Required: ID of the affected user
            "old_role": str,              # Previous role
            "new_role": str,              # New role
            "unit_id": Optional[int],     # Unit (if applicable)
            "actor_id": int               # Admin who changed the role
        }

    Recipients: The affected user
    """

    USER_DEACTIVATED = "user_deactivated"
    """
    Triggered when a user account is deactivated.

    Payload Schema:
        {
            "user_id": int,               # Required: ID of the deactivated user
            "username": str,              # Username of the deactivated user
            "old_status": str,            # Previous status (usually "active")
            "reason": Optional[str],      # Reason for deactivation
            "actor_id": int               # Admin who deactivated the user
        }

    Recipients: The deactivated user (for awareness before logout)
    """

    # =========================================================================
    # PIPELINE CONFIG EVENTS
    # =========================================================================

    PIPELINE_CONFIG_UPDATED = "pipeline_config_updated"
    """
    Triggered when pipeline configuration is updated.

    Payload Schema:
        {
            "config_type": str,           # Type: pipeline_stage, consultation_status, etc.
            "operation": str,             # Operation: create, update, delete
            "resource_id": str | int,     # ID of the affected resource
            "resource_name": Optional[str],  # Name of the resource
            "actor_id": int               # Admin who made the change
        }

    Recipients: All admins
    """

    # =========================================================================
    # OFFICER/OPERATIONAL EVENTS
    # =========================================================================

    OFFICER_AVAILABILITY_CHANGED = "officer_availability_changed"
    """
    Triggered when an officer changes their availability status.

    Payload Schema:
        {
            "officer_id": int,            # Required: ID of the officer
            "new_status": str,            # Required: New availability status (available, busy, away)
            "old_status": Optional[str],  # Previous status (if known)
            "username": str,              # Officer's username
            "unit_id": Optional[int],     # Officer's unit ID
            "actor_id": int               # User who changed the status (usually the officer themselves)
        }

    Recipients: All admins and managers (for workload visibility)
    """


# =============================================================================
# EVENT DISPATCHER PATTERN
# =============================================================================

class EventDispatcher:
    """
    Framework-agnostic event dispatcher for service layer.

    Decouples service layer from transport layer (Socket.IO, WebHooks, etc.)
    Services dispatch domain events, handlers deliver via specific transports.

    Usage in services:
        from ..core.events import dispatcher
        await dispatcher.dispatch("user.profile_updated", user_id=123, changes={...})

    Usage in socket_manager (register on startup):
        from app.core.events import dispatcher

        async def emit_profile_updated(user_id: int, changes: dict, **kwargs):
            await sio.emit("profile_updated", {"user_id": user_id, "changes": changes})

        dispatcher.register("user.profile_updated", emit_profile_updated)
    """

    def __init__(self):
        self._handlers: dict[str, list] = {}

    def register(self, event_name: str, handler):
        """
        Register a handler for a domain event.

        Args:
            event_name: Event identifier (e.g., "user.profile_updated")
            handler: Async function to handle event
        """
        if event_name not in self._handlers:
            self._handlers[event_name] = []

        self._handlers[event_name].append(handler)
        import structlog
        log = structlog.get_logger(__name__)
        log.debug("Event handler registered", event=event_name, handler=handler.__name__)

    async def dispatch(self, event_name: str, **data):
        """
        Dispatch a domain event to all registered handlers.

        Args:
            event_name: Event identifier
            **data: Event payload (passed to handlers as kwargs)
        """
        if event_name not in self._handlers:
            return

        import structlog
        log = structlog.get_logger(__name__)
        log.info("Dispatching event", event=event_name, handler_count=len(self._handlers[event_name]))

        for handler in self._handlers[event_name]:
            try:
                await handler(**data)
                log.debug("Event handler succeeded", event=event_name, handler=handler.__name__)
            except Exception as e:
                # Log error but continue dispatching to other handlers
                log.error(
                    "Event handler failed",
                    event=event_name,
                    handler=handler.__name__,
                    error=str(e),
                    exc_info=True
                )


# Global dispatcher instance for transport-agnostic event handling
dispatcher = EventDispatcher()


# =============================================================================
# DOMAIN EVENTS FOR TRANSPORT LAYER
# =============================================================================

class TransportEvents:
    """
    Domain events for transport layer (Socket.IO, etc.)
    Use these instead of calling sio.emit() directly in services.
    """

    # User events
    USER_FORCE_LOGOUT = "user.force_logout"
    USER_PROFILE_UPDATED = "user.profile_updated"

    # Session events
    SESSION_EXPIRED_BATCH = "session.expired_batch"

