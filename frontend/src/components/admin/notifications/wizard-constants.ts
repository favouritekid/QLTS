// wizard-constants.ts — Fallback data for when backend metadata is unavailable.
// These are overridden at runtime by useNotificationMetadata() responses.

import type { ExternalResolverOption } from "./wizard-types";

// ============================================================================
// Types (used by constants below and wizard's useMemo hooks)
// ============================================================================

export interface EventOption {
  value: string;
  label: string;
  category: string;
  description: string;
  icon: string;
}

export interface RecipientOption {
  value: string;
  label: string;
  description: string;
}

export interface TemplateVariable {
  variable: string;
  label: string;
  description: string;
}

export const SUPPORTED_INTERNAL_RESOLVERS = [
  "lead_owner",
  "unit_staff",
  "unit_managers",
  "all_admins",
  "all_users",
  "specific_users",
  "collaborator_user",
] as const;

// ============================================================================
// System events — fallback when metadata.events is unavailable
// ============================================================================

export const SYSTEM_EVENTS: EventOption[] = [
  // Lead Events
  { value: "lead_created", label: "Có lead mới được tạo", category: "lead", description: "Khi một lead mới được tạo trong hệ thống", icon: "👤" },
  { value: "lead_assigned", label: "Lead được phân công", category: "lead", description: "Khi lead được gán cho cán bộ phụ trách", icon: "👤" },
  { value: "lead_assignment_failed", label: "Phân công lead thất bại", category: "lead", description: "Khi không thể tự động phân công lead (không có cán bộ hoặc đã đầy)", icon: "👤" },
  { value: "lead_reassigned", label: "Lead được chuyển giao", category: "lead", description: "Khi lead được chuyển sang đơn vị hoặc cán bộ khác", icon: "👤" },
  { value: "lead_status_changed", label: "Trạng thái lead thay đổi", category: "lead", description: "Khi lead chuyển sang giai đoạn khác trong pipeline", icon: "👤" },
  { value: "lead_deleted", label: "Lead bị xóa", category: "lead", description: "Khi lead bị xóa khỏi hệ thống", icon: "👤" },
  // Consultation Events
  { value: "consultation_created", label: "Có lịch tư vấn mới", category: "consultation", description: "Khi tạo lịch hẹn tư vấn cho lead", icon: "💬" },
  { value: "consultation_updated", label: "Lịch tư vấn được cập nhật", category: "consultation", description: "Khi thông tin lịch tư vấn được sửa đổi", icon: "💬" },
  { value: "consultation_deleted", label: "Lịch tư vấn bị hủy", category: "consultation", description: "Khi lịch tư vấn bị xóa", icon: "💬" },
  { value: "consultation_reminder", label: "Nhắc nhở lịch tư vấn", category: "consultation", description: "Tự động nhắc trước giờ tư vấn", icon: "💬" },
  // Application Events
  { value: "application_created", label: "Có hồ sơ mới được tạo", category: "application", description: "Khi lead nộp hồ sơ ứng tuyển", icon: "📝" },
  { value: "application_status_changed", label: "Trạng thái hồ sơ thay đổi", category: "application", description: "Khi trạng thái xử lý hồ sơ thay đổi", icon: "📝" },
  { value: "application_deleted", label: "Hồ sơ bị xóa", category: "application", description: "Khi hồ sơ bị xóa khỏi hệ thống", icon: "📝" },
  // Finance Events
  { value: "dorm_fee_created", label: "Có phí ký túc mới", category: "finance", description: "Khi tạo khoản phí ký túc cho sinh viên", icon: "💰" },
  { value: "payment_received", label: "Đã nhận thanh toán", category: "finance", description: "Khi ghi nhận thanh toán từ sinh viên", icon: "💰" },
  { value: "payment_overdue", label: "Thanh toán quá hạn", category: "finance", description: "Khi khoản thanh toán đã quá hạn", icon: "💰" },
  // Dorm Events
  { value: "dorm_room_assigned", label: "Phân phòng ký túc", category: "dorm", description: "Khi sinh viên được phân phòng ký túc", icon: "🏠" },
  { value: "dorm_maintenance_request", label: "Yêu cầu bảo trì ký túc", category: "dorm", description: "Khi có yêu cầu sửa chữa tại ký túc xá", icon: "🏠" },
  // Asset Events
  { value: "asset_maintenance_alert", label: "Cảnh báo bảo trì tài sản", category: "asset", description: "Khi tài sản cần bảo trì định kỳ", icon: "🔧" },
  { value: "asset_checked_out", label: "Tài sản được mượn", category: "asset", description: "Khi có người mượn tài sản", icon: "🔧" },
  // System Events
  { value: "system_alert", label: "Cảnh báo hệ thống", category: "system", description: "Thông báo quan trọng từ hệ thống", icon: "🔔" },
  { value: "system_announcement", label: "Thông báo chung", category: "system", description: "Thông báo chung cho toàn bộ người dùng", icon: "🔔" },
  { value: "user_role_changed", label: "Vai trò người dùng thay đổi", category: "system", description: "Khi quyền hạn của người dùng được thay đổi", icon: "🔔" },
  { value: "user_deactivated", label: "Tài khoản bị vô hiệu hóa", category: "system", description: "Khi tài khoản người dùng bị khóa", icon: "🔔" },
  { value: "pipeline_config_updated", label: "Cấu hình pipeline thay đổi", category: "system", description: "Khi admin thay đổi cấu hình quy trình", icon: "🔔" },
  { value: "officer_availability_changed", label: "Trạng thái cán bộ thay đổi", category: "system", description: "Khi cán bộ thay đổi trạng thái sẵn sàng", icon: "🔔" },
];

// ============================================================================
// Category display — UI labels, icons, sort order
// ============================================================================

export const CATEGORY_DISPLAY: Record<string, { label: string; icon: string; order: number }> = {
  lead:         { label: "Sự kiện Lead",      icon: "👤", order: 1 },
  consultation: { label: "Sự kiện Tư vấn",   icon: "💬", order: 2 },
  application:  { label: "Sự kiện Hồ sơ",    icon: "📝", order: 3 },
  finance:      { label: "Sự kiện Tài chính", icon: "💰", order: 4 },
  dorm:         { label: "Sự kiện Ký túc",    icon: "🏠", order: 5 },
  asset:        { label: "Sự kiện Tài sản",   icon: "🔧", order: 6 },
  pipeline:     { label: "Sự kiện Pipeline",  icon: "📊", order: 7 },
  operational:  { label: "Sự kiện Vận hành",  icon: "⚙️", order: 8 },
  security:     { label: "Sự kiện Bảo mật",   icon: "🔒", order: 9 },
  system:       { label: "Sự kiện Hệ thống",  icon: "🔔", order: 10 },
};

const FALLBACK_CATEGORY_ORDER = 999;

export function getCategoryIcon(category: string): string {
  return CATEGORY_DISPLAY[category]?.icon || "🔔";
}

export function getCategoryOrder(category: string): number {
  return CATEGORY_DISPLAY[category]?.order ?? FALLBACK_CATEGORY_ORDER;
}

// ============================================================================
// Recipient options — fallback when metadata.resolver_types is unavailable
// ============================================================================

export const RECIPIENT_OPTIONS: RecipientOption[] = [
  { value: "lead_owner", label: "Cán bộ phụ trách lead", description: "Gửi cho cán bộ đang được gán lead này" },
  { value: "unit_staff", label: "Nhân viên cùng đơn vị", description: "Gửi cho tất cả cán bộ trong cùng phòng/ban" },
  { value: "unit_managers", label: "Quản lý đơn vị", description: "Chỉ gửi cho các manager của đơn vị" },
  { value: "all_admins", label: "Tất cả Admin", description: "Gửi cho tất cả người dùng có quyền Admin" },
  { value: "all_users", label: "Tất cả người dùng", description: "Gửi broadcast cho toàn bộ người dùng trong hệ thống" },
  { value: "specific_users", label: "Người dùng cụ thể", description: "Chọn danh sách người nhận theo tên" },
  { value: "collaborator_user", label: "Cộng tác viên", description: "Gửi cho user liên kết với cộng tác viên" },
];

export const EXTERNAL_RESOLVER_FALLBACK: ExternalResolverOption[] = [
  { value: "lead_contact", label: "Lead (qua Zalo/SMS)", description: "Gửi cho lead qua SĐT" },
  { value: "admission_contact", label: "Hồ sơ tuyển sinh", description: "Gửi cho ứng viên" },
  { value: "collaborator_contact", label: "Cộng tác viên", description: "Gửi cho CTV" },
];

// ============================================================================
// Template variables — fallback when metadata.events[x].variables is unavailable
// ============================================================================

export const TEMPLATE_VARIABLES: Record<string, TemplateVariable[]> = {
  lead: [
    { variable: "$lead_name", label: "Tên lead", description: "Họ tên của lead" },
    { variable: "$lead_phone", label: "SĐT lead", description: "Số điện thoại" },
    { variable: "$lead_id", label: "ID lead", description: "Mã định danh lead" },
    { variable: "$officer_id", label: "ID cán bộ", description: "Mã cán bộ phụ trách" },
    { variable: "$unit_id", label: "ID đơn vị", description: "Mã đơn vị" },
    { variable: "$offering_name", label: "Tên chương trình", description: "Chương trình đào tạo" },
  ],
  consultation: [
    { variable: "$consultation_id", label: "ID tư vấn", description: "Mã lịch tư vấn" },
    { variable: "$lead_name", label: "Tên lead", description: "Tên người được tư vấn" },
    { variable: "$lead_phone", label: "SĐT lead", description: "Số điện thoại" },
    { variable: "$scheduled_at", label: "Thời gian hẹn", description: "Ngày giờ tư vấn" },
    { variable: "$minutes_until", label: "Phút còn lại", description: "Thời gian đến giờ hẹn" },
  ],
  application: [
    { variable: "$application_id", label: "ID hồ sơ", description: "Mã hồ sơ" },
    { variable: "$lead_id", label: "ID lead", description: "Mã lead nộp hồ sơ" },
    { variable: "$lead_name", label: "Tên lead", description: "Tên người nộp" },
    { variable: "$major_program_name", label: "Chương trình", description: "Ngành học" },
    { variable: "$old_status", label: "Trạng thái cũ", description: "Trạng thái trước đó" },
    { variable: "$new_status", label: "Trạng thái mới", description: "Trạng thái hiện tại" },
  ],
  finance: [
    { variable: "$amount", label: "Số tiền", description: "Số tiền thanh toán" },
    { variable: "$fee_id", label: "ID khoản phí", description: "Mã khoản phí" },
    { variable: "$payment_id", label: "ID thanh toán", description: "Mã giao dịch" },
    { variable: "$due_date", label: "Hạn thanh toán", description: "Ngày đến hạn" },
    { variable: "$days_overdue", label: "Số ngày trễ", description: "Số ngày quá hạn" },
  ],
  dorm: [
    { variable: "$dorm_id", label: "ID ký túc", description: "Mã KTX" },
    { variable: "$room_id", label: "ID phòng", description: "Mã phòng" },
    { variable: "$student_id", label: "ID sinh viên", description: "Mã SV" },
    { variable: "$priority", label: "Độ ưu tiên", description: "Mức độ khẩn cấp" },
  ],
  asset: [
    { variable: "$asset_id", label: "ID tài sản", description: "Mã tài sản" },
    { variable: "$asset_name", label: "Tên tài sản", description: "Tên thiết bị" },
    { variable: "$borrower_id", label: "ID người mượn", description: "Mã người mượn" },
    { variable: "$expected_return", label: "Ngày trả dự kiến", description: "Hạn trả" },
  ],
  system: [
    { variable: "$severity", label: "Mức độ", description: "Mức độ nghiêm trọng" },
    { variable: "$message", label: "Thông điệp", description: "Nội dung chi tiết" },
    { variable: "$old_role", label: "Vai trò cũ", description: "Quyền hạn trước" },
    { variable: "$new_role", label: "Vai trò mới", description: "Quyền hạn mới" },
    { variable: "$username", label: "Tên đăng nhập", description: "Username" },
  ],
};
