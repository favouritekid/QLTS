"""
Event Catalog — single source of truth for event semantics.

Originally merged data from two modules that have since been retired
in Wave 3 (2026-04-21):
- event_metadata.py — display, variables, condition_fields
- notification_registry.py — resolver, dedup, priority, link

Those modules are gone; the catalog below now carries all of that
inline. Per-event content that is NOT semantics (title_template,
message_template, notification_type, pre-serialized recipient_config)
lives in `app.core.notification_seed_defaults` for the seeders to
consume.

Code owns: event existence, classification, resolver OPTIONS, dedup, priority,
           link strategy, variables, condition fields.
DB owns:   enabled, title/message templates, selected channels, selected resolver,
           content overrides, conditions, action workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import Template
from typing import Dict, List, Literal, Optional

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

    # Privacy (Socket.IO scoping — PR #2 socket_scoped_emit):
    # - "public": safe to broadcast globally via `sio.emit(event, data)` — no PII.
    #             Examples: pipeline_config_updated, change_template_*, system_announcement,
    #             organization structure changes (unit/program/offering CRUD).
    # - "sensitive": carries lead/applicant/user PII — MUST be emitted with explicit
    #                `rooms` targeting (unit_<id> + role_admin + user_room_<id>).
    #                When `SOCKET_SCOPED_EMIT=true`, dispatcher fails closed if a
    #                sensitive event reaches `_emit_domain_event` without rooms.
    # Default "sensitive" forces explicit opt-in for anything that should broadcast.
    privacy: Literal["public", "sensitive"] = "sensitive"

    # B2.1 (admission cold-cutover refactor) — outbox routing flags.
    # Both default False so existing 200+ events keep their current behaviour
    # (additive extension). Set to True only on the 12 ADMISSION_* milestone
    # events whose contracts demand them (PLAN §3.3.d table line 1644-1657).
    #
    # - `requires_outbox=True` → `dispatch_event()` (B2.3) MUST INSERT a
    #   `notification_outbox` row inside the caller's transaction; the worker
    #   beat task `dispatch_pending_outbox` (T0-4b) drains the queue with
    #   delivery guarantee. Caller does NOT receive a post-commit callback.
    # - `requires_outbox=False` → `dispatch_event()` returns a best-effort
    #   post-commit callback that the router awaits after `db.commit()`. Same
    #   semantics as the existing `safe_dispatch` path.
    # - `bypass_consent_check=True` → wrapper calls into `dispatch()` /
    #   `safe_dispatch()` with `skip_preference_check=True` for in-app + email
    #   only (Quy chế Bộ GD&ĐT bắt buộc thông báo). Zalo/SMS bypass is
    #   FUTURE-GATED — Q7 chốt 2026-05-01 calls for a legal flag (working
    #   name `zalo_template_approved`) that does NOT exist in the codebase
    #   yet. B2.3 (`dispatch_event` wrapper) and B2.4 / T0-4b (worker)
    #   either honor consent for Zalo/SMS until the flag ships, or wire
    #   the flag at that time. Do NOT skip Zalo/SMS consent based on
    #   `bypass_consent_check` alone.
    requires_outbox: bool = False
    bypass_consent_check: bool = False


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


def _is_safe_relative_link(link: str) -> bool:
    """Allow only same-origin relative app paths for notification links."""
    if not link:
        return False

    trimmed = link.strip()
    if not trimmed:
        return False
    if trimmed.startswith("//"):
        return False

    lowered = trimmed.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "http://", "https://")):
        return False

    return trimmed.startswith("/")


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
            # NOTE: ``is_self_action`` is intentionally NOT a ``variable``.
            # It's a *derived* field auto-injected by the dispatcher when
            # ``actor_id == officer_id`` — never produced by the
            # ``EventPayload.for_lead_assigned()`` builder. Listing it as a
            # variable would break the catalog↔payload parity test
            # (``test_metadata_vars_exist_in_payload``). It is exposed
            # below as a *condition field* so the wizard + validator
            # accept it in rule conditions, which is the only surface
            # admins interact with.
        ),
        # ``is_self_action`` is exposed as a condition field so the
        # admin wizard can offer it in the rule builder dropdown and the
        # rule-CRUD validator accepts ``{field: "is_self_action", ...}``
        # without rejecting it as unknown. Boolean operators only.
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS + (
            _cond(
                "is_self_action",
                "boolean",
                "Officer tự assign lead cho chính mình (dispatcher derives from actor_id == officer_id)",
                _OPS_BOOL,
            ),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
        dedup_key_template="lead:${lead_id}:assigned:${officer_id}",
        link_strategy="/leads/${lead_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        default_channels=("browser",),
        priority=30,
        link_strategy="/leads/${lead_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
            _var("lead_code", "string", "Mã lead pseudo (LEAD-{id})"),
            _var("major_name", "string", "Tên ngành đăng ký (tối đa 30 ký tự)", False),
            _var("created_date_vn", "string", "Ngày tạo VN (dd/mm/yyyy)", False),
        ),
        condition_fields=_ACTOR_CONDS + _LEAD_CONDS,
        default_resolver="unit_managers",
        allowed_resolvers=_LEAD_RESOLVERS,
        default_channels=("browser",),
        priority=80,
        link_strategy="/leads/${lead_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
            _var("scheduled_at", "datetime", "Thời gian hẹn (ISO)"),
            _var("minutes_until", "integer", "Số phút còn lại"),
            _var("scheduled_time_vn", "string", "Thời gian hẹn VN (dd/mm/yyyy HH:MM)"),
            _var("booking_code", "string", "Mã booking (CONS-{id})"),
            _var("lead_code", "string", "Mã lead pseudo (LEAD-{id})"),
            _var("major_name", "string", "Tên ngành (tối đa 30 ký tự)"),
        ),
        condition_fields=_LEAD_CONDS + _CONSULTATION_CONDS + (
            _cond("event.minutes_until", "integer", "Số phút còn lại", _OPS_NUM),
            _cond("event.scheduled_at", "datetime", "Thời gian hẹn", _OPS_NUM),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=_LEAD_RESOLVERS,
        # NOTE: prod runtime enriches this rule with a zalo action
        # (zalo_template_id=333738, external_resolver=lead_contact) via
        # admin UI — that per-action config cannot be expressed in the
        # catalog's channel-list-only schema. Seed default stays
        # browser-only; Zalo is a post-seed DB customization.
        default_channels=("browser",),
        priority=10,
        dedup_key_template="reminder:${lead_id}:${consultation_id}",
        link_strategy="/leads/${lead_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
            # officer_id intentionally omitted — LeadOwnerResolver uses DB lookup
            _var("major_program_name", "string", "Tên ngành", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=70,
        link_strategy="/admissions/${application_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_STATUS_CHANGED,
        category="application",
        display_name="Trạng thái hồ sơ thay đổi",
        description="Khi trạng thái hồ sơ thay đổi",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            # officer_id intentionally omitted — LeadOwnerResolver uses DB lookup
            _var("old_status", "string", "Trạng thái cũ"),
            _var("new_status", "string", "Trạng thái mới"),
            _var("actor_id", "integer", "ID người thực hiện"),
            # enroll-specific extras (only present when new_status=enrolled)
            _var("student_id", "integer", "ID sinh viên (chỉ khi nhập học)", False),
            _var("student_code", "string", "Mã sinh viên (chỉ khi nhập học)", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=80,
        dedup_key_template="app:${application_id}:status:${new_status}",
        link_strategy="/admissions/${application_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_DELETED,
        category="application",
        display_name="Hồ sơ bị xóa",
        description="Khi hồ sơ bị xóa khỏi hệ thống",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            # officer_id intentionally omitted — LeadOwnerResolver uses DB lookup
            _var("lead_name", "string", "Tên lead", False),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser",),
        priority=100,
        link_strategy="/admissions",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_FEE_PAID,
        category="application",
        display_name="Lệ phí xét tuyển đã thanh toán",
        description="Khi lệ phí xét tuyển được xác nhận thanh toán",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị phụ trách", False),
            _var("officer_id", "integer", "ID officer phụ trách", False),
            _var("amount", "string", "Số tiền lệ phí"),
            _var("transaction_id", "string", "Mã giao dịch", False),
            _var("actor_id", "integer", "ID người thực hiện"),
            _var("actor_name", "string", "Tên người thực hiện", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser",),
        priority=75,
        dedup_key_template="app:${application_id}:fee_paid",
        link_strategy="/admissions/${application_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.APPLICATION_SURVEY_DUE,
        category="application",
        display_name="Khảo sát dịch vụ tư vấn sau duyệt 30 ngày",
        description="Scheduler gửi ZNS 426903 cho applicant sau khi hồ sơ được duyệt 30 ngày",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead (cho lead_contact resolver)"),
            _var("full_name", "string", "Họ tên applicant (≤30 ký tự)"),
            _var("program_name", "string", "Tên ngành (≤30 ký tự)"),
            _var("profile_code", "string", "Mã hồ sơ (≤30 ký tự)"),
            _var("submitted_date_vn", "string", "Ngày nộp DD/MM/YYYY"),
            _var("tracking_id", "string", "UUID echo-back cho user_feedback webhook"),
        ),
        # Applicant-only survey. No internal audience — there is no officer /
        # manager notification on this event. External delivery is wired per
        # action.config.external_resolver="lead_contact" on the ZNS rule row.
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        default_channels=("zalo",),
        priority=50,
        dedup_key_template="survey_due:${application_id}",
        link_strategy=None,
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    # ADM-028 (2026-04-29): magic-link expiry reminders. Beat task fires
    # at ~24h and ~6h before the token expires for unconfirmed approved
    # profiles. Per-token dedupe via reminder_24h_sent_at /
    # reminder_6h_sent_at columns on AdmissionConfirmationToken.
    EventDefinition(
        event=SystemEvents.ADMISSION_CONFIRMATION_REMINDER_24H,
        category="application",
        display_name="Nhắc xác nhận nhập học (còn ~24 giờ)",
        description=(
            "Beat task gửi nhắc applicant ~24h trước khi liên kết xác nhận hết hạn. "
            "One-shot per token, dedupe qua reminder_24h_sent_at."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead (cho lead_contact resolver)"),
            _var("lead_name", "string", "Họ tên applicant"),
            _var("expires_at_iso", "string", "ISO datetime — token expiry"),
            _var("hours_remaining", "integer", "Số giờ còn lại trước expiry"),
            _var("confirm_url", "string", "URL magic-link trực tiếp"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        default_channels=("email", "zalo"),
        priority=30,
        # Dedupe must include ``expires_at_iso`` so a refreshed token
        # (different expiry window) gets a fresh reminder. Keying on
        # ``application_id`` alone would let a previously-fired
        # reminder block delivery for a re-issued link in the same
        # 24h scan, even after the beat task cleared
        # ``reminder_24h_sent_at`` on the new row.
        dedup_key_template="confirm_reminder_24h:${application_id}:${expires_at_iso}",
        link_strategy=None,
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.ADMISSION_CONFIRMATION_REMINDER_6H,
        category="application",
        display_name="Nhắc xác nhận nhập học (còn ~6 giờ)",
        description=(
            "Beat task gửi nhắc applicant ~6h trước khi liên kết xác nhận hết hạn. "
            "One-shot per token, dedupe qua reminder_6h_sent_at. Có thể fire "
            "không cần 24h reminder đã fire trước đó (token issued <6h trước expiry)."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Họ tên applicant"),
            _var("expires_at_iso", "string", "ISO datetime — token expiry"),
            _var("hours_remaining", "integer", "Số giờ còn lại"),
            _var("confirm_url", "string", "URL magic-link"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        default_channels=("email", "zalo"),
        priority=20,
        # Same per-issuance-window keying as the 24h variant —
        # see comment there.
        dedup_key_template="confirm_reminder_6h:${application_id}:${expires_at_iso}",
        link_strategy=None,
        privacy="sensitive",
    ),
    # ADM-023 (2026-04-29): hard-lock awareness. Internal-only fanout
    # so support can proactively reach out when an applicant has been
    # hard-locked (≥30 failed CCCD attempts, lock_count incremented).
    EventDefinition(
        event=SystemEvents.ADMISSION_CONFIRMATION_HARD_LOCKED,
        category="application",
        display_name="Liên kết xác nhận bị khóa (≥30 lần sai CCCD)",
        description=(
            "Service raise khi applicant nhập sai CCCD ≥30 lần. Operator "
            "(officer/manager/admin) nhận notification để chủ động hỗ trợ."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("token_id", "integer", "ID confirmation token"),
            _var("attempt_count", "integer", "Tổng số lần nhập sai"),
            _var("lock_count", "integer", "Số lần token bị hard-lock"),
            _var("locked_at_iso", "string", "Thời điểm hard lock"),
            _var("lead_id", "integer", "ID lead"),
            _var("lead_name", "string", "Họ tên applicant"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=10,
        dedup_key_template="confirm_hard_locked:${token_id}:${lock_count}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
    ),

    # =========================================================================
    # B2.1 — admission cold-cutover refactor: 12 milestone events.
    # See `Documents/ADMISSION_REFACTOR_PLAN.md` §3.3.d table line 1644-1657
    # (audience / outbox / bypass_consent matrix). 7 events carry
    # `requires_outbox=True`; 5 of those carry `bypass_consent_check=True`.
    # All keep `category="application"` so admin notification UI groups them
    # with the existing application/profile lifecycle events.
    # =========================================================================

    # 1. T1 — candidate submits profile.
    EventDefinition(
        event=SystemEvents.ADMISSION_PROFILE_SUBMITTED,
        category="application",
        display_name="Hồ sơ tuyển sinh đã nộp",
        description="Candidate submitted an admission profile (T1). Officer + candidate audience.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("submitted_at_iso", "string", "ISO datetime when submit landed"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=80,
        dedup_key_template="admission:${application_id}:submitted",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=False,
        bypass_consent_check=False,
    ),

    # 2. T3, T4 — officer asks for revision.
    EventDefinition(
        event=SystemEvents.ADMISSION_REVISION_REQUESTED,
        category="application",
        display_name="Yêu cầu bổ sung hồ sơ",
        description="Officer requested a revision (T3 from reviewing, T4 from submitted). Candidate audience.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("revision_reason", "string", "Lý do yêu cầu chỉnh sửa"),
            _var("allowed_fields", "array", "Field paths candidate được sửa", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=70,
        dedup_key_template="admission:${application_id}:revision_requested",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=False,
        bypass_consent_check=False,
    ),

    # 3. T5 — candidate resubmits after revision.
    EventDefinition(
        event=SystemEvents.ADMISSION_RESUBMITTED,
        category="application",
        display_name="Hồ sơ đã được nộp lại",
        description="Candidate resubmitted after revision (T5). Officer audience.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("resubmit_notes", "string", "Ghi chú khi nộp lại", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=80,
        dedup_key_template="admission:${application_id}:resubmitted",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=False,
        bypass_consent_check=False,
    ),

    # 4. T6 — admin publishes admission result (broadcast batch).
    EventDefinition(
        event=SystemEvents.ADMISSION_RESULT_PUBLISHED,
        category="application",
        display_name="Công bố kết quả tuyển sinh",
        description="Admin published the admission result batch (T6). Officer + candidate audience. Critical: outbox + bypass consent.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("published_at_iso", "string", "ISO datetime kết quả công bố"),
            _var("decision_summary", "string", "Tóm tắt quyết định (admitted/waitlisted/rejected)", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:result_published",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=True,
    ),

    # 5. T7 — system marks profile admitted (per-profile after T6 batch).
    EventDefinition(
        event=SystemEvents.ADMISSION_DECISION_ADMITTED,
        category="application",
        display_name="Trúng tuyển",
        description="System marked profile admitted (T7). Candidate audience. Critical: outbox + bypass consent.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("choice_priority", "integer", "NV thứ mấy được trúng (1..5)", False),
            _var("path_id", "integer", "ID admission_path trúng", False),
            _var("total_score", "string", "Điểm tổng kết", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=10,
        dedup_key_template="admission:${application_id}:admitted:${choice_priority}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=True,
    ),

    # 6. T8 — system marks profile waitlisted.
    EventDefinition(
        event=SystemEvents.ADMISSION_DECISION_WAITLISTED,
        category="application",
        display_name="Trong danh sách dự bị",
        description="System marked profile waitlisted (T8). Candidate audience. Critical: outbox + bypass consent.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("waitlist_rank", "integer", "Thứ hạng dự bị", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:waitlisted",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=True,
    ),

    # 7. T9 — system marks profile rejected.
    EventDefinition(
        event=SystemEvents.ADMISSION_DECISION_REJECTED,
        category="application",
        display_name="Không trúng tuyển",
        description="System marked profile rejected (T9). Candidate audience. Critical: outbox + bypass consent.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("reject_reason_codes", "array", "Mã lý do từ chối", False),
            _var("from_waitlist", "boolean", "True khi từ waitlist → rejected (T11 gộp T9)", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:rejected",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=True,
    ),

    # 8. T10 — admin promotes waitlist → admitted.
    EventDefinition(
        event=SystemEvents.ADMISSION_WAITLIST_PROMOTED,
        category="application",
        display_name="Được gọi từ danh sách dự bị",
        description="Admin promoted waitlisted profile to admitted (T10). Candidate audience. Outbox guaranteed; consent honored.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("promoted_at_iso", "string", "ISO datetime promote"),
            _var("path_id", "integer", "ID admission_path trúng", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:waitlist_promoted",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),

    # 8b. T11 — admin finalizes waitlist → rejected (Wave 5 ship 2026-05-16).
    # Source-aware distinct from generic ADMISSION_DECISION_REJECTED (T9
    # engine cascade). Manager/admin manually reject 1 waitlisted choice
    # khi đợt closes + slot không mở. Notification rule unwired by default
    # (operator must seed via /admin/notification-rules); fail-closed at
    # dispatcher per T9 pattern.
    EventDefinition(
        event=SystemEvents.ADMISSION_WAITLIST_REJECTED,
        category="application",
        display_name="Bị loại khỏi danh sách dự bị",
        description="Admin finalized waitlisted profile to rejected (T11). Candidate audience. Outbox guaranteed; consent honored.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("rejected_at_iso", "string", "ISO datetime reject"),
            _var("reason", "string", "Lý do reject (audit)"),
            _var("path_id", "integer", "ID admission_path bị reject", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:waitlist_rejected",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),

    # 9. T12 — candidate / officer / admin confirms admission.
    EventDefinition(
        event=SystemEvents.ADMISSION_CONFIRMED,
        category="application",
        display_name="Xác nhận nhập học",
        description=(
            "Confirm action landed (T12). Officer audience. Distinct from "
            "ADMISSION_CONFIRMATION_REMINDER_* / _HARD_LOCKED (those are reminder/"
            "lock awareness signals). `confirmed_via` matches CHECK enum: "
            "'magic_link' / 'officer' / 'admin_override'."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("confirmed_via", "string", "magic_link / officer / admin_override"),
            _var("actor_id", "integer", "ID người xác nhận", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=60,
        dedup_key_template="admission:${application_id}:confirmed",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=False,
        bypass_consent_check=False,
    ),

    # 10. T13 — system enrolls confirmed profile (Student row created).
    EventDefinition(
        event=SystemEvents.ADMISSION_ENROLLED,
        category="application",
        display_name="Đã nhập học",
        description="System enrolled the confirmed profile (T13). Officer + candidate audience. Critical: outbox + bypass consent.",
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("student_id", "integer", "ID sinh viên mới"),
            _var("enrolled_at_iso", "string", "ISO datetime enroll"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="admission:${application_id}:enrolled",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=True,
    ),

    # 11. T14 / T15 / T16 — withdrawal (varies by from_status).
    EventDefinition(
        event=SystemEvents.ADMISSION_WITHDRAWN,
        category="application",
        display_name="Hồ sơ đã rút",
        description=(
            "Profile withdrawn (T14 from admitted / T15 from confirmed / "
            "T16 from enrolled). Officer audience. `withdrawn_by_role` "
            "discriminates self-service vs admin override."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("from_status", "string", "Trạng thái trước khi rút"),
            _var("withdrawn_by_role", "string", "candidate / admin"),
            _var("reason", "string", "Lý do (bắt buộc khi role != candidate)", False),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=70,
        dedup_key_template="admission:${application_id}:withdrawn",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=False,
        bypass_consent_check=False,
    ),

    # 12. T17 — admin override rollback (wildcard from any state to draft).
    EventDefinition(
        event=SystemEvents.ADMISSION_ROLLED_BACK,
        category="application",
        display_name="Hồ sơ đã được khôi phục về nháp (admin)",
        description=(
            "Admin override rollback to draft (T17 wildcard). Officer + "
            "candidate audience. Outbox guaranteed; consent honored. "
            "Per Q1 chốt: T17 from enrolled is rejected at the service "
            "guard — only states <= confirmed can be rolled back."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("from_status", "string", "Trạng thái trước rollback"),
            _var("override_reason", "string", "Lý do override (bắt buộc)"),
            _var("actor_id", "integer", "ID admin thực hiện"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=30,
        dedup_key_template="admission:${application_id}:rolled_back:${from_status}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),

    # =========================================================================
    # Q9 #07 Phase E — Priority bonus override events (3 events)
    # =========================================================================

    # 13. Officer/admin manually overrides KV (M1 ambiguous, lớp tạo nguồn, etc.)
    EventDefinition(
        event=SystemEvents.PRIORITY_KV_OVERRIDDEN,
        category="application",
        display_name="Khu vực ưu tiên đã được cập nhật thủ công",
        description=(
            "Officer/admin manually overrides candidate's KV via "
            "POST /api/v2/admissions/{id}/override-priority-kv (Phase E.2). "
            "Use cases: M1 ambiguous tiebreak, lớp tạo nguồn, quân nhân MAX "
            "KV, admin post-T6 correction. Candidate sees update với rationale."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("actor_id", "integer", "ID officer/admin"),
            _var("actor_name", "string", "Tên cán bộ"),
            _var("kv_resolved", "string", "KV mới (KV1/KV2-NT/KV2/KV3)"),
            _var("override_reason", "string", "Lý do override (≥20 ký tự)"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=70,
        dedup_key_template="priority:${application_id}:kv_overridden:${kv_resolved}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),

    # 14. Officer verifies UT đối tượng ưu tiên evidence.
    EventDefinition(
        event=SystemEvents.PRIORITY_OBJECT_VERIFIED,
        category="application",
        display_name="Đối tượng ưu tiên đã được xác minh",
        description=(
            "Officer verifies candidate's UT evidence via "
            "PATCH /api/v2/admissions/{id}/priority-objects/{sub_code}/verify "
            "(Phase E.3). Bonus will count in T6 engine cascade. Candidate "
            "receives positive confirmation."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("actor_id", "integer", "ID officer"),
            _var("actor_name", "string", "Tên cán bộ"),
            _var("sub_code", "string", "Mã UT (vd '04', '06')"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email"),
        priority=60,
        dedup_key_template="priority:${application_id}:ut_verified:${sub_code}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),

    # 15. Officer rejects UT evidence — candidate must re-upload.
    EventDefinition(
        event=SystemEvents.PRIORITY_OBJECT_REJECTED,
        category="application",
        display_name="Minh chứng đối tượng ưu tiên bị từ chối",
        description=(
            "Officer rejects UT evidence via PATCH /api/v2/admissions/{id}/"
            "priority-objects/{sub_code}/reject (Phase E.3). Bonus removed "
            "from T6 cascade. Candidate must re-upload with valid document. "
            "Zalo channel included for urgency."
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("actor_id", "integer", "ID officer"),
            _var("actor_name", "string", "Tên cán bộ"),
            _var("sub_code", "string", "Mã UT bị từ chối"),
            _var("reject_reason", "string", "Lý do từ chối (≥10 ký tự, hiển thị candidate)"),
        ),
        default_resolver="lead_owner",
        allowed_resolvers=("lead_owner", "unit_managers", "all_admins", "specific_users"),
        default_channels=("browser", "email", "zalo"),
        priority=75,
        dedup_key_template="priority:${application_id}:ut_rejected:${sub_code}",
        link_strategy="/admissions/${application_id}",
        privacy="sensitive",
        requires_outbox=True,
        bypass_consent_check=False,
    ),
)

# -------------------------------------------------------------------
# 4. Finance events — user (6) + internal_future (2)
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.PAYMENT_REJECTED,
        category="finance",
        display_name="Thanh toán bị từ chối",
        description="Khi checker từ chối một khoản thanh toán đang chờ",
        variables=(
            _var("payment_id", "integer", "ID thanh toán"),
            _var("invoice_id", "integer", "ID hóa đơn"),
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "string", "Số tiền"),
            _var("rejection_reason", "string", "Lý do từ chối"),
            _var("rejected_by_id", "integer", "ID người từ chối"),
            _var("created_by_id", "integer", "ID người ghi nhận"),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("user_id", "integer", "ID maker (recipient)"),
        ),
        default_resolver="specific_users",  # resolves via payload["user_id"] → maker
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=65,
        dedup_key_template="payment:${payment_id}:rejected",
        link_strategy="/finance/payments/${payment_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    # PR 8: FEE_FULLY_PAID — fires when fee reaches zero balance
    EventDefinition(
        event=SystemEvents.FEE_FULLY_PAID,
        category="finance",
        display_name="Học phí thanh toán đủ",
        description="Khi toàn bộ học phí của một kỳ đã được thanh toán đủ",
        variables=(
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "string", "Tổng học phí"),
            _var("semester_no", "integer", "Số kỳ học", False),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("user_id", "integer", "ID officer (recipient)"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=50,
        dedup_key_template="fee:${fee_id}:fully_paid",
        link_strategy="/finance/fees/${fee_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    # PR 8: INVOICE_ISSUED — fires when invoice transitions to issued
    EventDefinition(
        event=SystemEvents.INVOICE_ISSUED,
        category="finance",
        display_name="Hóa đơn được phát hành",
        description="Khi hóa đơn chuyển sang trạng thái phát hành",
        variables=(
            _var("invoice_id", "integer", "ID hóa đơn"),
            _var("invoice_number", "string", "Số hóa đơn"),
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "string", "Số tiền (raw Decimal string)"),
            _var("due_date", "datetime", "Hạn thanh toán (ISO)", False),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("user_id", "integer", "ID officer (recipient)"),
            _var("profile_code", "string", "Mã hồ sơ pseudo (HS-{id})"),
            _var("lead_full_name", "string", "Họ tên lead (tối đa 30 ký tự)", False),
            _var("major_name", "string", "Tên ngành (tối đa 30 ký tự)", False),
            _var("degree_level", "string", "Trình độ (Cao đẳng / Đại học)", False),
            _var("amount_vnd", "string", "Số tiền VND dạng integer (không decimal)"),
            _var("due_date_vn", "string", "Hạn thanh toán VN (dd/mm/yyyy)", False),
            _var("bank_transfer_note", "string", "Nội dung chuyển khoản (ASCII, ≤90)", False),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=55,
        dedup_key_template="invoice:${invoice_id}:issued",
        link_strategy="/finance/invoices/${invoice_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    # PR 8: PAYMENT_OVERDUE promoted from internal_future to user
    EventDefinition(
        event=SystemEvents.PAYMENT_OVERDUE,
        category="finance",
        display_name="Thanh toán quá hạn",
        description="Khi hóa đơn quá hạn thanh toán (invoice-level)",
        variables=(
            _var("invoice_id", "integer", "ID hóa đơn"),
            _var("invoice_number", "string", "Số hóa đơn"),
            _var("fee_id", "integer", "ID phí"),
            _var("fee_type", "string", "Loại phí"),
            _var("semester_no", "integer", "Số kỳ học", False),
            _var("amount", "string", "Số tiền còn nợ"),
            _var("due_date", "datetime", "Hạn thanh toán"),
            _var("days_overdue", "integer", "Số ngày quá hạn"),
            _var("days_overdue_bucket", "string", "Khung quá hạn: 1/7/14/30/30+ (window, not exact day)"),
            _var("installment_no", "integer", "Đợt thanh toán"),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("user_id", "integer", "ID officer (recipient)"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=20,
        dedup_key_template="overdue:${invoice_id}:${days_overdue_bucket}",
        link_strategy="/finance/fees/${fee_id}",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
)

_FINANCE_FUTURE_EVENTS: tuple = (
    EventDefinition(
        event=SystemEvents.REFUND_PROCESSED,
        category="finance",
        display_name="Hoàn tiền đã xử lý",
        description="Khi yêu cầu hoàn tiền đã được thực hiện (funds returned)",
        variables=(
            _var("refund_id", "integer", "ID yêu cầu hoàn tiền"),
            _var("payment_id", "integer", "ID thanh toán gốc"),
            _var("invoice_id", "integer", "ID hóa đơn"),
            _var("fee_id", "integer", "ID phí"),
            _var("amount", "string", "Số tiền hoàn"),
            _var("reason", "string", "Lý do hoàn tiền"),
            _var("processor_id", "integer", "ID người xử lý"),
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("unit_id", "integer", "ID đơn vị"),
            _var("user_ids", "array", "Recipients (officer + processor)"),
        ),
        default_resolver="specific_users",  # resolves via payload["user_ids"] → [officer, processor]
        allowed_resolvers=_FINANCE_RESOLVERS,
        default_channels=("browser", "email"),
        priority=55,
        dedup_key_template="refund:${refund_id}:processed",
        link_strategy="/finance/payments/${payment_id}",
        # PR A: dispatch site is wired in payment_service.process_approved_refund()
        # but RefundService has no router endpoint yet — the entire refund
        # flow (request, approve, process) is service-layer-only as of this
        # commit. Mark internal_future so the user-event contract test does
        # not require a reachable production caller. Promote to "user" class
        # when the refund router ships (tracked as PR B or later follow-up).
        notification_class="internal_future",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    # PAYMENT_OVERDUE promoted to _FINANCE_USER_EVENTS in PR 8
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
)

# -------------------------------------------------------------------
# 6. System + Security events (8 entries)
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
        # Sensitive by contract: SYSTEM_ALERT supports both per-user sends
        # (dispatch_system_alert) and admin-triggered broadcasts. Both
        # paths MUST pass explicit rooms — per-user resolves to
        # user_room_<id>, admin broadcast resolves to the full role
        # matrix. Classifying as "public" would let a misuse at any
        # call site leak admin-authored payloads to connected clients
        # with no scope check.
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.NOTIFICATION_HEALTH_ALERT,
        category="system",
        display_name="Cảnh báo sức khỏe hệ thống thông báo",
        description=(
            "Tín hiệu vận hành dành riêng cho admin về sức khỏe phân phối "
            "thông báo (failure rate, backlog, webhook lag, circuit breaker)"
        ),
        variables=(
            _var("severity", "string", "Mức độ nghiêm trọng"),
            _var("message", "string", "Nội dung cảnh báo"),
            _var("alert_type", "string", "Loại cảnh báo", False),
        ),
        # Admin-only operational signal — NOT a user broadcast. Mirrors
        # HOLIDAY_CALENDAR_INCOMPLETE's admin-scoped resolver set so the
        # health task can never fan out to all_users.
        default_resolver="all_admins",
        allowed_resolvers=_ADMIN_RESOLVERS,
        # browser + email (no zalo_bot — group SYSTEM defaults zalo_bot=False).
        default_channels=("browser", "email"),
        priority=10,
        # Sensitive: the dispatch site passes explicit rooms=["role_admin"]
        # so it clears the fail-closed socket guard. Classifying public would
        # let any misuse leak operational payloads to all connected clients.
        privacy="sensitive",
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
        # Holiday calendar config — meant for all admins, no PII
        privacy="public",
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
        # System-wide announcement — intended broadcast, no lead/user PII
        privacy="public",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.USER_PROFILE_UPDATED,
        category="system",
        display_name="Cập nhật hồ sơ người dùng",
        description="Khi admin cập nhật hồ sơ người dùng",
        variables=(
            _var("user_id", "integer", "ID user"),
            _var("updated_fields", "string", "Các trường thay đổi"),
            _var("actor_id", "integer", "ID người thực hiện"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        default_channels=("browser",),
        priority=40,
        link_strategy="/profile",
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Pipeline config metadata — no PII, all admins need realtime sync
        privacy="public",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
    ),
    EventDefinition(
        event=SystemEvents.ZALO_BOT_LINK_DISPLACED,
        category="security",
        display_name="Liên kết Zalo Bot bị thay thế",
        description=(
            "Khi chat_id Zalo Bot của bạn được liên kết bởi một tài khoản "
            "QLTS khác — bạn sẽ ngừng nhận thông báo qua Zalo cho đến khi "
            "thiết lập lại liên kết."
        ),
        variables=(
            _var("user_id", "integer", "ID user bị displace (recipient)"),
            _var("displaced_by_user_id", "integer", "ID user mới chiếm liên kết"),
            _var("chat_id_prefix", "string", "Prefix chat_id (đã mask)", False),
            _var("actor_id", "integer", "ID user mới (actor)"),
        ),
        default_resolver="specific_users",
        allowed_resolvers=("specific_users",),
        # Browser-only by default per design decision (minimal blast).
        # Admin có thể thêm channel email qua /admin/notification-rules
        # nếu muốn cảnh báo mạnh hơn.
        default_channels=("browser",),
        priority=10,
        # Dedup key includes chat_id_prefix (and not just the user pair)
        # because a single (displaced_user, new_user) pair can legitimately
        # produce multiple events: A links chat_X → B displaces A → A
        # re-links chat_Y → B displaces A again. Without chat_id_prefix
        # the second notification would be suppressed by the 5-minute
        # cooldown (NOTIFICATION_COOLDOWN_SECONDS) — leaving A unaware
        # of the second hijack.
        dedup_key_template=(
            "security:${user_id}:zalo_bot_link_displaced:"
            "${displaced_by_user_id}:${chat_id_prefix}"
        ),
        link_strategy="/settings/notifications",
        # Sensitive: contains targeted recipient + potential security event
        privacy="sensitive",
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
        # Org structure CRUD — no lead/applicant PII, safe to broadcast globally
        privacy="public",
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
        link_strategy="/leads/${lead_id}",
        notification_class="broadcast_only",
        # LEAD_UPDATED carries lead_id + updated_fields → must scope to unit/officer
        # even though notification_class says broadcast_only (broadcast_only = no persistence, not no-scoping).
        privacy="sensitive",
    ),
    # PR #8 — realtime cache invalidation for admission detail + finance
    # dashboard after POST /api/fees/calculate. No DB rule (broadcast_only),
    # but carries lead/profile IDs → must scope to unit + owning officer.
    EventDefinition(
        event=SystemEvents.FEE_CALCULATED,
        category="finance",
        display_name="Đã tính học phí",
        description="Realtime sync cho admission detail sau khi tính phí",
        variables=(
            _var("admission_profile_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("fee_id", "integer", "ID phí"),
            _var("fee_status", "string", "Trạng thái fee mới tạo"),
            _var(
                "lead_stage_changed",
                "boolean",
                "Lead pipeline stage đổi sau khi tính phí",
            ),
            _var("actor_id", "integer", "ID người tính phí"),
        ),
        link_strategy="/admissions/${admission_profile_id}",
        notification_class="broadcast_only",
        # Sensitive: payload carries lead/profile/fee IDs linked to PII.
        privacy="sensitive",
    ),
    # Realtime cache hint emitted after a post-approval minor correction.
    # Same broadcast-only treatment as FEE_CALCULATED — no DB rule, no
    # seeded notification, just a socket signal so other sessions
    # viewing the profile re-fetch. Payload deliberately carries field
    # NAMES only (changed_fields), never values, so the broadcast itself
    # leaks no PII; old/new values stay behind the audit-log RBAC gate.
    EventDefinition(
        event=SystemEvents.APPLICATION_MINOR_CORRECTED,
        category="application",
        display_name="Hồ sơ được hiệu chỉnh sau duyệt",
        description=(
            "Realtime sync cho admission detail sau khi sửa thông tin "
            "nhỏ trên hồ sơ approved/confirmed"
        ),
        variables=(
            _var("application_id", "integer", "ID hồ sơ"),
            _var("lead_id", "integer", "ID lead"),
            _var("changed_fields", "array", "Tên các trường đã đổi (no values)"),
            _var("actor_id", "integer", "ID người sửa"),
            _var("corrected_at", "string", "Thời gian sửa (ISO 8601)"),
        ),
        link_strategy="/admissions/${application_id}",
        notification_class="broadcast_only",
        # Sensitive: payload links to lead/profile rows even though
        # values are scrubbed — must be scoped to admin + unit + officer.
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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
        # Sensitive: contains lead/applicant/user/fee PII or targeted recipient
        privacy="sensitive",
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


def is_public_event(event: SystemEvents) -> bool:
    """
    True when the event is safe to broadcast globally via Socket.IO.

    Used by `notification_dispatcher._emit_domain_event` to enforce the
    fail-closed guard when `SOCKET_SCOPED_EMIT=true` — a sensitive event
    that reaches the emitter without explicit `rooms=` must be blocked
    rather than silently broadcast. Unknown events (missing from catalog)
    are treated as sensitive (safe default).
    """
    defn = EVENT_CATALOG.get(event)
    if defn is None:
        return False  # Unknown event → treat as sensitive
    return defn.privacy == "public"


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
    rendered = Template(defn.link_strategy).safe_substitute(payload).strip()
    if not _is_safe_relative_link(rendered):
        return None
    return rendered
