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

    LEAD_UPDATED = "lead_updated"
    """
    Triggered when a lead is updated (any field change).

    Payload Schema:
        {
            "lead_id": int,               # Required: ID of the lead
            "updated_fields": List[str],  # List of field names that were updated
            "status_changed": bool,       # Whether status/stage changed
            "actor_id": int,              # User who updated the lead
            "actor_name": str             # Name of the user who updated
        }

    Recipients: The assigned officer, unit managers
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

    LEAD_RESTORED = "lead_restored"
    """
    Triggered when a soft-deleted lead is restored.

    Payload Schema:
        {
            "lead_id": int,
            "lead_name": Optional[str],
            "unit_id": int,
            "officer_id": Optional[int],
            "actor_id": int,
            "actor_name": str
        }

    Recipients: Lead's assigned officer (if any), unit managers
    """

    LEAD_IMPORTED = "lead_imported"
    """
    Triggered when leads are bulk-imported from a file.

    Payload Schema:
        {
            "total_imported": int,
            "sample_lead_ids": List[int],    # Max 10 IDs for reference
            "unit_id": int,
            "filename": str,
            "actor_id": int,
            "actor_name": str
        }

    Recipients: Unit managers (awareness of bulk operations)
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
    # NOTE: APPLICATION_* is a legacy notification namespace for AdmissionProfile.
    # The active domain entity is AdmissionProfile, not Application.
    # Do not reuse APPLICATION_CREATED for approval/enrollment — use APPLICATION_STATUS_CHANGED.
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

    APPLICATION_FEE_PAID = "application_fee_paid"
    """
    Triggered when the application fee is confirmed paid (gateway
    callback or manual admin confirmation).

    Payload Schema:
        {
            "application_id": int,         # Required: AdmissionProfile ID
            "lead_id": int,                # Required: Lead ID
            "officer_id": Optional[int],   # Assigned officer (may be null)
            "amount": str,                 # Fee amount as string (Decimal-safe)
            "transaction_id": Optional[str], # Payment transaction reference
            "actor_id": int,               # User who recorded the payment (0 for system)
            "actor_name": Optional[str],   # Actor display name
        }

    Recipients: Assigned officer (lead_owner), unit managers, admins.
    """

    APPLICATION_SURVEY_DUE = "application_survey_due"
    """
    Triggered by the daily admission survey scheduler 30 days after profile
    approval. Sends ZNS template 426903 ("Khảo sát dịch vụ tư vấn") to the
    applicant via lead_contact resolver. One-shot per profile — scheduler
    guards with ``survey_sent_at IS NULL`` so re-approval does not re-fire.

    Payload Schema:
        {
            "application_id": int,         # Required: AdmissionProfile ID
            "lead_id": int,                # Required: Lead ID for phone resolver
            "full_name": str,              # Pre-resolved, ≤30 chars enforced by builder
            "program_name": str,           # offering.program.name, ≤30 chars
            "profile_code": str,           # profile.profile_code, ≤30 chars
            "submitted_date_vn": str,      # DD/MM/YYYY of profile.submitted_at
            "tracking_id": str,            # UUID, echoed back in user_feedback webhook
        }

    Recipients: Applicant only (external channel). No internal recipients
    — this is a customer-facing survey, not an officer notification.
    """

    APPLICATION_MINOR_CORRECTED = "application_minor_corrected"
    """
    Triggered when officer/manager/admin applies a post-approval minor
    correction to an AdmissionProfile in approved/confirmed state. The
    flow only allows a strict allowlist of low-risk demographic +
    address fields (configured per AdmissionPath); document, finance,
    and identity fields are hard-denied. See
    ``app/core/admission_correction_constants.py`` for the safe catalog.

    Payload Schema:
        {
            "application_id": int,         # AdmissionProfile.id
            "lead_id": int,                # Lead.id (room scoping key)
            "changed_fields": List[str],   # KEY NAMES ONLY — no values, no PII
            "actor_id": int,               # User.id who applied the correction
            "corrected_at": str,           # ISO 8601 UTC timestamp
        }

    Recipients: broadcast-only (socket). No DB notification rule, no
    seed default — purely a realtime cache-invalidation signal so other
    sessions viewing the profile refresh. Privacy: payload carries
    field NAMES only; old/new values stay in the audit log behind RBAC.
    Rooms scope = role_admin + unit_<lead.unit_id> +
    user_room_<lead.assigned_officer_id> via ``rooms_for_admission``.
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
    Triggered when an invoice becomes overdue (PR 8 — invoice-level).

    Payload Schema:
        {
            "invoice_id": int,            # Required: the overdue invoice
            "invoice_number": str,        # Invoice display number
            "fee_id": int,                # Parent fee
            "fee_type": str,              # tuition, application, etc.
            "semester_no": int | None,    # Semester context (tuition only)
            "amount": str,                # Invoice remaining amount (Decimal as string)
            "due_date": str,              # ISO date of the due date
            "days_overdue": int,          # Days past due
            "installment_no": int,        # Installment sequence number
            "admission_profile_id": int,  # Profile linked to fee
            "lead_id": int,               # Lead linked to profile
            "unit_id": int,               # Unit for scoping
            "user_id": int                # Recipient (officer)
        }

    Recipients: Assigned officer, finance staff
    """

    PAYMENT_VERIFIED = "payment_verified"
    """
    Triggered when a payment is verified (funds confirmed by checker).

    Bridged from finance domain event PaymentVerified.
    This is the confirmed payment event used for external ZNS notifications.
    PAYMENT_RECEIVED is for recording only; external Zalo must use this event.

    Payload Schema:
        {
            "payment_id": int,            # Required: ID of the verified payment
            "invoice_id": int,            # Required: ID of the invoice
            "fee_id": int,                # Required: ID of the fee
            "amount": str,                # Payment amount (Decimal as string)
            "verified_by_id": int,        # Required: User who verified the payment
            "verified_at": str,           # ISO timestamp of verification
            "admission_profile_id": int,  # Required: Admission profile linked to fee
            "lead_id": int,               # Required: Lead linked to admission profile
            "unit_id": int                # Required: Unit for scoping
        }

    Recipients: Finance staff, the applicant (external via Zalo ZNS phase 1)
    """

    PAYMENT_REJECTED = "payment_rejected"
    """
    Triggered when a checker rejects a pending payment.

    Payload Schema:
        {
            "payment_id": int,            # Required: ID of the rejected payment
            "invoice_id": int,            # Required: ID of the invoice
            "fee_id": int,                # Required: ID of the fee
            "amount": str,                # Payment amount (Decimal as string)
            "rejection_reason": str,      # Required: Why the payment was rejected
            "rejected_by_id": int,        # Required: Checker who rejected
            "created_by_id": int,         # Required: Maker who recorded the payment
            "admission_profile_id": int,  # Admission profile linked to fee
            "lead_id": int,               # Lead linked to admission profile
            "unit_id": int,               # Unit for scoping
            "user_id": int                # Recipient (== created_by_id) for SpecificUsersResolver
        }

    Recipients: The maker (created_by_id) who recorded the payment
    """

    REFUND_PROCESSED = "refund_processed"
    """
    Triggered when an approved refund is processed (funds returned).

    Payload Schema:
        {
            "refund_id": int,             # Required: ID of the refund request
            "payment_id": int,            # Required: Original payment being refunded
            "invoice_id": int,            # Required: Invoice affected
            "fee_id": int,                # Required: Fee affected
            "amount": str,                # Refund amount (Decimal as string)
            "reason": str,                # Refund reason
            "processor_id": int,          # User who processed the refund
            "admission_profile_id": int,  # Admission profile linked to fee
            "lead_id": int,               # Lead linked to admission profile
            "unit_id": int,               # Unit for scoping
            "user_ids": list[int]         # Resolved recipients (officer + processor)
        }

    Recipients: Assigned officer, processor (internal only — PR A scope).
    Finance staff group deferred to PR B (needs dedicated resolver/action group).
    External applicant notification deferred to Zalo ZNS Phase 2.

    Status: DORMANT as of PR A. The dispatch site lives in
    payment_service.process_approved_refund(), but RefundService has no
    router endpoint — the request/approve/process flow is service-layer
    only. Catalog tags this event notification_class="internal_future"
    until the refund router ships. No live API path can fire this event
    today.
    """

    FEE_CALCULATED = "fee_calculated"
    """
    Triggered after ``POST /api/fees/calculate`` successfully creates the
    official Fee record and its invoice schedule (PR #8).

    Realtime-only: the admission detail + finance dashboards refresh
    immediately so officers/managers don't have to reload after
    calculating fees. Not a user-visible notification — no DB rule seed.

    Payload Schema:
        {
            "admission_profile_id": int,      # Required
            "lead_id": int,                   # Required — FE invalidates lead pipeline when stage changed
            "fee_id": int,                    # Required
            "fee_status": str,                # Fee.status at creation time
            "lead_stage_changed": bool,       # Pre-computed in the service closure;
                                              # tells FE whether to invalidate lead/pipeline caches
            "actor_id": int                   # The user that ran the calculation
        }

    Recipients: scoped via ``rooms_for_admission(profile)`` — admin
    role + lead unit + assigned officer. No notification-channel fanout.
    """

    FEE_FULLY_PAID = "fee_fully_paid"
    """
    Triggered when a semester fee is fully paid (remaining_amount <= 0).

    Distinct from PAYMENT_VERIFIED (which fires on every payment verification).
    FEE_FULLY_PAID fires once when the fee reaches zero balance.

    Payload Schema:
        {
            "fee_id": int,
            "amount": str,                # Total fee amount (Decimal as string)
            "semester_no": int | None,    # Semester context
            "admission_profile_id": int,
            "lead_id": int,
            "unit_id": int,
            "user_id": int                # Recipient (officer)
        }

    Recipients: Assigned officer
    """

    INVOICE_ISSUED = "invoice_issued"
    """
    Triggered when an invoice transitions to issued status.

    Payload Schema:
        {
            "invoice_id": int,
            "invoice_number": str,
            "fee_id": int,
            "amount": str,                # Invoice amount (Decimal as string)
            "due_date": str | None,       # ISO date
            "admission_profile_id": int,
            "lead_id": int,
            "unit_id": int,
            "user_id": int                # Recipient (officer)
        }

    Recipients: Assigned officer
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

    NOTIFICATION_HEALTH_ALERT = "notification_health_alert"
    """
    Operational health alert for the notification delivery subsystem.

    Admin-only operational signal raised by the Celery beat task
    ``check_notification_alerts`` (``app/tasks/delivery_tasks.py``). Kept
    SEPARATE from ``SYSTEM_ALERT`` so the health task never fans out to the
    full ``all_users`` broadcast audience (which previously flooded every
    staff inbox + dead-lettered zalo_bot deliveries and self-fed the
    failure-rate loop). Dispatched to ``all_admins`` over browser + email
    only — never zalo_bot.

    Payload Schema:
        {
            "severity": str,              # Required: "info" | "warning" | "error"
            "message": str,               # Required: Alert message
            "alert_type": str,            # e.g. "failure_rate_high", "breaker_open"
        }

    Recipients: Admin users only (operators who action pipeline health).
    """

    HOLIDAY_CALENDAR_INCOMPLETE = "holiday_calendar_incomplete"
    """
    Holiday calendar missing lunar holidays for next year.

    Payload Schema:
        {
            "severity": str,      # "warning"
            "message": str,       # Warning message
            "action_url": str,    # Link to holiday management
            "year": int,          # The incomplete year
        }

    Recipients: Admin users only
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

    USER_PROFILE_UPDATED = "user_profile_updated"
    """
    Triggered when an admin updates a user's profile.

    Payload Schema:
        {
            "user_id": int,               # Required: ID of the affected user
            "updated_fields": str,        # Comma-separated list of changed fields
            "actor_id": int               # Admin who made the change
        }

    Recipients: The affected user (via specific_users resolver)
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

    # =========================================================================
    # ORGANIZATION EVENTS
    # =========================================================================

    UNIT_CREATED = "unit_created"
    """
    Triggered when a new organization unit is created.

    Payload Schema:
        {
            "unit_id": int,               # Required: ID of the new unit
            "unit_name": str,             # Required: Name of the unit
            "unit_type": str,             # Type: "Trường", "Phòng", "Khoa", etc.
            "parent_id": Optional[int],   # Parent unit ID (if any)
            "actor_id": int               # Admin who created the unit
        }

    Recipients: All admins
    """

    UNIT_UPDATED = "unit_updated"
    """
    Triggered when an organization unit is updated.

    Payload Schema:
        {
            "unit_id": int,               # Required: ID of the unit
            "unit_name": str,             # Required: Name of the unit
            "updated_fields": List[str],  # List of field names that were updated
            "actor_id": int               # Admin who updated the unit
        }

    Recipients: All admins, managers of the unit
    """

    UNIT_DELETED = "unit_deleted"
    """
    Triggered when an organization unit is deleted (soft delete).

    Payload Schema:
        {
            "unit_id": int,               # Required: ID of the deleted unit
            "unit_name": str,             # Required: Name of the unit
            "actor_id": int               # Admin who deleted the unit
        }

    Recipients: All admins
    """

    PROGRAM_CREATED = "program_created"
    """
    Triggered when a new major program is created.

    Payload Schema:
        {
            "program_id": int,            # Required: ID of the program
            "program_name": str,          # Required: Name of the program
            "program_code": Optional[str],# Program code
            "degree_level": str,          # Degree level
            "actor_id": int               # Admin who created the program
        }

    Recipients: All admins
    """

    PROGRAM_UPDATED = "program_updated"
    """
    Triggered when a major program is updated.

    Payload Schema:
        {
            "program_id": int,            # Required: ID of the program
            "program_name": str,          # Required: Name of the program
            "updated_fields": List[str],  # List of field names that were updated
            "actor_id": int               # Admin who updated the program
        }

    Recipients: All admins
    """

    PROGRAM_DELETED = "program_deleted"
    """
    Triggered when a major program is deleted (soft delete).

    Payload Schema:
        {
            "program_id": int,            # Required: ID of the program
            "program_name": str,          # Required: Name of the program
            "actor_id": int               # Admin who deleted the program
        }

    Recipients: All admins
    """

    OFFERING_CREATED = "offering_created"
    """
    Triggered when a new program offering is created.

    Payload Schema:
        {
            "offering_id": int,           # Required: ID of the offering
            "program_id": int,            # Required: Parent program ID
            "program_name": str,          # Parent program name
            "offering_type": str,         # Offering type
            "actor_id": int               # Admin who created the offering
        }

    Recipients: All admins
    """

    OFFERING_UPDATED = "offering_updated"
    """
    Triggered when a program offering is updated.

    Payload Schema:
        {
            "offering_id": int,           # Required: ID of the offering
            "program_id": int,            # Required: Parent program ID
            "updated_fields": List[str],  # List of field names that were updated
            "actor_id": int               # Admin who updated the offering
        }

    Recipients: All admins
    """

    OFFERING_DELETED = "offering_deleted"
    """
    Triggered when a program offering is deleted (soft delete).

    Payload Schema:
        {
            "offering_id": int,           # Required: ID of the offering
            "program_id": int,            # Required: Parent program ID
            "offering_type": str,         # Offering type
            \"actor_id\": int               # Admin who deleted the offering
        }

    Recipients: All admins
    """

    # =========================================================================
    # CTV (COLLABORATOR) EVENTS
    # =========================================================================

    CTV_CLAIM_SUBMITTED = "ctv_claim_submitted"
    """
    Triggered when a CTV submits a new lead claim.

    Payload Schema:
        {
            "collaborator_id": int,
            "claim_id": int,
            "lead_id": int,
            "unit_id": int,
            "collaborator_name": str,
            "lead_name": str,
            "actor_id": int
        }

    Recipients: Unit managers (for review)
    """

    CTV_CLAIM_APPROVED = "ctv_claim_approved"
    """
    Triggered when a lead claim is approved.

    Payload Schema:
        {
            "collaborator_id": int,
            "claim_id": int,
            "lead_id": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_CLAIM_REJECTED = "ctv_claim_rejected"
    """
    Triggered when a lead claim is rejected.

    Payload Schema:
        {
            "collaborator_id": int,
            "claim_id": int,
            "lead_id": int,
            "rejection_reason": Optional[str],
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_APPROVED = "ctv_approved"
    """
    Triggered when a collaborator account is approved.

    Payload Schema:
        {
            "collaborator_id": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_SUSPENDED = "ctv_suspended"
    """
    Triggered when a collaborator account is suspended.

    Payload Schema:
        {
            "collaborator_id": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_LEAD_CONVERTED = "ctv_lead_converted"
    """
    Triggered when a CTV-referred lead progresses to a new status.

    Payload Schema:
        {
            "collaborator_id": int,
            "lead_id": int,
            "new_status": str,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_ATTRIBUTION_EXPIRING = "ctv_attribution_expiring"
    """
    Triggered when a CTV's lead attribution is about to expire (7 days warning).

    Payload Schema:
        {
            "collaborator_id": int,
            "lead_id": int,
            "days_remaining": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_ATTRIBUTION_EXPIRED = "ctv_attribution_expired"
    """
    Triggered when a CTV's lead attribution has expired.

    Payload Schema:
        {
            "collaborator_id": int,
            "lead_id": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_COMMISSION_CREATED = "ctv_commission_created"
    """
    Triggered when a commission record is created for a CTV.

    Payload Schema:
        {
            "collaborator_id": int,
            "commission_id": int,
            "amount": str,
            "lead_id": int,
            "user_id": int,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    CTV_WEEKLY_SUMMARY = "ctv_weekly_summary"
    """
    Triggered weekly with summary stats for each CTV.

    Payload Schema:
        {
            "collaborator_id": int,
            "user_id": int,
            "stats": dict,
            "actor_id": int
        }

    Recipients: The collaborator (via user_id)
    """

    # =========================================================================
    # SECURITY EVENTS
    # =========================================================================

    SUSPICIOUS_LOGIN = "suspicious_login"
    """
    Triggered when a login is flagged as suspicious (new IP, device, or location).

    Payload Schema:
        {
            "user_id": int,               # Required: ID of the user who logged in
            "login_history_id": int,      # Required: ID of the login history record
            "ip_address": str,            # IP address used for login
            "location": str,              # Location (city, country)
            "device": str,                # Device/browser info
            "risk_score": int,            # Risk score (0-100)
            "anomalies": List[str],       # List of anomalies detected (new_ip, new_device, new_location)
            "actor_id": int               # Same as user_id (self-login)
        }

    Recipients: The user who logged in (for awareness)
    """

    ZALO_BOT_LINK_DISPLACED = "zalo_bot_link_displaced"
    """
    Triggered when an existing active Zalo Bot link is taken over by another
    user. Happens in ``zalo_bot_link_service.verify_and_link`` when the
    incoming chat_id was previously bound to a different staff user — the
    old binding is marked inactive (and ``zalo_bot_enabled`` flipped off)
    so the new link can be enforced by the partial unique index. The
    displaced user receives this event as a security awareness signal.

    Payload Schema:
        {
            "user_id": int,               # Required: displaced user (recipient)
            "displaced_by_user_id": int,  # Required: new linker (actor)
            "chat_id_prefix": str,        # First 4 + last 2 chars of chat_id
            "actor_id": int               # Same as displaced_by_user_id
        }

    Recipients: The displaced user (resolver = specific_users on user_id).
    """

    # =============================================================================
    # ADM-023 / ADM-028 — Magic-link hardening (2026-04-29)
    # =============================================================================

    ADMISSION_CONFIRMATION_REMINDER_24H = "admission_confirmation_reminder_24h"
    """
    Triggered by the magic-link reminder beat task ~24h before the token
    ``expires_at`` for an unconfirmed approved profile. One-shot per
    token: ``reminder_24h_sent_at`` is stamped in the same transaction
    as the dispatch so re-runs don't double-fire even if beat overlaps
    or the worker retries.

    Payload Schema:
        {
            "application_id": int,    # Required: AdmissionProfile ID
            "lead_id": int,           # Required: Lead ID for contact resolver
            "lead_name": str,         # Display name
            "expires_at_iso": str,    # ISO datetime — token expiry
            "hours_remaining": int,   # ~24, computed at fire time
            "confirm_url": str,       # Direct magic-link URL
        }

    Recipients: Applicant (email + Zalo). No internal fanout.
    """

    ADMISSION_CONFIRMATION_REMINDER_6H = "admission_confirmation_reminder_6h"
    """
    Final reminder ~6h before token expiry. Same beat task, same dedupe
    pattern as the 24h reminder via ``reminder_6h_sent_at``. Firing the
    6h reminder does NOT depend on the 24h reminder having fired —
    legitimate token may have crossed both windows already at task
    start (e.g. issued <6h before expiry on a manual resend).

    Payload Schema: same as ``ADMISSION_CONFIRMATION_REMINDER_24H`` but
    ``hours_remaining`` ≈ 6.

    Recipients: Applicant (email + Zalo). No internal fanout.
    """

    ADMISSION_CONFIRMATION_HARD_LOCKED = "admission_confirmation_hard_locked"
    """
    Triggered when an applicant's magic-link token crosses the
    ≥30-failed-attempts hard-lock threshold (``locked_at`` set,
    ``lock_count`` incremented). Internal-only — the applicant already
    saw a "link locked" message at the API; this event is the operator
    awareness signal so support can proactively reach out and unlock
    if appropriate.

    Payload Schema:
        {
            "application_id": int,        # Required: AdmissionProfile ID
            "token_id": int,              # Required: AdmissionConfirmationToken ID
            "attempt_count": int,         # Total failed attempts
            "lock_count": int,            # How many times this token has been hard-locked
            "locked_at_iso": str,         # When the hard lock fired
            "lead_id": int,               # Lead ID for context
            "lead_name": str,             # Display name
        }

    Recipients: Assigned officer + unit managers + admins.
    """

    # =========================================================================
    # ADMISSION 12 milestone events (B2.1) — admission cold-cutover refactor.
    # See `Documents/ADMISSION_REFACTOR_PLAN.md` §3.3.d table line 1644-1657.
    # 7 of the 12 (RESULT_PUBLISHED / DECISION_ADMITTED / DECISION_WAITLISTED
    # / DECISION_REJECTED / WAITLIST_PROMOTED / ENROLLED / ROLLED_BACK) carry
    # `requires_outbox=True` in EVENT_CATALOG — workflow guarantee delivery.
    # 5 of the 12 (RESULT_PUBLISHED / DECISION_ADMITTED / DECISION_WAITLISTED
    # / DECISION_REJECTED / ENROLLED) carry `bypass_consent_check=True` for
    # in-app + email channels per Quy chế Bộ GD&ĐT. Zalo/SMS bypass remains
    # FUTURE-GATED — the `zalo_template_approved` legal flag from Q7 chốt
    # 2026-05-01 does not exist in the codebase yet; B2.3 / B2.4 must either
    # honor consent for Zalo/SMS until that flag ships or wire the flag at
    # that time.
    # `APPLICATION_*` legacy namespace stays — see `notification_dispatcher`
    # for backward-compat dispatch pattern.
    # =========================================================================

    ADMISSION_PROFILE_SUBMITTED = "admission_profile_submitted"
    """T1 candidate submit. Audience: officer + candidate. requires_outbox=False."""

    ADMISSION_REVISION_REQUESTED = "admission_revision_requested"
    """T3, T4 officer asks revision. Audience: candidate. requires_outbox=False."""

    ADMISSION_RESUBMITTED = "admission_resubmitted"
    """T5 candidate resubmit after revision. Audience: officer. requires_outbox=False."""

    ADMISSION_RESULT_PUBLISHED = "admission_result_published"
    """T6 admin publishes admission result. Audience: officer + candidate.
    requires_outbox=True, bypass_consent_check=True (in-app + email)."""

    ADMISSION_DECISION_ADMITTED = "admission_decision_admitted"
    """T7 system marks profile admitted. Audience: candidate.
    requires_outbox=True, bypass_consent_check=True (in-app + email)."""

    ADMISSION_DECISION_WAITLISTED = "admission_decision_waitlisted"
    """T8 system marks profile waitlisted. Audience: candidate.
    requires_outbox=True, bypass_consent_check=True (in-app + email)."""

    ADMISSION_DECISION_REJECTED = "admission_decision_rejected"
    """T9 system marks profile rejected. Audience: candidate.
    requires_outbox=True, bypass_consent_check=True (in-app + email)."""

    ADMISSION_WAITLIST_PROMOTED = "admission_waitlist_promoted"
    """T10 admin promotes waitlist → admitted. Audience: candidate.
    requires_outbox=True, bypass_consent_check=False."""

    ADMISSION_WAITLIST_REJECTED = "admission_waitlist_rejected"
    """T11 admin finalizes waitlist → rejected (Wave 5 ship 2026-05-16).
    Source-aware: distinct từ ADMISSION_DECISION_REJECTED (engine cascade
    T9). Manager/admin manually reject 1 waitlisted choice khi đợt closes
    + slot không mở. Audience: candidate. requires_outbox=True."""

    ADMISSION_CONFIRMED = "admission_confirmed"
    """T12 candidate / officer / admin confirms admission. Audience: officer.
    requires_outbox=False. Distinct from ADMISSION_CONFIRMATION_REMINDER_*
    (those are reminder events; this fires when the confirm action lands)."""

    ADMISSION_ENROLLED = "admission_enrolled"
    """T13 system enrolls confirmed profile. Audience: officer + candidate.
    requires_outbox=True, bypass_consent_check=True (in-app + email)."""

    ADMISSION_WITHDRAWN = "admission_withdrawn"
    """T14, T15, T16 candidate / admin withdraws. Audience: officer.
    requires_outbox=False."""

    ADMISSION_ROLLED_BACK = "admission_rolled_back"
    """T17 admin override rollback. Audience: officer + candidate.
    requires_outbox=True, bypass_consent_check=False."""

    # =========================================================================
    # Q9 #07 PHASE E — PRIORITY BONUS OVERRIDE EVENTS (TT 05/2021/TT-BLĐTBXH)
    # =========================================================================

    PRIORITY_KV_OVERRIDDEN = "priority_kv_overridden"
    """Officer/admin manually overrides candidate's KV (khu vực ưu tiên).

    Triggered by `priority_override_service.override_kv()` (Phase E.2) when
    candidate flows hit M1 ambiguous tiebreak, lớp tạo nguồn, quân nhân MAX KV,
    hoặc admin post-T6 correction.

    Payload Schema:
        {
            "application_id": int,      # Required: AdmissionProfile.id (legacy alias)
            "lead_id": int,             # Required: profile.lead_id for routing
            "actor_id": int,            # Required: user.id of officer/admin
            "actor_name": str,          # Required: full_name for notification body
            "kv_resolved": str,         # Required: 'KV1' | 'KV2-NT' | 'KV2' | 'KV3'
            "override_reason": str,     # Required: min 20 chars rationale
            "evidence_file_id": Optional[int]  # Document FK if attached
        }

    Recipients: lead_owner (candidate). bypass_consent_check=False
    (legitimate state change notification, candidate đã consent khi nộp hồ sơ).
    """

    PRIORITY_OBJECT_VERIFIED = "priority_object_verified"
    """Officer verifies a candidate's UT (đối tượng ưu tiên) evidence.

    Triggered by `priority_override_service.verify_object_evidence()` (Phase E.3)
    after officer reviews uploaded document for sub_code (vd UT04 DTTS, UT06 mồ côi).

    Payload Schema:
        {
            "application_id": int,      # Required: AdmissionProfile.id
            "lead_id": int,             # Required: profile.lead_id
            "actor_id": int,            # Required: officer user.id
            "actor_name": str,          # Required: officer full_name
            "sub_code": str,            # Required: UT sub_code (vd '04', '06')
            "document_id": Optional[int]  # Verified document FK
        }

    Recipients: lead_owner. Candidate sees positive confirmation that bonus
    will count in T6 engine cascade.
    """

    PRIORITY_OBJECT_REJECTED = "priority_object_rejected"
    """Officer rejects a candidate's UT evidence — candidate must resupply.

    Triggered by `priority_override_service.reject_object_evidence()` (Phase E.3)
    when uploaded document fails verification (wrong document, expired, etc.).

    Payload Schema:
        {
            "application_id": int,      # Required: AdmissionProfile.id
            "lead_id": int,             # Required: profile.lead_id
            "actor_id": int,            # Required: officer user.id
            "actor_name": str,          # Required: officer full_name
            "sub_code": str,            # Required: UT sub_code
            "reject_reason": str        # Required: min 10 chars (template displays to candidate)
        }

    Recipients: lead_owner. Zalo channel included for urgency (candidate must
    re-upload). bypass_consent_check=False — consent inherited from submit flow.
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
        log.debug("Event handler registered", event_name=event_name, handler=handler.__name__)

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
        log.info("Dispatching event", event_name=event_name, handler_count=len(self._handlers[event_name]))

        for handler in self._handlers[event_name]:
            try:
                await handler(**data)
                log.debug("Event handler succeeded", event_name=event_name, handler=handler.__name__)
            except Exception as e:
                # Log error but continue dispatching to other handlers
                log.error(
                    "Event handler failed",
                    event_name=event_name,
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

