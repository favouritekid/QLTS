# app/core/event_metadata.py
"""
✅ NOTIFICATION 2.0 - PHASE 2: Event Metadata Registry

Central registry defining metadata for all system events. This is the "source of truth"
for notification variable definitions, making the frontend completely dynamic.

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
    default_channels: List[str] = field(default_factory=lambda: ["socket"])
    category: str = "general"


# =============================================================================
# ✅ EVENT METADATA REGISTRY - 27 EVENTS DEFINED
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
            EventVariable("lead_name", "string", "Tên lead", required=False),
            EventVariable("lead_phone", "string", "SĐT lead", required=False),
            EventVariable("offering_name", "string", "Tên ngành/chương trình", required=False),
        ],
        filter_fields=["lead_id", "officer_id", "actor_id"],
        default_channels=["socket", "email"],
        category="lead"
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
        ],
        filter_fields=["lead_id", "unit_id", "reason"],
        default_channels=["socket", "email"],
        category="lead"
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
            EventVariable("reason", "string", "Lý do chuyển giao", required=False),
        ],
        filter_fields=["lead_id", "old_officer_id", "new_officer_id", "old_unit_id", "new_unit_id"],
        default_channels=["socket", "email"],
        category="lead"
    ),

    SystemEvents.LEAD_STATUS_CHANGED: EventMetadata(
        event=SystemEvents.LEAD_STATUS_CHANGED,
        display_name="Trạng thái lead thay đổi",
        description="Khi lead chuyển sang giai đoạn khác trong pipeline",
        variables=[
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer phụ trách", required=False),
            EventVariable("old_status", "string", "Trạng thái cũ"),
            EventVariable("new_status", "string", "Trạng thái mới"),
            EventVariable("actor_id", "integer", "ID người thực hiện"),
        ],
        filter_fields=["lead_id", "officer_id", "old_status", "new_status"],
        default_channels=["socket"],
        category="lead"
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
        ],
        filter_fields=["lead_id", "unit_id", "source"],
        default_channels=["socket"],
        category="lead"
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
        ],
        filter_fields=["lead_id", "unit_id", "officer_id"],
        default_channels=["socket"],
        category="lead"
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
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id", "status_id"],
        default_channels=["socket"],
        category="consultation"
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
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id", "new_status_id"],
        default_channels=["socket"],
        category="consultation"
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
        ],
        filter_fields=["consultation_id", "lead_id", "officer_id"],
        default_channels=["socket"],
        category="consultation"
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
        default_channels=["socket", "email"],
        category="consultation"
    ),

    # =========================================================================
    # APPLICATION EVENTS (4 events)
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
        category="application"
    ),

    SystemEvents.APPLICATION_DOCUMENTS_UPDATED: EventMetadata(
        event=SystemEvents.APPLICATION_DOCUMENTS_UPDATED,
        display_name="Cập nhật tài liệu hồ sơ",
        description="Khi tài liệu hồ sơ được cập nhật",
        variables=[
            EventVariable("application_id", "integer", "ID hồ sơ"),
            EventVariable("lead_id", "integer", "ID của lead"),
            EventVariable("officer_id", "integer", "ID officer xử lý"),
            EventVariable("document_summary", "string", "Tóm tắt thay đổi", required=False),
            EventVariable("actor_id", "integer", "ID người cập nhật"),
        ],
        filter_fields=["application_id", "lead_id", "officer_id"],
        default_channels=["socket"],
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
        default_channels=["socket"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
        category="finance"
    ),

    SystemEvents.PAYMENT_OVERDUE: EventMetadata(
        event=SystemEvents.PAYMENT_OVERDUE,
        display_name="Thanh toán quá hạn",
        description="Khi thanh toán quá hạn",
        variables=[
            EventVariable("fee_id", "integer", "ID phí"),
            EventVariable("user_id", "integer", "ID người nợ"),
            EventVariable("amount", "integer", "Số tiền nợ"),
            EventVariable("days_overdue", "integer", "Số ngày quá hạn"),
            EventVariable("fee_type", "string", "Loại phí"),
        ],
        filter_fields=["fee_id", "user_id", "days_overdue", "fee_type"],
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket", "email"],
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
        default_channels=["socket"],
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
        default_channels=["socket"],
        category="operational"
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
            "category": metadata.category
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
