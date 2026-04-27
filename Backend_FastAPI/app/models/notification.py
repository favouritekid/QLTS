# app/models/notification.py
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base



class Notification(Base):
    """
    Model for user notifications.
    Supports real-time notifications via WebSocket.
    """

    __tablename__ = "notification"

    id = Column(Integer, primary_key=True, index=True)

    # User who receives the notification
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)

    # Notification type: info, success, warning, error, admin_update, system
    type = Column(String(50), nullable=False, default="info", index=True)

    # Title of notification
    title = Column(String(255), nullable=False)

    # Message content
    message = Column(Text, nullable=False)

    # Optional link to navigate to
    link = Column(String(512), nullable=True)

    # Additional data in JSON format
    data = Column(JSON, nullable=True)

    # Read status
    is_read = Column(Boolean, nullable=False, default=False, index=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    # ✅ TASK 6.1: Updated to use back_populates (explicit bidirectional relationship)
    user = relationship("User", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification {self.id}: {self.title} for user {self.user_id}>"


class NotificationRule(Base):
    """
    ✅ PHASE 2.1: Model for notification rules (visual management).

    Allows administrators to manage notification configurations through UI
    instead of hardcoding them in the registry.

    Fields:
        event: SystemEvents enum value (e.g., "LEAD_ASSIGNED")
        title_template: Template string with {placeholders} (e.g., "Lead assigned: {lead_name}")
        message_template: Message template with {placeholders}
        notification_type: Severity level (info, success, warning, error)
        link_template: Optional link template (e.g., "/leads/{lead_id}")
        channels: JSON array of delivery channels ["browser", "email", "sms"]
        recipient_config: JSON object defining resolver {resolver_type, params}
        condition: Optional JSON object for activation conditions
        enabled: Whether this rule is active

    Example recipient_config:
        {
            "resolver_type": "specific_user",
            "params": {"user_field": "officer_id"}
        }
        {
            "resolver_type": "all_users",
            "params": {"exclude_actor": true}
        }
    """

    __tablename__ = "notification_rule"

    id = Column(Integer, primary_key=True, index=True)

    # Event trigger (from SystemEvents enum)
    event = Column(String(100), nullable=False, index=True,
                   comment="SystemEvents enum value (e.g., LEAD_ASSIGNED)")

    # Notification content templates
    title_template = Column(String(255), nullable=False,
                           comment="Title template with {placeholders}")
    message_template = Column(Text, nullable=False,
                             comment="Message template with {placeholders}")
    notification_type = Column(String(20), nullable=False, default="info",
                              comment="Severity: info, success, warning, error")
    link_template = Column(String(512), nullable=True,
                          comment="Optional link template (e.g., /leads/{lead_id})")

    # Phase C1 deprecated `channels` column was dropped in Wave 4b
    # (migration 2297e303be04). Runtime truth lives in
    # `NotificationAction` rows (see the `actions` relationship below).

    # Recipient resolution configuration
    recipient_config = Column(JSON, nullable=False,
                             comment="Resolver config: {resolver_type, params}")

    # Optional activation conditions.
    # `none_as_null=True` makes SQLAlchemy persist Python `None` as SQL NULL
    # instead of the JSON literal `'null'`, so `WHERE condition IS NULL`
    # filters and indexes work correctly. Audit on 2026-04-27 found 48/49
    # rows had the JSON literal — backfilled by migration to SQL NULL.
    condition = Column(JSON(none_as_null=True), nullable=True,
                      comment="Optional activation conditions")

    # Enable/disable flag
    enabled = Column(Boolean, nullable=False, default=True, index=True,
                    comment="Enable/disable this rule")

    # ✅ PHASE 3.1: Optional reference to reusable template
    template_id = Column(Integer, ForeignKey("notification_template.id", ondelete="SET NULL"),
                        nullable=True, index=True,
                        comment="Optional reference to reusable template")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                       onupdate=func.now(), nullable=False)

    # Relationships
    template = relationship("NotificationTemplate", foreign_keys=[template_id])
    actions = relationship("NotificationAction", back_populates="rule",
                          cascade="all, delete-orphan",
                          order_by="NotificationAction.step")

    def __repr__(self) -> str:
        return f"<NotificationRule {self.id}: {self.event} ({self.notification_type})>"


class NotificationTemplate(Base):
    """
    ✅ NOTIFICATION 2.0 - PHASE 1: Refactored notification templates with metadata.

    Enhanced model for reusable notification templates that supports:
        - Template code-based referencing (instead of ID)
        - Multi-channel support filtering
        - Event-based template filtering
        - Template type classification

    Fields:
        name: Human-readable template name
        template_code: Unique code identifier (e.g., "TPL_LEAD_ASSIGN", "ZNS_LICHHEN")
        description: Human-readable description for admins
        title_template: Template string with {placeholders}
        message_template: Message template with {placeholders}
        link_template: Optional link template
        variables: JSON array of available variables (e.g., ["lead_name", "officer_id"])
        category: Template category (e.g., "lead", "consultation", "application")

        # NEW FIELDS (NOTIFICATION 2.0):
        supported_channels: JSON array of channels this template works with (["socket", "email", "zalo"])
        allowed_events: JSON array of events this template is designed for (null = all events)
        template_type: Template type classification ("system", "zalo_zns", "email_html", "sms")

        is_system: System template flag (cannot be deleted by users)
        usage_count: Number of notification rules using this template
        created_by: User ID who created this template

    Example:
        {
            "name": "Lead Assignment Notification",
            "template_code": "TPL_LEAD_ASSIGN",
            "title_template": "Lead assigned: {lead_name}",
            "message_template": "You have been assigned to lead {lead_name} (Phone: {lead_phone})",
            "link_template": "/leads/{lead_id}",
            "variables": ["lead_name", "lead_phone", "lead_id"],
            "category": "lead",
            "supported_channels": ["socket", "email"],
            "allowed_events": ["LEAD_ASSIGNED", "LEAD_REASSIGNED"],
            "template_type": "system"
        }
    """

    __tablename__ = "notification_template"

    id = Column(Integer, primary_key=True, index=True)

    # Template identification
    name = Column(String(100), nullable=False, unique=True, index=True,
                  comment="Template name (human-readable)")
    template_code = Column(String(100), nullable=False, unique=True, index=True,
                          comment="Template code (unique identifier for referencing)")
    description = Column(Text, nullable=True,
                        comment="Template description for admins")

    # Template content
    title_template = Column(String(255), nullable=False,
                           comment="Title template with {placeholders}")
    message_template = Column(Text, nullable=False,
                             comment="Message template with {placeholders}")
    link_template = Column(String(512), nullable=True,
                          comment="Optional link template")

    # Template metadata
    variables = Column(JSON, nullable=True,
                      comment="List of available variables for this template")
    category = Column(String(50), nullable=True, index=True,
                     comment="Template category (e.g., 'lead', 'consultation')")

    # NEW: NOTIFICATION 2.0 - Channel and Event filtering (JSONB for efficient queries)
    supported_channels = Column(JSONB, nullable=False, default=["browser"],
                               comment='Channels this template supports (["browser", "email", "zalo", "sms"])')
    allowed_events = Column(JSONB, nullable=True,
                           comment='Events this template is designed for (null = all events)')

    template_type = Column(String(50), nullable=False, default="system",
                          comment='Template type: system, zalo_zns, email_html, sms')

    # System and usage tracking
    is_system = Column(Boolean, nullable=False, default=False, server_default="false", index=True,
                      comment="System template (cannot be deleted)")
    usage_count = Column(Integer, nullable=False, default=0, server_default="0",
                        comment="Number of rules using this template")

    # Audit fields
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"),
                       nullable=True, index=True, comment="User ID who created this template")  # ✅ FIX: Added index
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                       onupdate=func.now(), nullable=False)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<NotificationTemplate {self.id}: {self.name} ({self.category})>"


class NotificationAction(Base):
    """
    ✅ NOTIFICATION 2.0 - PHASE 1: Model for notification workflow actions.

    Represents individual steps in a multi-step notification workflow.
    Each NotificationRule can have multiple actions that execute sequentially,
    supporting different channels and optional delays.

    Fields:
        rule_id: Foreign key to NotificationRule (cascade delete)
        step: Step number in the workflow (1, 2, 3...)
        channel: Delivery channel for this action ("browser", "email", "zalo", "sms")
        template_code: Optional reference to NotificationTemplate.template_code
        delay_minutes: Delay before executing this action (0 = immediate)
        config: Channel-specific configuration (JSON)

    Example workflow:
        Rule: LEAD_ASSIGNED
        Actions:
            [Step 1] Channel: socket, Template: TPL_LEAD_ASSIGN, Delay: 0 min
            [Step 2] Channel: email, Template: TPL_LEAD_ASSIGN_EMAIL, Delay: 15 min
            [Step 3] Channel: zalo, Template: ZNS_LICHHEN, Delay: 60 min

    Constraints:
        - Unique constraint on (rule_id, step) prevents duplicate steps
        - Cascade delete ensures actions are removed when rule is deleted
    """

    __tablename__ = "notification_action"

    id = Column(Integer, primary_key=True, index=True)

    # Reference to parent rule
    # NOTE: index is defined in __table_args__ as ix_notification_action_rule_id
    rule_id = Column(Integer, ForeignKey("notification_rule.id", ondelete="CASCADE"),
                    nullable=False,
                    comment="Foreign key to notification_rule")

    # Step number in workflow sequence
    step = Column(Integer, nullable=False, default=1,
                 comment="Step number in workflow (1, 2, 3...)")

    # Delivery channel
    channel = Column(String(50), nullable=False,
                    comment="Delivery channel: browser, email, zalo, sms")

    # Optional template reference (by code, not ID for flexibility)
    template_code = Column(String(100), nullable=True,
                          comment="Optional reference to NotificationTemplate.template_code")

    # Delay before execution
    delay_minutes = Column(Integer, nullable=False, default=0,
                          comment="Delay in minutes before executing this action (0 = immediate)")

    # Channel-specific configuration
    config = Column(JSON, nullable=True,
                   comment="Channel-specific configuration (e.g., Zalo template ID)")

    # Phase 3: Delivery branch fields
    recipient_config = Column(JSON, nullable=True,
        comment="Per-action recipient resolver config. Falls back to rule.recipient_config if null.")
    content_mode = Column(String(50), nullable=True,
        comment="Content source: inherit_default, template_override, inline_override, channel_native")
    content_override = Column(JSON, nullable=True,
        comment="Inline title/message/link override when content_mode=inline_override")
    branch_key = Column(String(100), nullable=True,
        comment="Human-readable branch identifier for debugging and UI round-trip")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                       nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                       onupdate=func.now(), nullable=False)

    # Table arguments: indexes and constraints
    __table_args__ = (
        Index('ix_notification_action_rule_id', 'rule_id'),
        Index('ix_notification_action_step', 'step'),
        UniqueConstraint('rule_id', 'step', name='uq_notification_action_rule_step'),
    )

    # Relationships
    rule = relationship("NotificationRule", back_populates="actions")

    def __repr__(self) -> str:
        return f"<NotificationAction {self.id}: Rule {self.rule_id} Step {self.step} ({self.channel})>"
