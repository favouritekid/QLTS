"""
Event Catalog — single source of truth for event semantics.

Merges data from:
- event_metadata.py (display, variables, condition_fields)
- notification_registry.py (resolver, dedup, priority, link)

Code owns: event existence, classification, resolver OPTIONS, dedup, priority,
           link strategy, variables, condition fields.
DB owns:   enabled, title/message templates, selected channels, selected resolver,
           content overrides, conditions, action workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Dict, List, Optional

from app.core.events import SystemEvents


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventVariable:
    """Payload variable available for template rendering."""
    name: str
    type: str           # "string", "integer", "boolean", "datetime", "float", "array"
    description: str
    required: bool = True


@dataclass(frozen=True)
class ConditionField:
    """Field that admin can use in rule conditions."""
    path: str           # "actor.role", "event.new_status_id", "lead.source"
    type: str           # "string", "integer", "boolean", "array", "datetime"
    description: str
    operators: tuple = ()   # ("eq", "ne", "in", "not_in", ...)


@dataclass(frozen=True)
class EventDefinition:
    """Unified event definition combining metadata + technical config."""
    # Identity
    event: SystemEvents
    category: str                               # "lead", "consultation", ...

    # Display (for frontend metadata API)
    display_name: str
    description: str
    variables: tuple = ()                        # Tuple[EventVariable, ...]
    condition_fields: tuple = ()                 # Tuple[ConditionField, ...]

    # Technical (code-owned, admin cannot modify)
    default_resolver: str = "all_admins"
    allowed_resolvers: tuple = ()                # Tuple[str, ...]
    default_channels: tuple = ("browser",)       # Tuple[str, ...]
    priority: int = 100                          # lower = higher priority
    dedup_key_template: Optional[str] = None
    link_strategy: Optional[str] = None

    # Classification (3-tier)
    notification_class: str = "user"             # "user" | "broadcast_only" | "internal_future"
    retired: bool = False


# ---------------------------------------------------------------------------
# Helpers — variable / condition shortcuts
# ---------------------------------------------------------------------------

def _var(name: str, tp: str, desc: str, req: bool = True) -> EventVariable:
    return EventVariable(name=name, type=tp, description=desc, required=req)


def _cond(path: str, tp: str, desc: str, ops: tuple) -> ConditionField:
    return ConditionField(path=path, type=tp, description=desc, operators=ops)


_OPS_STR = ("eq", "ne", "in", "not_in", "contains")
_OPS_NUM = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in")
_OPS_BOOL = ("eq", "ne")
_OPS_ARR = ("contains",)

# Reusable condition-field blocks
_ACTOR_CONDS: tuple = (
    _cond("actor.id", "integer", "ID người thực hiện", _OPS_NUM),
    _cond("actor.name", "string", "Tên người thực hiện", _OPS_STR),
    _cond("actor.role", "string", "Vai trò người thực hiện", _OPS_STR),
    _cond("actor.unit_id", "integer", "ID đơn vị của người thực hiện", _OPS_NUM),
)

_LEAD_CONDS: tuple = (
    _cond("lead.id", "integer", "ID của lead", _OPS_NUM),
    _cond("lead.name", "string", "Tên lead", _OPS_STR),
    _cond("lead.source", "string", "Nguồn lead", _OPS_STR),
    _cond("lead.consultation_status_id", "string", "Mã trạng thái tư vấn", _OPS_STR),
    _cond("lead.stage_id", "string", "Mã giai đoạn pipeline", _OPS_STR),
    _cond("lead.unit_id", "integer", "ID đơn vị của lead", _OPS_NUM),
    _cond("lead.officer_id", "integer", "ID officer phụ trách lead", _OPS_NUM),
)

_CONSULTATION_CONDS: tuple = (
    _cond("consultation.id", "integer", "ID record tư vấn", _OPS_NUM),
    _cond("consultation.status_id", "string", "Mã trạng thái tư vấn", _OPS_STR),
)

# Reusable resolver sets
_LEAD_RESOLVERS = ("lead_owner", "unit_staff", "unit_managers", "all_admins", "specific_users")
_ADMIN_RESOLVERS = ("all_admins", "unit_managers", "all_users", "specific_users")
_CTV_RESOLVERS = ("collaborator_user", "unit_managers", "all_admins", "specific_users")
_SYSTEM_RESOLVERS = ("all_users", "all_admins", "specific_users")
_FINANCE_RESOLVERS = ("specific_users", "all_admins", "unit_managers")


# ===================================================================
# EVENT DEFINITIONS — organized by category
# ===================================================================

# -------------------------------------------------------------------
# 1. Lead events (9 entries)
# -------------------------------------------------------------------

_LEAD_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.LEAD_ASSIGNED,
        category="lead",
        display_name="Lead được phân công",
        description="Khi lead được assign cho officer",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer được phân công"),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
            _var("lead_name", "string", "Tên lead", False),
            _var("lead_phone", "string", "SĐT lead", False),
            _var("offering_name", "string", "Tên chương trình", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
        dedup_key_template="lead:${lead_id}:assigned:${officer_id}",
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
        category="lead",
        display_name="Phân công lead thất bại",
        description="Khi hệ thống không thể tự động phân công lead",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("reason", "string", "Lý do thất bại"),
            _var("lead_name", "string", "Tên lead", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="unit_managers",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser", "email"),
        priority=30,
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_REASSIGNED,
        category="lead",
        display_name="Lead được chuyển giao",
        description="Khi lead được chuyển sang đơn vị/officer khác",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("old_officer_id", "integer", "ID officer cũ", False),
            _var("new_officer_id", "integer", "ID officer mới", False),
            _var("old_unit_id", "integer", "ID đơn vị cũ"),
            _var("new_unit_id", "integer", "ID đơn vị mới"),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
            _var("reason", "string", "Lý do chuyển giao", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + (
            _cond("event.old_unit_id", "integer", "ID đơn vị cũ", _OPS_NUM),
            _cond("event.new_unit_id", "integer", "ID đơn vị mới", _OPS_NUM),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser", "email"),
        priority=60,
        dedup_key_template="lead:${lead_id}:reassigned",
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_STATUS_CHANGED,
        category="lead",
        display_name="Trạng thái lead thay đổi",
        description="Khi lead chuyển sang giai đoạn khác trong pipeline",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead", False),
            _var("officer_id", "integer", "ID officer phụ trách", False),
            _var("officer_name", "string", "Tên officer", False),
            _var("old_status", "string", "Trạng thái cũ"),
            _var("new_status", "string", "Trạng thái mới"),
            _var("old_stage", "integer", "Giai đoạn cũ", False),
            _var("new_stage", "integer", "Giai đoạn mới", False),
            _var("updated_fields", "array", "Các trường đã cập nhật", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + (
            _cond("event.old_status_id", "string", "Trạng thái cũ", _OPS_STR),
            _cond("event.new_status_id", "string", "Trạng thái mới", _OPS_STR),
            _cond("event.old_stage_id", "string", "Giai đoạn cũ", _OPS_STR),
            _cond("event.new_stage_id", "string", "Giai đoạn mới", _OPS_STR),
            _cond("event.updated_fields", "array", "Các trường cập nhật", _OPS_ARR),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        dedup_key_template="lead:${lead_id}:status:${new_status}",
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_CREATED,
        category="lead",
        display_name="Lead mới được tạo",
        description="Khi có lead mới trong hệ thống",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("lead_name", "string", "Tên lead", False),
            _var("source", "string", "Nguồn lead", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="unit_managers",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=80,
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_DELETED,
        category="lead",
        display_name="Lead bị xóa",
        description="Khi lead bị soft-delete khỏi hệ thống",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead", False),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("officer_id", "integer", "ID officer phụ trách", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="specific_users",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/leads",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_RESTORED,
        category="lead",
        display_name="Lead được khôi phục",
        description="Khi lead bị xóa được khôi phục lại",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead", False),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("officer_id", "integer", "ID officer phụ trách", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện"),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/leads/${lead_id}",
    ),
    EventDefinition(
        event=SystemEvents.LEAD_IMPORTED,
        category="lead",
        display_name="Import lead hàng loạt",
        description="Khi lead được import từ file CSV/Excel",
        variables=(
            _var("total_imported", "integer", "Tổng số lead import"),
            _var("sample_lead_ids", "array", "Danh sách ID mẫu", False),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("filename", "string", "Tên file import"),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện"),
        ),
        condition_fields=_ACTOR_CONDS + (
            _cond("event.unit_id", "integer", "ID đơn vị", _OPS_NUM),
            _cond("event.total_imported", "integer", "Tổng import", _OPS_NUM),
            _cond("event.filename", "string", "Tên file", _OPS_STR),
        ),
        default_resolver="unit_managers",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=120,
        link_strategy="/leads",
    ),
    EventDefinition(
        event=SystemEvents.OFFICER_AVAILABILITY_CHANGED,
        category="lead",
        display_name="Trạng thái officer thay đổi",
        description="Khi officer thay đổi trạng thái sẵn sàng",
        variables=(
            _var("officer_id", "integer", "ID officer"),
            _var("new_status", "string", "Trạng thái mới"),
            _var("old_status", "string", "Trạng thái cũ", False),
            _var("username", "string", "Tên officer"),
            _var("unit_id", "integer", "ID đơn vị", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="all_admins",
        allowed_resolvers=_ADMIN_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/admin/users",
    ),
)

# -------------------------------------------------------------------
# 2. Consultation events (4 entries)
# -------------------------------------------------------------------

_CONSULTATION_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.CONSULTATION_CREATED,
        category="consultation",
        display_name="Tư vấn mới được tạo",
        description="Khi có record tư vấn mới",
        variables=(
            _var("consultation_id", "integer", "ID tư vấn"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer", False),
            _var("status_id", "string", "Mã trạng thái"),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
            _var("unit_id", "integer", "ID đơn vị"),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + _CONSULTATION_CONDS,
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/leads/${lead_id}?tab=consultations",
    ),
    EventDefinition(
        event=SystemEvents.CONSULTATION_UPDATED,
        category="consultation",
        display_name="Cập nhật tư vấn",
        description="Khi record tư vấn được cập nhật",
        variables=(
            _var("consultation_id", "integer", "ID tư vấn"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer", False),
            _var("old_status_id", "string", "Trạng thái cũ", False),
            _var("new_status_id", "string", "Trạng thái mới"),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + _CONSULTATION_CONDS + (
            _cond("event.old_status_id", "string", "Trạng thái cũ", _OPS_STR),
            _cond("event.new_status_id", "string", "Trạng thái mới", _OPS_STR),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=120,
        link_strategy="/leads/${lead_id}?tab=consultations",
    ),
    EventDefinition(
        event=SystemEvents.CONSULTATION_DELETED,
        category="consultation",
        display_name="Xóa record tư vấn",
        description="Khi record tư vấn bị xóa",
        variables=(
            _var("consultation_id", "integer", "ID tư vấn"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + _CONSULTATION_CONDS,
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/leads/${lead_id}?tab=consultations",
    ),
    EventDefinition(
        event=SystemEvents.CONSULTATION_REMINDER,
        category="consultation",
        display_name="Nhắc nhở lịch tư vấn",
        description="Nhắc officer về lịch tư vấn sắp tới",
        variables=(
            _var("consultation_id", "integer", "ID tư vấn"),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead"),
            _var("lead_phone", "string", "SĐT lead"),
            _var("officer_id", "integer", "ID officer"),
            _var("scheduled_at", "datetime", "Thời gian hẹn"),
            _var("minutes_until", "integer", "Số phút còn lại"),
        ),
        condition_fields=_LEAD_CONDS + _CONSULTATION_CONDS + (
            _cond("event.minutes_until", "integer", "Số phút còn lại", _OPS_NUM),
            _cond("event.scheduled_at", "datetime", "Thời gian hẹn", _OPS_NUM),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser", "email"),
        priority=10,
        dedup_key_template="reminder:${lead_id}:${consultation_id}",
        link_strategy="/leads/${lead_id}",
    ),
)

# -------------------------------------------------------------------
# 3. Admission events (3 entries)
# -------------------------------------------------------------------

_ADMISSION_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.APPLICATION_CREATED,
        category="application",
        display_name="Hồ sơ mới được tạo",
        description="Khi có hồ sơ xét tuyển mới",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer"),
            _var("major_program_name", "string", "Tên ngành", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=70,
        link_strategy="/admissions/${application_id}",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_STATUS_CHANGED,
        category="application",
        display_name="Trạng thái hồ sơ thay đổi",
        description="Khi trạng thái hồ sơ thay đổi",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer"),
            _var("old_status", "string", "Trạng thái cũ"),
            _var("new_status", "string", "Trạng thái mới"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=80,
        dedup_key_template="app:${application_id}:status:${new_status}",
        link_strategy="/admissions/${application_id}",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_DELETED,
        category="application",
        display_name="Hồ sơ bị xóa",
        description="Khi hồ sơ bị xóa khỏi hệ thống",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("officer_id", "integer", "ID officer"),
            _var("lead_name", "string", "Tên lead", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser",),
        priority=100,
        link_strategy="/admissions",
    ),
)

# -------------------------------------------------------------------
# 4. Finance events — user (2) + internal_future (2)
# -------------------------------------------------------------------

_FINANCE_USER_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.PAYMENT_RECEIVED,
        category="finance",
        display_name="Thanh toán được ghi nhận",
        description="Khi có thanh toán được ghi nhận",
        variables=(
            _var("payment_id", "integer", "ID thanh toán"),
            _var("user_id", "integer", "ID user thanh toán"),
            _var("amount", "integer", "Số tiền"),
            _var("payment_type", "string", "Loại thanh toán"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=70,
        link_strategy="/finance/payments/${payment_id}",
    ),
    EventDefinition(
        event=SystemEvents.PAYMENT_VERIFIED,
        category="finance",
        display_name="Thanh toán được xác nhận",
        description="Khi thanh toán đã được xác minh (checker xác nhận)",
        variables=(
            _var("payment_id", "integer", "ID thanh toán"),
            _var("invoice_id", "integer", "ID hóa đơn"),
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "string", "Số tiền"),
            _var("verified_by_id", "integer", "ID người xác nhận"),
            _var("verified_at", "datetime", "Thời gian xác nhận"),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=60,
        link_strategy="/finance/payments/${payment_id}",
    ),
)

_FINANCE_FUTURE_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.DORM_FEE_CREATED,
        category="dorm",   # D: F4 fix — wrong domain → dorm
        display_name="Phí ký túc xá được tạo",
        description="Khi có phí KTX mới",
        variables=(
            _var("dorm_id", "integer", "ID ký túc xá"),
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "integer", "Số tiền"),
            _var("due_date", "datetime", "Hạn thanh toán", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=60,
        link_strategy="/finance/fees/${fee_id}",
        notification_class="internal_future",
    ),
    EventDefinition(
        event=SystemEvents.PAYMENT_OVERDUE,
        category="finance",
        display_name="Thanh toán quá hạn",
        description="Khi thanh toán quá hạn — promote khi beat task implemented",
        variables=(
            _var("fee_id", "integer", "ID phí"),
            _var("user_id", "integer", "ID user"),
            _var("amount", "integer", "Số tiền"),
            _var("days_overdue", "integer", "Số ngày quá hạn"),
            _var("fee_type", "string", "Loại phí"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=20,
        link_strategy="/finance/fees/${fee_id}",
        notification_class="internal_future",
    ),
)

# -------------------------------------------------------------------
# 5. CTV events — user (9) + internal_future (1)
# -------------------------------------------------------------------

_CTV_USER_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.CTV_CLAIM_SUBMITTED,
        category="ctv",
        display_name="CTV gửi claim mới",
        description="Khi cộng tác viên gửi claim cho lead",
        variables=(
            _var("claim_id", "integer", "ID claim"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("collaborator_name", "string", "Tên CTV"),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="unit_managers",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser",),
        priority=60,
        dedup_key_template="ctv:claim:${claim_id}:submitted",
        link_strategy="/admin/collaborators/claims/${claim_id}",
    ),
    EventDefinition(
        event=SystemEvents.CTV_CLAIM_APPROVED,
        category="ctv",
        display_name="Claim được duyệt",
        description="Khi claim của CTV được duyệt",
        variables=(
            _var("claim_id", "integer", "ID claim"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("collaborator_name", "string", "Tên CTV", False),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
        dedup_key_template="ctv:claim:${claim_id}:approved",
        link_strategy="/ctv/claims",
    ),
    EventDefinition(
        event=SystemEvents.CTV_CLAIM_REJECTED,
        category="ctv",
        display_name="Claim bị từ chối",
        description="Khi claim của CTV bị từ chối",
        variables=(
            _var("claim_id", "integer", "ID claim"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("collaborator_name", "string", "Tên CTV", False),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Tên lead", False),
            _var("rejection_reason", "string", "Lý do từ chối"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
        dedup_key_template="ctv:claim:${claim_id}:rejected",
        link_strategy="/ctv/claims",
    ),
    EventDefinition(
        event=SystemEvents.CTV_APPROVED,
        category="ctv",
        display_name="Tài khoản CTV được duyệt",
        description="Khi tài khoản CTV được admin duyệt",
        variables=(
            _var("collaborator_id", "integer", "ID CTV"),
            _var("collaborator_name", "string", "Tên CTV", False),
            _var("user_id", "integer", "ID user liên kết"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=30,
        dedup_key_template="ctv:${collaborator_id}:approved",
    ),
    EventDefinition(
        event=SystemEvents.CTV_SUSPENDED,
        category="ctv",
        display_name="Tài khoản CTV bị đình chỉ",
        description="Khi tài khoản CTV bị đình chỉ",
        variables=(
            _var("collaborator_id", "integer", "ID CTV"),
            _var("collaborator_name", "string", "Tên CTV", False),
            _var("user_id", "integer", "ID user liên kết"),
            _var("reason", "string", "Lý do đình chỉ", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="ctv:${collaborator_id}:suspended",
    ),
    EventDefinition(
        event=SystemEvents.CTV_COMMISSION_CREATED,
        category="ctv",
        display_name="Hoa hồng mới",
        description="Khi CTV nhận được hoa hồng",
        variables=(
            _var("commission_id", "integer", "ID hoa hồng"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("lead_id", "integer", "ID lead"),
            _var("amount", "string", "Số tiền hoa hồng"),
            _var("actor_id", "integer", "ID người thực hiện", False),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=30,
        dedup_key_template="ctv:commission:${commission_id}:created",
        link_strategy="/ctv/commissions",
    ),
    EventDefinition(
        event=SystemEvents.CTV_ATTRIBUTION_EXPIRING,
        category="ctv",
        display_name="Quyền giới thiệu sắp hết hạn",
        description="Quyền giới thiệu lead sắp hết hạn",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("days_remaining", "integer", "Số ngày còn lại"),
            _var("expiry_date", "datetime", "Ngày hết hạn", False),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=35,
        dedup_key_template="ctv:attribution:${lead_id}:expiring",
        link_strategy="/ctv/leads",
    ),
    EventDefinition(
        event=SystemEvents.CTV_ATTRIBUTION_EXPIRED,
        category="ctv",
        display_name="Quyền giới thiệu hết hạn",
        description="Quyền giới thiệu lead đã hết hạn",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("attribution_id", "integer", "ID attribution", False),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=40,
        dedup_key_template="ctv:attribution:${lead_id}:expired",
        link_strategy="/ctv/leads",
    ),
    EventDefinition(
        event=SystemEvents.CTV_WEEKLY_SUMMARY,
        category="ctv",
        display_name="Báo cáo tuần CTV",
        description="Tổng hợp hoạt động CTV trong tuần",
        variables=(
            _var("collaborator_id", "integer", "ID CTV"),
            _var("new_leads", "integer", "Số lead mới"),
            _var("commissions", "integer", "Số hoa hồng"),
            _var("total_earnings", "integer", "Tổng thu nhập", False),
            _var("week", "string", "Tuần (ISO)"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser", "email"),
        priority=90,
        dedup_key_template="ctv:weekly:${collaborator_id}:${week}",
        link_strategy="/ctv",
    ),
)

_CTV_FUTURE_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.CTV_LEAD_CONVERTED,
        category="ctv",
        display_name="Lead tiến triển",
        description="Khi lead của CTV chuyển trạng thái — promote khi dispatch implemented",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("collaborator_id", "integer", "ID CTV"),
            _var("old_status", "string", "Trạng thái cũ"),
            _var("new_status", "string", "Trạng thái mới"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="collaborator_user",
        allowed_resolvers=_CTV_RESOLVERS,
        default_channels=("browser",),
        priority=80,
        dedup_key_template="ctv:lead:${lead_id}:converted:${new_status}",
        link_strategy="/ctv/leads",
        notification_class="internal_future",
    ),
)

# -------------------------------------------------------------------
# 6. System + Security events (7 entries)
# -------------------------------------------------------------------

_SYSTEM_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.SYSTEM_ALERT,
        category="system",
        display_name="Cảnh báo hệ thống",
        description="Cảnh báo quan trọng từ hệ thống",
        variables=(
            _var("severity", "string", "Mức độ nghiêm trọng"),
            _var("message", "string", "Nội dung cảnh báo"),
            _var("action_url", "string", "Link hành động", False),
            _var("expires_at", "datetime", "Hết hạn", False),
        ),
        default_resolver="all_users",
        allowed_resolvers=_SYSTEM_RESOLVERS,
        default_channels=("browser", "email"),
        priority=10,
        link_strategy="${action_url}",
    ),
    EventDefinition(
        event=SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE,
        category="system",
        display_name="Lịch nghỉ lễ chưa đầy đủ",
        description="Lịch nghỉ lễ âm lịch cho năm tới chưa được cấu hình",
        variables=(
            _var("severity", "string", "Mức độ"),
            _var("message", "string", "Nội dung"),
            _var("action_url", "string", "Link hành động", False),
            _var("year", "integer", "Năm"),
        ),
        default_resolver="all_admins",
        allowed_resolvers=_ADMIN_RESOLVERS,
        default_channels=("browser",),
        priority=20,
        link_strategy="${action_url}",
    ),
    EventDefinition(
        event=SystemEvents.SYSTEM_ANNOUNCEMENT,
        category="system",
        display_name="Thông báo hệ thống",
        description="Thông báo toàn hệ thống",
        variables=(
            _var("title", "string", "Tiêu đề"),
            _var("message", "string", "Nội dung"),
            _var("priority", "string", "Độ ưu tiên"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="all_users",
        allowed_resolvers=_SYSTEM_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
    ),
    EventDefinition(
        event=SystemEvents.USER_ROLE_CHANGED,
        category="system",
        display_name="Thay đổi vai trò",
        description="Khi vai trò của user thay đổi",
        variables=(
            _var("user_id", "integer", "ID user"),
            _var("old_role", "string", "Vai trò cũ"),
            _var("new_role", "string", "Vai trò mới"),
            _var("unit_id", "integer", "ID đơn vị", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_SYSTEM_RESOLVERS,
        default_channels=("browser", "email"),
        priority=40,
        link_strategy="/profile",
    ),
    EventDefinition(
        event=SystemEvents.USER_DEACTIVATED,
        category="system",
        display_name="Vô hiệu hóa tài khoản",
        description="Khi tài khoản bị vô hiệu hóa",
        variables=(
            _var("user_id", "integer", "ID user"),
            _var("username", "string", "Tên user"),
            _var("old_status", "string", "Trạng thái cũ"),
            _var("reason", "string", "Lý do", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_SYSTEM_RESOLVERS,
        default_channels=("browser",),
        priority=5,
    ),
    EventDefinition(
        event=SystemEvents.PIPELINE_CONFIG_UPDATED,
        category="pipeline",
        display_name="Cập nhật cấu hình pipeline",
        description="Khi cấu hình pipeline thay đổi",
        variables=(
            _var("config_type", "string", "Loại cấu hình"),
            _var("operation", "string", "Thao tác"),
            _var("resource_id", "string", "ID tài nguyên"),
            _var("resource_name", "string", "Tên tài nguyên", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="all_admins",
        allowed_resolvers=_ADMIN_RESOLVERS,
        default_channels=("browser",),
        priority=100,
        link_strategy="/admin/pipeline",
    ),
    EventDefinition(
        event=SystemEvents.SUSPICIOUS_LOGIN,
        category="security",
        display_name="Đăng nhập đáng ngờ",
        description="Khi phát hiện đăng nhập bất thường",
        variables=(
            _var("user_id", "integer", "ID user"),
            _var("login_history_id", "integer", "ID lịch sử đăng nhập"),
            _var("ip_address", "string", "Địa chỉ IP"),
            _var("location", "string", "Vị trí", False),
            _var("device", "string", "Thiết bị", False),
            _var("risk_score", "integer", "Điểm rủi ro", False),
            _var("anomalies", "string", "Bất thường", False),
            _var("actor_id", "integer", "ID user đăng nhập"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        default_channels=("browser", "email"),
        priority=10,
        dedup_key_template="security:${user_id}:suspicious_login:${login_history_id}",
        link_strategy="/settings/login-history",
    ),
)

# -------------------------------------------------------------------
# 7. Broadcast-only events (10 entries) — D1: no DB rule, no UI
# -------------------------------------------------------------------

_BROADCAST_EVENTS: tuple = tuple(
    EventDefinition(
        event=ev,
        category="organization",
        display_name=ev.value.replace("_", " ").title(),
        description=f"Broadcast-only: {ev.value}",
        notification_class="broadcast_only",
    )
    for ev in (
        SystemEvents.UNIT_CREATED, SystemEvents.UNIT_UPDATED, SystemEvents.UNIT_DELETED,
        SystemEvents.PROGRAM_CREATED, SystemEvents.PROGRAM_UPDATED, SystemEvents.PROGRAM_DELETED,
        SystemEvents.OFFERING_CREATED, SystemEvents.OFFERING_UPDATED, SystemEvents.OFFERING_DELETED,
    )
) + (
    EventDefinition(
        event=SystemEvents.LEAD_UPDATED,
        category="lead",
        display_name="Lead được cập nhật",
        description="UI real-time sync — quá rộng cho notification (D1)",
        variables=(
            _var("lead_id", "integer", "ID lead"),
            _var("updated_fields", "array", "Các trường cập nhật", False),
            _var("status_changed", "boolean", "Có đổi trạng thái", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        notification_class="broadcast_only",
    ),
)

# -------------------------------------------------------------------
# 8. Internal/future events — Dorm, Asset (4 entries)
# -------------------------------------------------------------------

_INTERNAL_FUTURE_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.DORM_ROOM_ASSIGNED,
        category="dorm",
        display_name="Phân phòng ký túc xá",
        description="Module chưa build — promote khi Dorm module implemented",
        variables=(
            _var("dorm_id", "integer", "ID ký túc xá"),
            _var("room_id", "integer", "ID phòng"),
            _var("student_id", "integer", "ID sinh viên"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        default_channels=("browser", "email"),
        priority=60,
        link_strategy="/dorm/rooms/${room_id}",
        notification_class="internal_future",
    ),
    EventDefinition(
        event=SystemEvents.DORM_MAINTENANCE_REQUEST,
        category="dorm",
        display_name="Yêu cầu sửa chữa KTX",
        description="Module chưa build — promote khi Dorm module implemented",
        variables=(
            _var("request_id", "integer", "ID yêu cầu"),
            _var("dorm_id", "integer", "ID ký túc xá"),
            _var("room_id", "integer", "ID phòng", False),
            _var("priority", "string", "Độ ưu tiên"),
            _var("description", "string", "Mô tả"),
            _var("reporter_id", "integer", "ID người báo"),
        ),
        default_resolver="unit_staff",
        default_channels=("browser", "email"),
        priority=50,
        link_strategy="/dorm/maintenance/${request_id}",
        notification_class="internal_future",
    ),
    EventDefinition(
        event=SystemEvents.ASSET_MAINTENANCE_ALERT,
        category="asset",
        display_name="Cảnh báo bảo trì tài sản",
        description="Module chưa build — promote khi Asset module implemented",
        variables=(
            _var("asset_id", "integer", "ID tài sản"),
            _var("asset_name", "string", "Tên tài sản"),
            _var("maintenance_type", "string", "Loại bảo trì"),
            _var("due_date", "datetime", "Hạn bảo trì", False),
            _var("unit_id", "integer", "ID đơn vị", False),
        ),
        default_resolver="unit_staff",
        default_channels=("browser", "email"),
        priority=70,
        link_strategy="/assets/${asset_id}",
        notification_class="internal_future",
    ),
    EventDefinition(
        event=SystemEvents.ASSET_CHECKED_OUT,
        category="asset",
        display_name="Mượn tài sản",
        description="Module chưa build — promote khi Asset module implemented",
        variables=(
            _var("asset_id", "integer", "ID tài sản"),
            _var("asset_name", "string", "Tên tài sản"),
            _var("borrower_id", "integer", "ID người mượn"),
            _var("expected_return", "datetime", "Ngày trả dự kiến", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="all_admins",
        default_channels=("browser",),
        priority=120,
        link_strategy="/assets/${asset_id}",
        notification_class="internal_future",
    ),
)


# ===================================================================
# 9. EVENT_CATALOG dict assembly
# ===================================================================

EVENT_CATALOG: Dict[SystemEvents, EventDefinition] = {}

for _group in (
    _LEAD_EVENTS,
    _CONSULTATION_EVENTS,
    _ADMISSION_EVENTS,
    _FINANCE_USER_EVENTS,
    _FINANCE_FUTURE_EVENTS,
    _CTV_USER_EVENTS,
    _CTV_FUTURE_EVENTS,
    _SYSTEM_EVENTS,
    _BROADCAST_EVENTS,
    _INTERNAL_FUTURE_EVENTS,
):
    for _defn in _group:
        assert _defn.event not in EVENT_CATALOG, f"Duplicate event: {_defn.event}"
        EVENT_CATALOG[_defn.event] = _defn


# ===================================================================
# 10. Public API
# ===================================================================

def get_event(event: SystemEvents) -> Optional[EventDefinition]:
    """Get event definition by SystemEvents enum member."""
    return EVENT_CATALOG.get(event)


def get_event_by_key(key: str) -> Optional[EventDefinition]:
    """Get event definition by string key (e.g. 'lead_assigned')."""
    for ev, defn in EVENT_CATALOG.items():
        if ev.value == key:
            return defn
    return None


def get_notifiable_events() -> List[EventDefinition]:
    """Return only notification_class='user' and not retired — for admin UI / sync."""
    return [
        d for d in EVENT_CATALOG.values()
        if d.notification_class == "user" and not d.retired
    ]


def get_active_events() -> List[EventDefinition]:
    """Return all non-retired events (including broadcast_only)."""
    return [d for d in EVENT_CATALOG.values() if not d.retired]


def render_dedup_key(event: SystemEvents, payload: dict) -> Optional[str]:
    """Render dedup key from catalog template + payload. Returns None if no template."""
    defn = EVENT_CATALOG.get(event)
    if not defn or not defn.dedup_key_template:
        return None
    return Template(defn.dedup_key_template).safe_substitute(payload)


def render_link(event: SystemEvents, payload: dict) -> Optional[str]:
    """Render link from catalog template + payload. Code-owned, not DB."""
    defn = EVENT_CATALOG.get(event)
    if not defn or not defn.link_strategy:
        return None
    return Template(defn.link_strategy).safe_substitute(payload)
