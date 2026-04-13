# app/core/event_metadata.py
"""
⚠️ DEPRECATED (PR1 — notification refactor)

This module is superseded by ``app.core.event_catalog`` which now provides
both display metadata AND technical config in a single ``EventDefinition``.

The metadata router now serves from ``event_catalog.get_notifiable_events()``
instead of ``get_all_events_metadata()``.

Kept temporarily for backward compatibility with any code that still
imports ``EventVariable``, ``ConditionField``, or ``EventMetadata``.

--- Original docstring ---
✅ NOTIFICATION 2.0 - PHASE 2: Event Metadata Registry

Derived contract defining metadata for admin UI and frontend rule builders.
NOT the runtime source of truth — dispatch() uses notification_registry.py and DB rules.
This registry drives the admin metadata API for dynamic form generation.

Backend defines:
    - Available variables for each event
    - Filter fields for conditional rules
    - Default channels for each event type
    - Event categorization

Frontend reads this metadata via API and becomes completely dynamic - no hardcoding needed.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.events import SystemEvents


@dataclass
class EventVariable:
    """
    Definition of a variable available in an event's payload.

    Example:
        EventVariable(
            name="lead_name",
            type="string",
            description="Full name of the lead",
            required=True
        )
    """
    name: str
    type: str  # "string", "integer", "boolean", "datetime", "float"
    description: str
    required: bool = True


@dataclass
class ConditionField:
    """
    Definition of a field available for rule conditions.

    Unlike EventVariable (template-visible flat payload fields),
    ConditionField uses nested paths evaluated against the condition context.
    """
    path: str       # "actor.role", "event.new_status_id", "lead.source"
    type: str       # "string", "integer", "boolean", "array", "datetime"
    description: str  # Vietnamese UI label
    operators: list   # ["eq", "ne", "in", "not_in", "contains"]


# Operator sets by type
_OPS_STRING = ["eq", "ne", "in", "not_in", "contains"]
_OPS_NUMERIC = ["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"]
_OPS_BOOLEAN = ["eq", "ne"]
_OPS_ARRAY = ["contains"]

# Common actor fields (most events have these)
_ACTOR_CONDITION_FIELDS = [
    ConditionField("actor.id", "integer", "ID người thực hiện", _OPS_NUMERIC),
    ConditionField("actor.name", "string", "Tên người thực hiện", _OPS_STRING),
    ConditionField("actor.role", "string", "Vai trò người thực hiện (VD: admin, manager, officer)", _OPS_STRING),
    ConditionField("actor.unit_id", "integer", "ID đơn vị của người thực hiện", _OPS_NUMERIC),
]

# Lead entity fields (events that have lead_id/lead_name/unit_id in payload)
_LEAD_ENTITY_CONDITION_FIELDS = [
    ConditionField("lead.id", "integer", "ID của lead", _OPS_NUMERIC),
    ConditionField("lead.name", "string", "Tên lead", _OPS_STRING),
    ConditionField("lead.source", "string", "Nguồn lead (VD: website, facebook)", _OPS_STRING),
    ConditionField("lead.consultation_status_id", "string", "Mã trạng thái tư vấn hiện tại (VD: new, contacted)", _OPS_STRING),
    ConditionField("lead.stage_id", "string", "Mã giai đoạn pipeline hiện tại (VD: NEW_LEAD, CONTACTED)", _OPS_STRING),
    ConditionField("lead.unit_id", "integer", "ID đơn vị của lead", _OPS_NUMERIC),
    ConditionField("lead.officer_id", "integer", "ID officer phụ trách lead", _OPS_NUMERIC),
]

# Consultation fields
_CONSULTATION_CONDITION_FIELDS = [
    ConditionField("consultation.id", "integer", "ID record tư vấn", _OPS_NUMERIC),
    ConditionField("consultation.status_id", "string", "Mã trạng thái tư vấn", _OPS_STRING),
]


@dataclass
class EventMetadata:
    """
    Complete metadata for a system event.

    This tells the frontend everything it needs to know about an event:
        - What variables are available for templates
        - What fields can be used in conditions
        - Default delivery channels
        - Categorization for organization
    """
    event: SystemEvents
    display_name: str
    description: str
    variables: List[EventVariable]
    filter_fields: List[str]
    default_channels: List[str] = field(default_factory=lambda: ["browser"])
    # NOTE: default_channels currently only includes "browser" and "email".
    # "zalo" and "sms" are planned/gated channels (see NotificationChannel in
    # event_groups.py). They are defined in the enum but default to False in
    # DEFAULT_GROUP_CHANNELS and are NOT listed in any event's default_channels
    # here until their delivery backends are production-ready.
    # See NOTIFICATION_PLAN_SPEC_ADDENDUM.md for the gating roadmap.
    category: str = "general"
    condition_fields: List[ConditionField] = field(default_factory=list)


# =============================================================================
# ✅ EVENT METADATA REGISTRY - 27 EVENTS DEFINED
#
# Channel inventory:
#   browser  — active, delivered via Socket.IO + DB row
#   email    — active, delivered via EmailService / Celery worker
#   zalo     — planned (ZNS Phase 1), gated behind feature flag, not in any
#              default_channels list below until delivery backend is live
#   sms      — planned (future), gated behind feature flag, not in any
#              default_channels list below until delivery backend is live
# =============================================================================

EVENT_METADATA_REGISTRY: Dict[SystemEvents, EventMetadata] = {

    # =========================================================================
    # LEAD EVENTS (6 events)
    # =========================================================================

    SystemEvents.LEAD_ASSIGNED: EventMetadata(
        event=SystemEvents.LEAD_ASSIGNED,
        display_name="Lead được phân công",
        description="Khi lead được assign cho officer",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer được assign"),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
            EventVariable("actor_name", "string", "Tên người thực hiện", required=False),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("lead_phone", "string", "SĐT lead", required=False),
            EventVariable("offering_name", "string", "Tên ngành/chương trình", required=False),
        ],
        filter_fields=["lead_id", "officer_id", "actor_id"],
        default_channels=["browser", "email"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS,
    ),

    SystemEvents.LEAD_ASSIGNMENT_FAILED: EventMetadata(
        event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
        display_name="Phân công lead thất bại",
        description="Khi hệ thống không thể tự động phân công lead",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("reason", "string", "Lý do thất bại"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
            EventVariable("actor_name", "string", "Tên người thực hiện", required=False),
        ],
        filter_fields=["lead_id", "unit_id", "reason"],
        default_channels=["browser", "email"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS,
    ),

    SystemEvents.LEAD_REASSIGNED: EventMetadata(
        event=SystemEvents.LEAD_REASSIGNED,
        display_name="Lead được chuyển giao",
        description="Khi lead được chuyển sang đơn vị/officer khác",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("old_officer_id", "integer", "ID officer cũ", required=False),
            EventVariable("new_officer_id", "integer", "ID officer mới", required=False),
            EventVariable("old_unit_id", "integer", "ID đơn vị cũ"),
            EventVariable("new_unit_id", "integer", "ID đơn vị mới"),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
            EventVariable("actor_name", "string", "Tên người thực hiện", required=False),
            EventVariable("reason", "string", "Lý do chuyển giao", required=False),
        ],
        filter_fields=["lead_id", "old_officer_id", "new_officer_id", "old_unit_id", "new_unit_id"],
        default_channels=["browser", "email"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS + [
            ConditionField("event.old_unit_id", "integer", "ID đơn vị cũ", _OPS_NUMERIC),
            ConditionField("event.new_unit_id", "integer", "ID đơn vị mới", _OPS_NUMERIC),
        ],
    ),

    SystemEvents.LEAD_STATUS_CHANGED: EventMetadata(
        event=SystemEvents.LEAD_STATUS_CHANGED,
        display_name="Trạng thái lead thay đổi",
        description="Khi lead chuyển sang giai đoạn khác trong pipeline",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("officer_id", "integer", "ID officer phụ trách", required=False),
            EventVariable("officer_name", "string", "Tên officer phụ trách", required=False),
            EventVariable("old_status", "string", "Trạng thái cũ"),
            EventVariable("new_status", "string", "Trạng thái mới"),
            EventVariable("old_stage", "integer", "ID giai đoạn pipeline cũ", required=False),
            EventVariable("new_stage", "integer", "ID giai đoạn pipeline mới", required=False),
            EventVariable("updated_fields", "array", "Danh sách trường đã thay đổi", required=False),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
            EventVariable("actor_name", "string", "Tên người thực hiện", required=False),
        ],
        filter_fields=["lead_id", "officer_id", "old_status", "new_status", "old_stage", "new_stage", "updated_fields"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS + [
            ConditionField("event.old_status_id", "string", "Mã trạng thái cũ", _OPS_STRING),
            ConditionField("event.new_status_id", "string", "Mã trạng thái mới", _OPS_STRING),
            ConditionField("event.old_stage_id", "string", "Mã giai đoạn pipeline cũ", _OPS_STRING),
            ConditionField("event.new_stage_id", "string", "Mã giai đoạn pipeline mới", _OPS_STRING),
            ConditionField("event.updated_fields", "array", "Danh sách trường đã thay đổi", _OPS_ARRAY),
        ],
    ),

    SystemEvents.LEAD_CREATED: EventMetadata(
        event=SystemEvents.LEAD_CREATED,
        display_name="Lead mới được tạo",
        description="Khi có lead mới trong hệ thống",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("unit_id", "integer", "ID đơn vị phụ trách"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("source", "string", "Nguồn lead", required=False),
            EventVariable("actor_id", "integer", "ID người tạo"),
            EventVariable("actor_name", "string", "Tên người tạo", required=False),
        ],
        filter_fields=["lead_id", "unit_id", "source"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS,
    ),

    SystemEvents.LEAD_UPDATED: EventMetadata(
        event=SystemEvents.LEAD_UPDATED,
        display_name="Lead được cập nhật",
        description="Khi lead được cập nhật thông tin",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("updated_fields", "array", "Danh sách trường đã thay đổi", required=False),
            EventVariable("status_changed", "boolean", "Có thay đổi trạng thái không", required=False),
            EventVariable("actor_id", "integer", "ID người cập nhật"),
            EventVariable("actor_name", "string", "Tên người cập nhật", required=False),
            EventVariable("updated_by", "string", "Tên người cập nhật (alias)", required=False),
            EventVariable("updated_summary", "string", "Tóm tắt trường đã thay đổi", required=False),
            EventVariable("updated_at", "datetime", "Thời điểm cập nhật (ISO)", required=False),
            EventVariable("message", "string", "Thông báo cập nhật", required=False),
        ],
        filter_fields=["lead_id", "status_changed"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + [
            ConditionField("lead.id", "integer", "ID của lead", _OPS_NUMERIC),
        ] + [
            ConditionField("event.status_changed", "boolean", "Có thay đổi trạng thái không", _OPS_BOOLEAN),
            ConditionField("event.updated_fields", "array", "Danh sách trường đã thay đổi", _OPS_ARRAY),
        ],
    ),

    SystemEvents.LEAD_DELETED: EventMetadata(
        event=SystemEvents.LEAD_DELETED,
        display_name="Lead bị xóa",
        description="Khi lead bị soft-delete khỏi hệ thống",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("officer_id", "integer", "ID officer đã phụ trách", required=False),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
            EventVariable("actor_name", "string", "Tên admin thực hiện", required=False),
        ],
        filter_fields=["lead_id", "unit_id", "officer_id"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS,
    ),

    SystemEvents.LEAD_RESTORED: EventMetadata(
        event=SystemEvents.LEAD_RESTORED,
        display_name="Lead được khôi phục",
        description="Khi lead bị xóa được khôi phục lại",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("officer_id", "integer", "ID officer phụ trách", required=False),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
            EventVariable("actor_name", "string", "Tên admin thực hiện"),
        ],
        filter_fields=["lead_id", "unit_id", "officer_id"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS,
    ),

    SystemEvents.LEAD_IMPORTED: EventMetadata(
        event=SystemEvents.LEAD_IMPORTED,
        display_name="Import lead hàng loạt",
        description="Khi lead được import từ file CSV/Excel",
        variables=[
            EventVariable("total_imported", "integer", "Số lead đã import"),
            EventVariable("sample_lead_ids", "array", "Danh sách ID mẫu (tối đa 10)", required=False),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("filename", "string", "Tên file import"),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
            EventVariable("actor_name", "string", "Tên người thực hiện"),
        ],
        filter_fields=["unit_id"],
        default_channels=["browser"],
        category="lead",
        condition_fields=_ACTOR_CONDITION_FIELDS + [
            ConditionField("event.unit_id", "integer", "ID đơn vị import", _OPS_NUMERIC),
            ConditionField("event.total_imported", "integer", "Số lead đã import", _OPS_NUMERIC),
            ConditionField("event.filename", "string", "Tên file import", _OPS_STRING),
        ],
    ),

    # =========================================================================
    # CONSULTATION EVENTS (4 events)
    # =========================================================================

    SystemEvents.CONSULTATION_CREATED: EventMetadata(
        event=SystemEvents.CONSULTATION_CREATED,
        display_name="Tư vấn mới được tạo",
        description="Khi có record tư vấn mới",
        variables=[
            EventVariable("consultation_id", "integer", "ID record tư vấn"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer tư vấn", required=False),
            EventVariable("status_id", "string", "Trạng thái tư vấn"),
            EventVariable("actor_id", "integer", "ID người tạo"),
            EventVariable("actor_name", "string", "Tên người tạo", required=False),
            EventVariable("unit_id", "integer", "ID đơn vị"),
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id", "status_id", "unit_id"],
        default_channels=["browser"],
        category="consultation",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS + _CONSULTATION_CONDITION_FIELDS,
    ),

    SystemEvents.CONSULTATION_UPDATED: EventMetadata(
        event=SystemEvents.CONSULTATION_UPDATED,
        display_name="Cập nhật tư vấn",
        description="Khi record tư vấn được cập nhật",
        variables=[
            EventVariable("consultation_id", "integer", "ID record tư vấn"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer phụ trách", required=False),
            EventVariable("old_status_id", "string", "Trạng thái cũ", required=False),
            EventVariable("new_status_id", "string", "Trạng thái mới"),
            EventVariable("actor_id", "integer", "ID người cập nhật"),
            EventVariable("actor_name", "string", "Tên người cập nhật", required=False),
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id", "new_status_id"],
        default_channels=["browser"],
        category="consultation",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS + _CONSULTATION_CONDITION_FIELDS + [
            ConditionField("event.old_status_id", "string", "Mã trạng thái tư vấn cũ", _OPS_STRING),
            ConditionField("event.new_status_id", "string", "Mã trạng thái tư vấn mới", _OPS_STRING),
        ],
    ),

    SystemEvents.CONSULTATION_DELETED: EventMetadata(
        event=SystemEvents.CONSULTATION_DELETED,
        display_name="Xóa record tư vấn",
        description="Khi record tư vấn bị xóa",
        variables=[
            EventVariable("consultation_id", "integer", "ID record tư vấn"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer", required=False),
            EventVariable("actor_id", "integer", "ID người xóa"),
            EventVariable("actor_name", "string", "Tên người xóa", required=False),
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id"],
        default_channels=["browser"],
        category="consultation",
        condition_fields=_ACTOR_CONDITION_FIELDS + _LEAD_ENTITY_CONDITION_FIELDS + _CONSULTATION_CONDITION_FIELDS,
    ),

    SystemEvents.CONSULTATION_REMINDER: EventMetadata(
        event=SystemEvents.CONSULTATION_REMINDER,
        display_name="Nhắc nhở lịch tư vấn",
        description="Nhắc officer về lịch tư vấn sắp tới",
        variables=[
            EventVariable("consultation_id", "integer", "ID record tư vấn"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("lead_name", "string", "Tên lead"),
            EventVariable("lead_phone", "string", "SĐT lead"),
            EventVariable("officer_id", "integer", "ID officer được nhắc"),
            EventVariable("scheduled_at", "datetime", "Thời gian hẹn (ISO)"),
            EventVariable("minutes_until", "integer", "Số phút còn lại"),
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id", "minutes_until"],
        default_channels=["browser", "email"],
        category="consultation",
        condition_fields=_LEAD_ENTITY_CONDITION_FIELDS + _CONSULTATION_CONDITION_FIELDS + [
            ConditionField("event.minutes_until", "integer", "Số phút còn lại", _OPS_NUMERIC),
            ConditionField("event.scheduled_at", "datetime", "Thời gian hẹn", _OPS_NUMERIC),
        ],
    ),

    # =========================================================================
    # APPLICATION EVENTS (4 events)
    # NOTE: APPLICATION_* is a legacy notification namespace for AdmissionProfile.
    # =========================================================================

    SystemEvents.APPLICATION_CREATED: EventMetadata(
        event=SystemEvents.APPLICATION_CREATED,
        display_name="Hồ sơ mới được tạo",
        description="Khi có hồ sơ xét tuyển mới",
        variables=[
            EventVariable("application_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer xử lý"),
            EventVariable("major_program_name", "string", "Tên ngành", required=False),
            EventVariable("actor_id", "integer", "ID người tạo"),
        ],
        filter_fields=["application_id", "lead_id", "officer_id"],
        default_channels=["browser", "email"],
        category="application"
    ),

    SystemEvents.APPLICATION_STATUS_CHANGED: EventMetadata(
        event=SystemEvents.APPLICATION_STATUS_CHANGED,
        display_name="Trạng thái hồ sơ thay đổi",
        description="Khi trạng thái hồ sơ thay đổi",
        variables=[
            EventVariable("application_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer xử lý"),
            EventVariable("old_status", "string", "Trạng thái cũ"),
            EventVariable("new_status", "string", "Trạng thái mới"),
            EventVariable("actor_id", "integer", "ID người thay đổi"),
        ],
        filter_fields=["application_id", "lead_id", "officer_id", "new_status"],
        default_channels=["browser", "email"],
        category="application"
    ),

    SystemEvents.APPLICATION_DELETED: EventMetadata(
        event=SystemEvents.APPLICATION_DELETED,
        display_name="Hồ sơ bị xóa",
        description="Khi hồ sơ bị xóa khỏi hệ thống",
        variables=[
            EventVariable("application_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer đã xử lý"),
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("actor_id", "integer", "ID admin xóa"),
        ],
        filter_fields=["application_id", "lead_id", "officer_id"],
        default_channels=["browser"],
        category="application"
    ),

    # =========================================================================
    # FINANCE EVENTS (3 events)
    # =========================================================================

    SystemEvents.DORM_FEE_CREATED: EventMetadata(
        event=SystemEvents.DORM_FEE_CREATED,
        display_name="Phí ký túc xá được tạo",
        description="Khi có phí KTX mới",
        variables=[
            EventVariable("dorm_id", "integer", "ID ký túc xá"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "integer", "Số tiền"),
            EventVariable("due_date", "datetime", "Hạn thanh toán", required=False),
            EventVariable("actor_id", "integer", "ID người tạo"),
        ],
        filter_fields=["dorm_id", "fee_id", "amount"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.PAYMENT_RECEIVED: EventMetadata(
        event=SystemEvents.PAYMENT_RECEIVED,
        display_name="Thanh toán được ghi nhận",
        description="Khi có thanh toán được ghi nhận",
        variables=[
            EventVariable("payment_id", "integer", "ID thanh toán"),
            EventVariable("user_id", "integer", "ID người thanh toán"),
            EventVariable("amount", "integer", "Số tiền"),
            EventVariable("payment_type", "string", "Loại thanh toán"),
            EventVariable("actor_id", "integer", "ID người ghi nhận"),
        ],
        filter_fields=["payment_id", "user_id", "payment_type", "amount"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.PAYMENT_OVERDUE: EventMetadata(
        event=SystemEvents.PAYMENT_OVERDUE,
        display_name="Thanh toán quá hạn",
        description="Khi hóa đơn quá hạn thanh toán (invoice-level, PR 8)",
        variables=[
            EventVariable("invoice_id", "integer", "ID hóa đơn"),
            EventVariable("invoice_number", "string", "Số hóa đơn"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("fee_type", "string", "Loại phí"),
            EventVariable("semester_no", "integer", "Số kỳ học"),
            EventVariable("amount", "string", "Số tiền còn nợ"),
            EventVariable("due_date", "datetime", "Hạn thanh toán"),
            EventVariable("days_overdue", "integer", "Số ngày quá hạn"),
            EventVariable("days_overdue_bucket", "string", "Mốc quá hạn (1/7/14/30/30+)"),
            EventVariable("installment_no", "integer", "Đợt thanh toán"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("user_id", "integer", "ID officer (recipient)"),
        ],
        filter_fields=["invoice_id", "fee_id", "days_overdue", "fee_type", "semester_no"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.PAYMENT_VERIFIED: EventMetadata(
        event=SystemEvents.PAYMENT_VERIFIED,
        display_name="Thanh toán được xác nhận",
        description="Khi thanh toán đã được xác minh (checker xác nhận)",
        variables=[
            EventVariable("payment_id", "integer", "ID thanh toán"),
            EventVariable("invoice_id", "integer", "ID hóa đơn"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "string", "Số tiền thanh toán"),
            EventVariable("verified_by_id", "integer", "ID người xác nhận"),
            EventVariable("verified_at", "datetime", "Thời điểm xác nhận"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ tuyển sinh"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
        ],
        filter_fields=["payment_id", "fee_id", "amount", "admission_profile_id"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.PAYMENT_REJECTED: EventMetadata(
        event=SystemEvents.PAYMENT_REJECTED,
        display_name="Thanh toán bị từ chối",
        description="Khi checker từ chối một khoản thanh toán đang chờ",
        variables=[
            EventVariable("payment_id", "integer", "ID thanh toán"),
            EventVariable("invoice_id", "integer", "ID hóa đơn"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "string", "Số tiền thanh toán"),
            EventVariable("rejection_reason", "string", "Lý do từ chối"),
            EventVariable("rejected_by_id", "integer", "ID người từ chối"),
            EventVariable("created_by_id", "integer", "ID người ghi nhận (maker)"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ tuyển sinh"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("user_id", "integer", "ID maker (recipient)"),
        ],
        filter_fields=["payment_id", "fee_id", "amount", "admission_profile_id", "rejected_by_id"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.REFUND_PROCESSED: EventMetadata(
        event=SystemEvents.REFUND_PROCESSED,
        display_name="Hoàn tiền đã xử lý",
        description="Khi yêu cầu hoàn tiền đã được thực hiện (funds returned)",
        variables=[
            EventVariable("refund_id", "integer", "ID yêu cầu hoàn tiền"),
            EventVariable("payment_id", "integer", "ID thanh toán gốc"),
            EventVariable("invoice_id", "integer", "ID hóa đơn"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "string", "Số tiền hoàn"),
            EventVariable("reason", "string", "Lý do hoàn tiền"),
            EventVariable("processor_id", "integer", "ID người xử lý"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ tuyển sinh"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("user_ids", "array", "Recipients (officer + processor)"),
        ],
        filter_fields=["refund_id", "payment_id", "fee_id", "amount", "admission_profile_id"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.FEE_FULLY_PAID: EventMetadata(
        event=SystemEvents.FEE_FULLY_PAID,
        display_name="Học phí thanh toán đủ",
        description="Khi toàn bộ học phí của một kỳ đã được thanh toán đủ",
        variables=[
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "string", "Tổng học phí"),
            EventVariable("semester_no", "integer", "Số kỳ học"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("user_id", "integer", "ID officer (recipient)"),
        ],
        filter_fields=["fee_id", "amount", "semester_no", "admission_profile_id"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    SystemEvents.INVOICE_ISSUED: EventMetadata(
        event=SystemEvents.INVOICE_ISSUED,
        display_name="Hóa đơn được phát hành",
        description="Khi hóa đơn chuyển sang trạng thái phát hành",
        variables=[
            EventVariable("invoice_id", "integer", "ID hóa đơn"),
            EventVariable("invoice_number", "string", "Số hóa đơn"),
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("amount", "string", "Số tiền"),
            EventVariable("due_date", "datetime", "Hạn thanh toán"),
            EventVariable("admission_profile_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID lead"),
            EventVariable("unit_id", "integer", "ID đơn vị"),
            EventVariable("user_id", "integer", "ID officer (recipient)"),
        ],
        filter_fields=["invoice_id", "fee_id", "amount", "admission_profile_id"],
        default_channels=["browser", "email"],
        category="finance"
    ),

    # =========================================================================
    # DORM EVENTS (2 events)
    # =========================================================================

    SystemEvents.DORM_ROOM_ASSIGNED: EventMetadata(
        event=SystemEvents.DORM_ROOM_ASSIGNED,
        display_name="Phân phòng ký túc xá",
        description="Khi sinh viên được phân phòng KTX",
        variables=[
            EventVariable("dorm_id", "integer", "ID ký túc xá"),
            EventVariable("room_id", "integer", "ID phòng"),
            EventVariable("student_id", "integer", "ID sinh viên"),
            EventVariable("actor_id", "integer", "ID người phân"),
        ],
        filter_fields=["dorm_id", "room_id", "student_id"],
        default_channels=["browser", "email"],
        category="dorm"
    ),

    SystemEvents.DORM_MAINTENANCE_REQUEST: EventMetadata(
        event=SystemEvents.DORM_MAINTENANCE_REQUEST,
        display_name="Yêu cầu sửa chữa KTX",
        description="Khi có yêu cầu sửa chữa tại KTX",
        variables=[
            EventVariable("request_id", "integer", "ID yêu cầu"),
            EventVariable("dorm_id", "integer", "ID ký túc xá"),
            EventVariable("room_id", "integer", "ID phòng", required=False),
            EventVariable("priority", "string", "Độ ưu tiên"),
            EventVariable("description", "string", "Mô tả"),
            EventVariable("reporter_id", "integer", "ID người báo cáo"),
        ],
        filter_fields=["request_id", "dorm_id", "priority"],
        default_channels=["browser", "email"],
        category="dorm"
    ),

    # =========================================================================
    # ASSET EVENTS (2 events)
    # =========================================================================

    SystemEvents.ASSET_MAINTENANCE_ALERT: EventMetadata(
        event=SystemEvents.ASSET_MAINTENANCE_ALERT,
        display_name="Cảnh báo bảo trì tài sản",
        description="Khi tài sản cần bảo trì",
        variables=[
            EventVariable("asset_id", "integer", "ID tài sản"),
            EventVariable("asset_name", "string", "Tên tài sản"),
            EventVariable("maintenance_type", "string", "Loại bảo trì"),
            EventVariable("due_date", "datetime", "Hạn bảo trì", required=False),
            EventVariable("unit_id", "integer", "ID đơn vị phụ trách", required=False),
        ],
        filter_fields=["asset_id", "maintenance_type", "unit_id"],
        default_channels=["browser", "email"],
        category="asset"
    ),

    SystemEvents.ASSET_CHECKED_OUT: EventMetadata(
        event=SystemEvents.ASSET_CHECKED_OUT,
        display_name="Mượn tài sản",
        description="Khi tài sản được mượn",
        variables=[
            EventVariable("asset_id", "integer", "ID tài sản"),
            EventVariable("asset_name", "string", "Tên tài sản"),
            EventVariable("borrower_id", "integer", "ID người mượn"),
            EventVariable("expected_return", "datetime", "Ngày dự kiến trả", required=False),
            EventVariable("actor_id", "integer", "ID người cho mượn"),
        ],
        filter_fields=["asset_id", "borrower_id"],
        default_channels=["browser"],
        category="asset"
    ),

    # =========================================================================
    # SYSTEM EVENTS (4 events)
    # =========================================================================

    SystemEvents.SYSTEM_ALERT: EventMetadata(
        event=SystemEvents.SYSTEM_ALERT,
        display_name="Cảnh báo hệ thống",
        description="Cảnh báo quan trọng từ hệ thống",
        variables=[
            EventVariable("severity", "string", "Mức độ nghiêm trọng"),
            EventVariable("message", "string", "Nội dung cảnh báo"),
            EventVariable("action_url", "string", "URL hành động", required=False),
            EventVariable("expires_at", "datetime", "Thời gian hết hạn", required=False),
        ],
        filter_fields=["severity"],
        default_channels=["browser", "email"],
        category="system"
    ),

    SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE: EventMetadata(
        event=SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE,
        display_name="Lịch nghỉ lễ chưa đầy đủ",
        description="Lịch nghỉ lễ âm lịch cho năm tới chưa được cấu hình",
        variables=[
            EventVariable("severity", "string", "Mức độ"),
            EventVariable("message", "string", "Nội dung cảnh báo"),
            EventVariable("action_url", "string", "URL cấu hình lịch nghỉ", required=False),
            EventVariable("year", "integer", "Năm chưa đầy đủ"),
        ],
        filter_fields=["year"],
        default_channels=["browser", "email"],
        category="system"
    ),

    SystemEvents.SYSTEM_ANNOUNCEMENT: EventMetadata(
        event=SystemEvents.SYSTEM_ANNOUNCEMENT,
        display_name="Thông báo hệ thống",
        description="Thông báo toàn hệ thống",
        variables=[
            EventVariable("title", "string", "Tiêu đề"),
            EventVariable("message", "string", "Nội dung"),
            EventVariable("priority", "string", "Độ ưu tiên"),
            EventVariable("actor_id", "integer", "ID admin tạo"),
        ],
        filter_fields=["priority"],
        default_channels=["browser", "email"],
        category="system"
    ),

    SystemEvents.USER_ROLE_CHANGED: EventMetadata(
        event=SystemEvents.USER_ROLE_CHANGED,
        display_name="Thay đổi vai trò",
        description="Khi vai trò của user thay đổi",
        variables=[
            EventVariable("user_id", "integer", "ID user bị ảnh hưởng"),
            EventVariable("old_role", "string", "Vai trò cũ"),
            EventVariable("new_role", "string", "Vai trò mới"),
            EventVariable("unit_id", "integer", "ID đơn vị", required=False),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
        ],
        filter_fields=["user_id", "old_role", "new_role", "unit_id"],
        default_channels=["browser", "email"],
        category="system"
    ),

    SystemEvents.USER_DEACTIVATED: EventMetadata(
        event=SystemEvents.USER_DEACTIVATED,
        display_name="Vô hiệu hóa tài khoản",
        description="Khi tài khoản bị vô hiệu hóa",
        variables=[
            EventVariable("user_id", "integer", "ID user bị vô hiệu hóa"),
            EventVariable("username", "string", "Tên đăng nhập"),
            EventVariable("old_status", "string", "Trạng thái cũ"),
            EventVariable("reason", "string", "Lý do", required=False),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
        ],
        filter_fields=["user_id", "reason"],
        default_channels=["browser", "email"],
        category="system"
    ),

    SystemEvents.USER_PROFILE_UPDATED: EventMetadata(
        event=SystemEvents.USER_PROFILE_UPDATED,
        display_name="Cập nhật hồ sơ người dùng",
        description="Khi admin cập nhật hồ sơ người dùng",
        variables=[
            EventVariable("user_id", "integer", "ID user bị ảnh hưởng"),
            EventVariable("updated_fields", "string", "Các trường thay đổi"),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
        ],
        filter_fields=["user_id"],
        default_channels=["browser"],
        category="system"
    ),

    # =========================================================================
    # PIPELINE CONFIG EVENTS (1 event)
    # =========================================================================

    SystemEvents.PIPELINE_CONFIG_UPDATED: EventMetadata(
        event=SystemEvents.PIPELINE_CONFIG_UPDATED,
        display_name="Cập nhật cấu hình pipeline",
        description="Khi cấu hình pipeline thay đổi",
        variables=[
            EventVariable("config_type", "string", "Loại cấu hình"),
            EventVariable("operation", "string", "Hành động"),
            EventVariable("resource_id", "string", "ID resource"),
            EventVariable("resource_name", "string", "Tên resource", required=False),
            EventVariable("actor_id", "integer", "ID admin thực hiện"),
        ],
        filter_fields=["config_type", "operation"],
        default_channels=["browser"],
        category="pipeline"
    ),

    # =========================================================================
    # OFFICER/OPERATIONAL EVENTS (1 event)
    # =========================================================================

    SystemEvents.OFFICER_AVAILABILITY_CHANGED: EventMetadata(
        event=SystemEvents.OFFICER_AVAILABILITY_CHANGED,
        display_name="Trạng thái officer thay đổi",
        description="Khi officer thay đổi trạng thái sẵn sàng",
        variables=[
            EventVariable("officer_id", "integer", "ID officer"),
            EventVariable("new_status", "string", "Trạng thái mới"),
            EventVariable("old_status", "string", "Trạng thái cũ", required=False),
            EventVariable("username", "string", "Tên đăng nhập"),
            EventVariable("unit_id", "integer", "ID đơn vị", required=False),
            EventVariable("actor_id", "integer", "ID người thay đổi"),
        ],
        filter_fields=["officer_id", "new_status", "unit_id"],
        default_channels=["browser"],
        category="operational"
    ),

    # =========================================================================
    # SECURITY EVENTS
    # =========================================================================

    SystemEvents.SUSPICIOUS_LOGIN: EventMetadata(
        event=SystemEvents.SUSPICIOUS_LOGIN,
        display_name="Đăng nhập đáng ngờ",
        description="Khi phát hiện đăng nhập bất thường (IP mới, thiết bị mới, vị trí mới)",
        variables=[
            EventVariable("user_id", "integer", "ID người dùng"),
            EventVariable("login_history_id", "integer", "ID lịch sử đăng nhập"),
            EventVariable("ip_address", "string", "Địa chỉ IP"),
            EventVariable("location", "string", "Vị trí (thành phố, quốc gia)", required=False),
            EventVariable("device", "string", "Thông tin thiết bị/trình duyệt", required=False),
            EventVariable("risk_score", "integer", "Điểm rủi ro (0-100)", required=False),
            EventVariable("anomalies", "string", "Danh sách bất thường", required=False),
            EventVariable("actor_id", "integer", "ID người đăng nhập"),
        ],
        filter_fields=["user_id", "risk_score", "ip_address"],
        default_channels=["browser", "email"],
        category="security"
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_event_metadata(event: SystemEvents) -> Optional[EventMetadata]:
    """
    Get metadata for a specific event.

    Args:
        event: SystemEvents enum value

    Returns:
        EventMetadata if found, None otherwise
    """
    return EVENT_METADATA_REGISTRY.get(event)


def get_all_events_metadata() -> Dict[str, Dict]:
    """
    Get all event metadata as a dictionary (for API response).

    Returns:
        Dict mapping event names to metadata dicts
    """
    result = {}
    for event, metadata in EVENT_METADATA_REGISTRY.items():
        result[event.value] = {
            "event": event.value,
            "display_name": metadata.display_name,
            "description": metadata.description,
            "variables": [
                {
                    "name": var.name,
                    "type": var.type,
                    "description": var.description,
                    "required": var.required
                }
                for var in metadata.variables
            ],
            "filter_fields": metadata.filter_fields,
            "default_channels": metadata.default_channels,
            "category": metadata.category,
            "condition_fields": [
                {
                    "path": cf.path,
                    "type": cf.type,
                    "description": cf.description,
                    "operators": cf.operators,
                }
                for cf in metadata.condition_fields
            ],
        }
    return result


def get_events_by_category(category: str) -> List[EventMetadata]:
    """
    Get all events in a specific category.

    Args:
        category: Category name (lead, consultation, application, etc.)

    Returns:
        List of EventMetadata for the category
    """
    return [
        metadata
        for metadata in EVENT_METADATA_REGISTRY.values()
        if metadata.category == category
    ]


def get_all_categories() -> List[str]:
    """
    Get list of all unique categories.

    Returns:
        List of category names
    """
    return list(set(metadata.category for metadata in EVENT_METADATA_REGISTRY.values()))
