// src/components/admin/notifications/NotificationRuleWizard.tsx
/**
 * ✅ PHASE 2.4: Notification Rule Wizard
 *
 * Simplified wizard-style interface for creating notification rules.
 * Replaces the complex NotificationRuleForm with a 4-step guided process.
 *
 * Features:
 * - Auto-listing events from backend constants
 * - Clear recipient selection with examples
 * - Visual condition builder
 * - Template variable picker (no manual {{}} syntax)
 * - Contextual helpers and tooltips
 * - 100% Vietnamese interface
 * - Real-time preview
 */
"use client";

import { useState, useMemo, useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import * as z from "zod";
import {
  Loader2,
  Save,
  ChevronRight,
  ChevronLeft,
  HelpCircle,
  Bell,
  Users,
  Filter,
  MessageSquare,
  Sparkles,
  Check,
  ChevronsUpDown,
  Zap,
  Layers, // ✅ NOTIFICATION 2.0: Step 5 icon
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

import {
  useCreateNotificationRule,
  useUpdateNotificationRule,
  useNotificationRule,
  useNotificationMetadata, // ✅ NOTIFICATION 2.0: Dynamic metadata
} from "@/hooks/useNotificationRules";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { MultiStepActionEditor } from "./MultiStepActionEditor"; // ✅ NOTIFICATION 2.0

// ============================================
// TYPES & INTERFACES
// ============================================

interface EventOption {
  value: string;
  label: string;
  category: string;
  description: string;
  icon: string;
}

interface RecipientOption {
  value: string;
  label: string;
  description: string;
  example: string;
}

interface TemplateVariable {
  variable: string;
  label: string;
  description: string;
}

// ============================================
// FORM SCHEMA
// ============================================

// ✅ NOTIFICATION 2.0: Action schema for multi-step workflows
const actionSchema = z.object({
  step: z.number(),
  channel: z.string(),
  template_code: z.string().nullable().optional(),
  delay_minutes: z.number().optional(),
  config: z.record(z.string(), z.unknown()).nullable().optional(),
});

const formSchema = z.object({
  event: z.string().min(1, "Vui lòng chọn sự kiện"),
  title_template: z.string().min(1, "Vui lòng nhập tiêu đề"),
  message_template: z.string().min(1, "Vui lòng nhập nội dung"),
  notification_type: z.enum(["info", "success", "warning", "error"]),
  link_template: z.string().optional(),
  channels: z.array(z.string()).min(1, "Vui lòng chọn ít nhất một kênh"), // Fallback for backward compatibility
  recipient_config: z.record(z.string(), z.unknown()),
  condition: z.record(z.string(), z.unknown()).nullable(),
  enabled: z.boolean(),
  actions: z.array(actionSchema).optional(), // ✅ NOTIFICATION 2.0: Multi-step workflow
});

type FormValues = z.infer<typeof formSchema>;

// ============================================
// CONSTANTS - AUTO-LISTING EVENTS
// ============================================

/**
 * Danh sách sự kiện tự động từ backend
 * Được nhóm theo danh mục và có mô tả tiếng Việt
 */
const SYSTEM_EVENTS: EventOption[] = [
  // Lead Events
  {
    value: "lead_created",
    label: "Có lead mới được tạo",
    category: "lead",
    description: "Khi một lead mới được tạo trong hệ thống",
    icon: "👤",
  },
  {
    value: "lead_assigned",
    label: "Lead được phân công",
    category: "lead",
    description: "Khi lead được gán cho cán bộ phụ trách",
    icon: "👤",
  },
  {
    value: "lead_assignment_failed",
    label: "Phân công lead thất bại",
    category: "lead",
    description: "Khi không thể tự động phân công lead (không có cán bộ hoặc đã đầy)",
    icon: "👤",
  },
  {
    value: "lead_reassigned",
    label: "Lead được chuyển giao",
    category: "lead",
    description: "Khi lead được chuyển sang đơn vị hoặc cán bộ khác",
    icon: "👤",
  },
  {
    value: "lead_status_changed",
    label: "Trạng thái lead thay đổi",
    category: "lead",
    description: "Khi lead chuyển sang giai đoạn khác trong pipeline",
    icon: "👤",
  },
  {
    value: "lead_deleted",
    label: "Lead bị xóa",
    category: "lead",
    description: "Khi lead bị xóa khỏi hệ thống",
    icon: "👤",
  },

  // Consultation Events
  {
    value: "consultation_created",
    label: "Có lịch tư vấn mới",
    category: "consultation",
    description: "Khi tạo lịch hẹn tư vấn cho lead",
    icon: "💬",
  },
  {
    value: "consultation_updated",
    label: "Lịch tư vấn được cập nhật",
    category: "consultation",
    description: "Khi thông tin lịch tư vấn được sửa đổi",
    icon: "💬",
  },
  {
    value: "consultation_deleted",
    label: "Lịch tư vấn bị hủy",
    category: "consultation",
    description: "Khi lịch tư vấn bị xóa",
    icon: "💬",
  },
  {
    value: "consultation_reminder",
    label: "Nhắc nhở lịch tư vấn",
    category: "consultation",
    description: "Tự động nhắc trước giờ tư vấn",
    icon: "💬",
  },

  // Application Events
  {
    value: "application_created",
    label: "Có hồ sơ mới được tạo",
    category: "application",
    description: "Khi lead nộp hồ sơ ứng tuyển",
    icon: "📝",
  },
  {
    value: "application_status_changed",
    label: "Trạng thái hồ sơ thay đổi",
    category: "application",
    description: "Khi trạng thái xử lý hồ sơ thay đổi",
    icon: "📝",
  },
  {
    value: "application_deleted",
    label: "Hồ sơ bị xóa",
    category: "application",
    description: "Khi hồ sơ bị xóa khỏi hệ thống",
    icon: "📝",
  },

  // Finance Events
  {
    value: "dorm_fee_created",
    label: "Có phí ký túc mới",
    category: "finance",
    description: "Khi tạo khoản phí ký túc cho sinh viên",
    icon: "💰",
  },
  {
    value: "payment_received",
    label: "Đã nhận thanh toán",
    category: "finance",
    description: "Khi ghi nhận thanh toán từ sinh viên",
    icon: "💰",
  },
  {
    value: "payment_overdue",
    label: "Thanh toán quá hạn",
    category: "finance",
    description: "Khi khoản thanh toán đã quá hạn",
    icon: "💰",
  },

  // Dorm Events
  {
    value: "dorm_room_assigned",
    label: "Phân phòng ký túc",
    category: "dorm",
    description: "Khi sinh viên được phân phòng ký túc",
    icon: "🏠",
  },
  {
    value: "dorm_maintenance_request",
    label: "Yêu cầu bảo trì ký túc",
    category: "dorm",
    description: "Khi có yêu cầu sửa chữa tại ký túc xá",
    icon: "🏠",
  },

  // Asset Events
  {
    value: "asset_maintenance_alert",
    label: "Cảnh báo bảo trì tài sản",
    category: "asset",
    description: "Khi tài sản cần bảo trì định kỳ",
    icon: "🔧",
  },
  {
    value: "asset_checked_out",
    label: "Tài sản được mượn",
    category: "asset",
    description: "Khi có người mượn tài sản",
    icon: "🔧",
  },

  // System Events
  {
    value: "system_alert",
    label: "Cảnh báo hệ thống",
    category: "system",
    description: "Thông báo quan trọng từ hệ thống",
    icon: "🔔",
  },
  {
    value: "system_announcement",
    label: "Thông báo chung",
    category: "system",
    description: "Thông báo chung cho toàn bộ người dùng",
    icon: "🔔",
  },
  {
    value: "user_role_changed",
    label: "Vai trò người dùng thay đổi",
    category: "system",
    description: "Khi quyền hạn của người dùng được thay đổi",
    icon: "🔔",
  },
  {
    value: "user_deactivated",
    label: "Tài khoản bị vô hiệu hóa",
    category: "system",
    description: "Khi tài khoản người dùng bị khóa",
    icon: "🔔",
  },
  {
    value: "pipeline_config_updated",
    label: "Cấu hình pipeline thay đổi",
    category: "system",
    description: "Khi admin thay đổi cấu hình quy trình",
    icon: "🔔",
  },
  {
    value: "officer_availability_changed",
    label: "Trạng thái cán bộ thay đổi",
    category: "system",
    description: "Khi cán bộ thay đổi trạng thái sẵn sàng",
    icon: "🔔",
  },
];

/**
 * Nhóm sự kiện theo danh mục
 */
const EVENT_CATEGORIES = [
  { value: "lead", label: "Sự kiện Lead", icon: "👤" },
  { value: "consultation", label: "Sự kiện Tư vấn", icon: "💬" },
  { value: "application", label: "Sự kiện Hồ sơ", icon: "📝" },
  { value: "finance", label: "Sự kiện Tài chính", icon: "💰" },
  { value: "dorm", label: "Sự kiện Ký túc", icon: "🏠" },
  { value: "asset", label: "Sự kiện Tài sản", icon: "🔧" },
  { value: "system", label: "Sự kiện Hệ thống", icon: "🔔" },
];

/**
 * Danh sách người nhận với mô tả và ví dụ rõ ràng
 */
const RECIPIENT_OPTIONS: RecipientOption[] = [
  {
    value: "lead_owner",
    label: "Cán bộ phụ trách lead",
    description: "Gửi cho cán bộ đang được gán lead này",
    example: "VD: Khi có lịch tư vấn mới, gửi cho cán bộ phụ trách",
  },
  {
    value: "unit_staff",
    label: "Nhân viên cùng đơn vị",
    description: "Gửi cho tất cả cán bộ trong cùng phòng/ban",
    example: "VD: Manager tạo lead → Tất cả officers cùng phòng nhận thông báo",
  },
  {
    value: "unit_managers",
    label: "Quản lý đơn vị",
    description: "Chỉ gửi cho các manager của đơn vị",
    example: "VD: Phân công lead thất bại → Managers nhận để xử lý",
  },
  {
    value: "all_admins",
    label: "Tất cả Admin",
    description: "Gửi cho tất cả người dùng có quyền Admin",
    example: "VD: Cập nhật cấu hình hệ thống → Tất cả admins được thông báo",
  },
  {
    value: "all_users",
    label: "Tất cả người dùng",
    description: "Gửi broadcast cho toàn bộ người dùng trong hệ thống",
    example: "VD: Thông báo bảo trì hệ thống → Tất cả nhận thông báo",
  },
  {
    value: "specific_users",
    label: "Người dùng cụ thể",
    description: "Chọn danh sách người nhận theo tên",
    example: "VD: Gửi riêng cho một số người nhất định",
  },
  {
    value: "dorm_residents",
    label: "Sinh viên ở ký túc",
    description: "Gửi cho các sinh viên đang ở ký túc xá",
    example: "VD: Thông báo cắt điện → Tất cả sinh viên KTX nhận",
  },
  {
    value: "dorm_staff",
    label: "Nhân viên ký túc xá",
    description: "Gửi cho đội ngũ quản lý KTX",
    example: "VD: Yêu cầu sửa chữa → Bảo vệ/quản lý KTX nhận",
  },
];

/**
 * Loại thông báo
 */
const NOTIFICATION_TYPES = [
  {
    value: "info",
    label: "Thông tin",
    description: "Thông báo mang tính thông tin",
    color: "bg-info-100 text-info-800",
  },
  {
    value: "success",
    label: "Thành công",
    description: "Thông báo hành động thành công",
    color: "bg-success-100 text-success-800",
  },
  {
    value: "warning",
    label: "Cảnh báo",
    description: "Thông báo cần chú ý",
    color: "bg-warning-100 text-warning-800",
  },
  {
    value: "error",
    label: "Lỗi",
    description: "Thông báo lỗi hoặc thất bại",
    color: "bg-error-100 text-error-800",
  },
];

/**
 * Biến template theo sự kiện
 */
const TEMPLATE_VARIABLES: Record<string, TemplateVariable[]> = {
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

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * ✅ NOTIFICATION 2.0: Map category to icon emoji
 */
function getCategoryIcon(category: string): string {
  const iconMap: Record<string, string> = {
    lead: "👤",
    consultation: "💬",
    application: "📝",
    finance: "💰",
    dorm: "🏠",
    asset: "🔧",
    system: "🔔",
  };
  return iconMap[category] || "🔔";
}

// Phase 2: Canonical operator labels
const OPERATOR_LABELS: Record<string, string> = {
  eq: "Bằng (=)",
  ne: "Khác (≠)",
  gt: "Lớn hơn (>)",
  gte: "Lớn hơn hoặc bằng (≥)",
  lt: "Nhỏ hơn (<)",
  lte: "Nhỏ hơn hoặc bằng (≤)",
  in: "Trong danh sách",
  not_in: "Không trong danh sách",
  contains: "Chứa",
};

// Phase 2: Legacy operator alias map
const OPERATOR_ALIAS_MAP: Record<string, string> = {
  "==": "eq", "!=": "ne",
  ">": "gt", ">=": "gte",
  "<": "lt", "<=": "lte",
};

// Phase 2: Legacy flat field alias map (mirror of backend FIELD_ALIASES_GLOBAL)
// "unit_id" intentionally omitted — ambiguous, resolved event-aware below.
const FIELD_ALIAS_MAP: Record<string, string> = {
  new_status: "event.new_status_id",
  old_status: "event.old_status_id",
  old_stage: "event.old_stage_id",
  new_stage: "event.new_stage_id",
  lead_id: "lead.id",
  lead_name: "lead.name",
  officer_id: "lead.officer_id",
  actor_id: "actor.id",
  actor_name: "actor.name",
  consultation_id: "consultation.id",
  status_changed: "event.status_changed",
  updated_fields: "event.updated_fields",
};

// Phase 2: Event-aware alias for ambiguous fields
const FIELD_ALIAS_PER_EVENT: Record<string, Record<string, string>> = {
  lead_imported: { unit_id: "event.unit_id" },
};
const FIELD_ALIAS_DEFAULT: Record<string, string> = { unit_id: "lead.unit_id" };

function resolveFieldAlias(field: string, event: string): string {
  if (field in FIELD_ALIAS_MAP) return FIELD_ALIAS_MAP[field];
  const perEvent = FIELD_ALIAS_PER_EVENT[event] ?? FIELD_ALIAS_DEFAULT;
  return perEvent[field] ?? FIELD_ALIAS_DEFAULT[field] ?? field;
}

// ============================================
// HELPER COMPONENTS
// ============================================

/**
 * Helper tooltip hiển thị thông tin bổ sung
 */
function HelpTooltip({ content }: { content: string }) {
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <HelpCircle className="h-4 w-4 text-muted-foreground cursor-help inline-block ml-1" />
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-xs">
          <p className="text-sm">{content}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * Step indicator cho wizard
 */
function StepIndicator({ currentStep }: { currentStep: number }) {
  const steps = [
    { number: 1, label: "Sự kiện", icon: Bell },
    { number: 2, label: "Người nhận", icon: Users },
    { number: 3, label: "Điều kiện", icon: Filter },
    { number: 4, label: "Nội dung", icon: MessageSquare },
    { number: 5, label: "Quy trình", icon: Layers }, // ✅ NOTIFICATION 2.0: Multi-step workflow
  ];

  return (
    <div className="flex items-center justify-between mb-8">
      {steps.map((step, index) => {
        const Icon = step.icon;
        const isActive = currentStep === step.number;
        const isCompleted = currentStep > step.number;

        return (
          <div key={step.number} className="flex items-center flex-1">
            <div className="flex flex-col items-center flex-1">
              <div
                className={`
                  flex items-center justify-center w-10 h-10 rounded-full border-2 transition-colors
                  ${isActive ? "border-primary bg-primary text-primary-foreground" : ""}
                  ${isCompleted ? "border-success-500 bg-success-500 text-white" : ""}
                  ${!isActive && !isCompleted ? "border-muted-foreground/30 text-muted-foreground" : ""}
                `}
              >
                <Icon className="h-5 w-5" />
              </div>
              <span
                className={`
                  text-xs mt-1 font-medium
                  ${isActive ? "text-primary" : ""}
                  ${isCompleted ? "text-success-600" : ""}
                  ${!isActive && !isCompleted ? "text-muted-foreground" : ""}
                `}
              >
                {step.label}
              </span>
            </div>
            {index < steps.length - 1 && (
              <div
                className={`
                  h-0.5 flex-1 mx-2 mb-6 transition-colors
                  ${isCompleted ? "bg-success-500" : "bg-muted-foreground/20"}
                `}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ============================================
// MAIN COMPONENT
// ============================================

interface NotificationRuleWizardProps {
  ruleId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function NotificationRuleWizard({
  ruleId,
  open,
  onOpenChange,
  onSuccess,
}: NotificationRuleWizardProps) {
  const [currentStep, setCurrentStep] = useState(1);
  const isEditMode = !!ruleId;

  // User selection state (for specific_users recipient)
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [userPickerOpen, setUserPickerOpen] = useState(false);

  // Condition builder state
  const [conditionEnabled, setConditionEnabled] = useState(false);
  const [conditionField, setConditionField] = useState<string>("");
  const [conditionOperator, setConditionOperator] = useState<string>("eq");
  const [conditionValue, setConditionValue] = useState<string>("");
  const [isCompoundCondition, setIsCompoundCondition] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);

  // Fetch users for user picker
  const { data: usersData } = useAdminUsersList({
    page: 1,
    page_size: 100,
  });

  // ✅ NOTIFICATION 2.0: Fetch metadata for dynamic builder
  const { data: metadata } = useNotificationMetadata();

  // Fetch existing rule if in edit mode
  const { data: existingRule, isLoading: loadingRule } = useNotificationRule(ruleId);

  // Mutations
  const createMutation = useCreateNotificationRule();
  const updateMutation = useUpdateNotificationRule();

  // Form
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      event: "",
      title_template: "",
      message_template: "",
      notification_type: "info",
      link_template: "",
      channels: ["browser"], // ✅ Channel for in-browser notifications
      recipient_config: { resolver_type: "lead_owner", params: {} },
      condition: null,
      enabled: true,
      actions: [ // ✅ NOTIFICATION 2.0: Default single-step action
        {
          step: 1,
          channel: "browser",
          template_code: null,
          delay_minutes: 0,
          config: null,
        },
      ],
    },
  });

  // Phase 2: Hydrate form when editing existing rule
  useEffect(() => {
    if (!existingRule || !isEditMode) return;

    form.reset({
      event: existingRule.event,
      title_template: existingRule.title_template,
      message_template: existingRule.message_template,
      notification_type: existingRule.notification_type as "info" | "success" | "warning" | "error",
      link_template: existingRule.link_template ?? "",
      channels: existingRule.channels,
      recipient_config: existingRule.recipient_config,
      condition: existingRule.condition,
      enabled: existingRule.enabled,
      actions: existingRule.actions?.map((a: Record<string, unknown>) => ({
        step: a.step as number,
        channel: a.channel as string,
        template_code: (a.template_code as string) || null,
        delay_minutes: (a.delay_minutes as number) || 0,
        config: (a.config as Record<string, unknown>) || null,
      })) ?? [],
    });

    // Hydrate condition state
    if (existingRule.condition) {
      const cond = existingRule.condition as Record<string, unknown>;
      if ("conditions" in cond) {
        setConditionEnabled(true);
        setIsCompoundCondition(true);
      } else {
        setConditionEnabled(true);
        setIsCompoundCondition(false);
        const rawField = String(cond.field ?? "");
        setConditionField(resolveFieldAlias(rawField, existingRule.event));
        const rawOp = String(cond.operator ?? "eq");
        setConditionOperator(OPERATOR_ALIAS_MAP[rawOp] ?? rawOp);
        // Hydrate value — arrays become comma-separated, others toString
        const rawVal = cond.value;
        if (Array.isArray(rawVal)) {
          setConditionValue(rawVal.join(", "));
        } else {
          setConditionValue(String(rawVal ?? ""));
        }
      }
    }
    setIsHydrated(true);
  }, [existingRule, isEditMode]);

  // Watch form values for dynamic behavior
  const selectedEvent = form.watch("event");
  const selectedRecipient = form.watch("recipient_config.resolver_type") as string;
  const titleTemplate = form.watch("title_template");
  const messageTemplate = form.watch("message_template");

  // Phase 2: Reset condition state on event change (only if not hydrating)
  useEffect(() => {
    if (isEditMode && !isHydrated) return;
    setConditionField("");
    setConditionOperator("eq");
    setConditionValue("");
    setConditionEnabled(false);
    setIsCompoundCondition(false);
    form.setValue("condition", null);
  }, [selectedEvent]);

  // ✅ NOTIFICATION 2.0: Dynamic data from metadata
  // Convert metadata events to EventOption format
  const dynamicEvents = useMemo<EventOption[]>(() => {
    if (!metadata?.events) return SYSTEM_EVENTS; // Fallback to hardcoded
    return metadata.events.map((event) => ({
      value: event.event,
      label: event.display_name,
      category: event.category,
      description: event.description,
      icon: getCategoryIcon(event.category),
    }));
  }, [metadata]);

  // Dynamic channels from metadata (convert to full format with labels + status)
  const dynamicChannels = useMemo(() => {
    const channelLabels: Record<string, { label: string; description: string }> = {
      browser: { label: "Browser (Real-time)", description: "Hiển thị popup trong trình duyệt ngay lập tức" },
      email: { label: "Email", description: "Gửi email đến hộp thư của người dùng" },
      zalo: { label: "Zalo", description: "Gửi tin nhắn qua Zalo OA" },
      sms: { label: "SMS", description: "Gửi tin nhắn SMS" },
    };

    const fallback = [
      { value: "browser", status: "live" as const },
      { value: "email", status: "live" as const },
      { value: "zalo", status: "live" as const },    // Phase C1
      { value: "sms", status: "planned" as const },
    ];
    const channels = metadata?.channels || fallback;
    return channels.map((ch) => ({
      value: ch.value,
      label: channelLabels[ch.value]?.label || ch.value,
      description: channelLabels[ch.value]?.description || "",
      status: ch.status,
    }));
  }, [metadata]);

  // Dynamic resolver types from metadata
  const dynamicResolverTypes = useMemo<RecipientOption[]>(() => {
    if (!metadata?.resolver_types) return RECIPIENT_OPTIONS; // Fallback
    return metadata.resolver_types.map((resolver) => ({
      value: resolver.value,
      label: resolver.label,
      description: resolver.description,
      example: resolver.example,
    }));
  }, [metadata]);

  // Get category from selected event (using dynamic events)
  const selectedEventData = useMemo(() => {
    return dynamicEvents.find((e) => e.value === selectedEvent);
  }, [selectedEvent, dynamicEvents]);

  // Get metadata for selected event
  const selectedEventMetadata = useMemo(() => {
    if (!metadata?.events || !selectedEvent) return null;
    return metadata.events.find((e) => e.event === selectedEvent);
  }, [metadata, selectedEvent]);

  // Get template variables for selected event (from metadata)
  const availableVariables = useMemo(() => {
    if (!selectedEventMetadata?.variables) {
      // Fallback to hardcoded
      if (!selectedEventData) return [];
      return TEMPLATE_VARIABLES[selectedEventData.category] || [];
    }
    return selectedEventMetadata.variables.map((v) => ({
      variable: `$${v.name}`,
      label: v.description,
      description: `${v.type}${v.required ? " (bắt buộc)" : ""}`,
    }));
  }, [selectedEventMetadata, selectedEventData]);

  // Group events by category (✅ NOTIFICATION 2.0: Using dynamic events)
  const groupedEvents = useMemo(() => {
    const groups: Record<string, EventOption[]> = {};
    dynamicEvents.forEach((event) => {
      if (!groups[event.category]) {
        groups[event.category] = [];
      }
      groups[event.category].push(event);
    });
    return groups;
  }, [dynamicEvents]);

  // Insert variable into template
  const insertVariable = (field: "title_template" | "message_template", variable: string) => {
    const currentValue = form.getValues(field);
    form.setValue(field, `${currentValue}${variable} `);
  };

  // Update condition in form — coerce value to match field type
  const updateCondition = (field: string, operator: string, rawValue: string) => {
    if (!field || !rawValue) {
      form.setValue("condition", null);
      return;
    }

    // Phase 2: Coerce value based on field type from metadata
    const fieldMeta = selectedEventMetadata?.condition_fields?.find(
      (cf: { path: string; type: string }) => cf.path === field
    );
    const fieldType = fieldMeta?.type ?? "string";

    let typedValue: unknown = rawValue;
    if (operator === "in" || operator === "not_in") {
      // Parse comma-separated string into array
      typedValue = rawValue.split(",").map((v) => {
        const trimmed = v.trim();
        if (fieldType === "integer") return parseInt(trimmed, 10) || 0;
        if (fieldType === "float") return parseFloat(trimmed) || 0;
        return trimmed;
      });
    } else if (fieldType === "integer") {
      typedValue = parseInt(rawValue, 10) || 0;
    } else if (fieldType === "float") {
      typedValue = parseFloat(rawValue) || 0;
    } else if (fieldType === "boolean") {
      typedValue = rawValue === "true";
    }

    const condition = {
      type: "simple",
      field: field,
      operator: operator,
      value: typedValue,
    };

    form.setValue("condition", condition);
  };

  const onSubmit = async (data: FormValues) => {
    try {
      if (isEditMode && ruleId) {
        await updateMutation.mutateAsync({
          ruleId,
          data,
        });
        toast.success("✅ Đã cập nhật quy tắc thông báo");
      } else {
        await createMutation.mutateAsync(data);
        toast.success("✅ Đã tạo quy tắc thông báo mới");
      }
      onOpenChange(false);
      form.reset();
      setCurrentStep(1);
      onSuccess?.();
    } catch {
      toast.error(
        isEditMode
          ? "❌ Không thể cập nhật quy tắc"
          : "❌ Không thể tạo quy tắc"
      );
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  const nextStep = () => {
    setCurrentStep((prev) => Math.min(prev + 1, 5)); // ✅ NOTIFICATION 2.0: Changed from 4 to 5
  };

  const prevStep = () => {
    setCurrentStep((prev) => Math.max(prev - 1, 1));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {isEditMode ? "Chỉnh sửa quy tắc thông báo" : "Tạo quy tắc thông báo mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật cấu hình quy tắc thông báo"
              : "Hướng dẫn từng bước để tạo quy tắc thông báo tự động"}
          </DialogDescription>
        </DialogHeader>

        {loadingRule && isEditMode ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            {/* Step Indicator */}
            {/* ✅ NOTIFICATION 2.0: 5 steps total */}
            <StepIndicator currentStep={currentStep} />

            {/* Quick Templates */}
            {currentStep === 1 && !isEditMode && (
              <Card className="bg-gradient-to-r from-info-50 to-indigo-50 border-info-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Zap className="h-4 w-4 text-info-600" />
                    Kịch bản mẫu - Bắt đầu nhanh
                    <HelpTooltip content="Click vào kịch bản mẫu để tự động điền form theo các trường hợp phổ biến" />
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Click để áp dụng kịch bản và tùy chỉnh sau
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {/* Template 1: Manager creates lead */}
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_created");
                        form.setValue("recipient_config", {
                          resolver_type: "unit_staff",
                          params: {},
                        });
                        setConditionEnabled(true);
                        setConditionField("actor.role");
                        setConditionOperator("eq");
                        setConditionValue("manager");
                        updateCondition("actor.role", "eq", "manager");
                        form.setValue("title_template", "Lead mới từ Manager: $lead_name");
                        form.setValue("message_template", "Manager vừa tạo lead $lead_name ($lead_phone). Các officer cùng đơn vị vui lòng theo dõi.");
                        form.setValue("notification_type", "info");
                        setCurrentStep(2);
                      }}
                    >
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Manager tạo lead → Gửi cho Officers</p>
                        <p className="text-xs text-muted-foreground">
                          Khi manager tạo lead, gửi thông báo cho tất cả officers cùng đơn vị
                        </p>
                      </div>
                    </Button>

                    {/* Template 2: Lead assigned */}
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_assigned");
                        form.setValue("recipient_config", {
                          resolver_type: "lead_owner",
                          params: {},
                        });
                        form.setValue("title_template", "Lead được phân công: $lead_name");
                        form.setValue("message_template", "Bạn vừa được phân công lead $lead_name ($lead_phone). Vui lòng liên hệ sớm.");
                        form.setValue("notification_type", "success");
                        setCurrentStep(2);
                      }}
                    >
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Lead được phân công</p>
                        <p className="text-xs text-muted-foreground">
                          Thông báo cho officer khi được gán lead mới
                        </p>
                      </div>
                    </Button>

                    {/* Template 3: Lead assignment failed */}
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_assignment_failed");
                        form.setValue("recipient_config", {
                          resolver_type: "unit_managers",
                          params: {},
                        });
                        form.setValue("title_template", "Cảnh báo: Phân công lead thất bại");
                        form.setValue("message_template", "Không thể tự động phân công lead $lead_name. Lý do: $reason. Vui lòng phân công thủ công.");
                        form.setValue("notification_type", "warning");
                        setCurrentStep(2);
                      }}
                    >
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Phân công thất bại → Gửi Manager</p>
                        <p className="text-xs text-muted-foreground">
                          Cảnh báo manager khi không thể phân công lead tự động
                        </p>
                      </div>
                    </Button>

                    {/* Template 4: Consultation reminder */}
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "consultation_reminder");
                        form.setValue("recipient_config", {
                          resolver_type: "lead_owner",
                          params: {},
                        });
                        form.setValue("title_template", "Nhắc nhở: Tư vấn với $lead_name");
                        form.setValue("message_template", "Bạn có lịch tư vấn với $lead_name ($lead_phone) trong $minutes_until phút nữa.");
                        form.setValue("notification_type", "info");
                        setCurrentStep(2);
                      }}
                    >
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Nhắc lịch tư vấn</p>
                        <p className="text-xs text-muted-foreground">
                          Nhắc officer trước khi đến giờ tư vấn
                        </p>
                      </div>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                {/* STEP 1: Event Selection */}
                {currentStep === 1 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <div>
                      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
                        <Bell className="h-5 w-5 text-primary" />
                        Bước 1: Khi nào gửi thông báo?
                        <HelpTooltip content="Chọn sự kiện hệ thống sẽ kích hoạt thông báo này. Ví dụ: khi có lead mới, khi phân công lead, v.v." />
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Chọn sự kiện hệ thống sẽ kích hoạt thông báo này
                      </p>
                    </div>

                    <FormField
                      control={form.control}
                      name="event"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Chọn sự kiện</FormLabel>
                          <FormControl>
                            <div className="space-y-4">
                              {EVENT_CATEGORIES.map((category) => {
                                const categoryEvents = groupedEvents[category.value] || [];
                                if (categoryEvents.length === 0) return null;

                                return (
                                  <Card key={category.value}>
                                    <CardHeader className="pb-3">
                                      <CardTitle className="text-sm flex items-center gap-2">
                                        <span className="text-lg">{category.icon}</span>
                                        {category.label}
                                      </CardTitle>
                                    </CardHeader>
                                    <CardContent>
                                      <RadioGroup
                                        value={field.value}
                                        onValueChange={field.onChange}
                                      >
                                        <div className="space-y-2">
                                          {categoryEvents.map((event) => (
                                            <div
                                              key={event.value}
                                              className={`
                                                flex items-start space-x-3 rounded-lg border p-3 cursor-pointer transition-colors
                                                ${field.value === event.value ? "border-primary bg-primary/5" : "hover:bg-muted/50"}
                                              `}
                                              onClick={() => field.onChange(event.value)}
                                            >
                                              <RadioGroupItem value={event.value} id={event.value} />
                                              <div className="flex-1">
                                                <label
                                                  htmlFor={event.value}
                                                  className="text-sm font-medium cursor-pointer"
                                                >
                                                  {event.icon} {event.label}
                                                </label>
                                                <p className="text-xs text-muted-foreground mt-0.5">
                                                  {event.description}
                                                </p>
                                              </div>
                                            </div>
                                          ))}
                                        </div>
                                      </RadioGroup>
                                    </CardContent>
                                  </Card>
                                );
                              })}
                            </div>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                )}

                {/* STEP 2: Recipient Selection */}
                {currentStep === 2 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <div>
                      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
                        <Users className="h-5 w-5 text-primary" />
                        Bước 2: Ai sẽ nhận thông báo?
                        <HelpTooltip content="Xác định ai sẽ nhận thông báo khi sự kiện xảy ra. Ví dụ: cán bộ phụ trách, manager đơn vị, v.v." />
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Xác định người nhận thông báo
                      </p>
                    </div>

                    <FormField
                      control={form.control}
                      name="recipient_config.resolver_type"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Chọn người nhận</FormLabel>
                          <FormControl>
                            <RadioGroup
                              value={field.value as string}
                              onValueChange={(value) => {
                                field.onChange(value);
                                form.setValue("recipient_config", {
                                  resolver_type: value,
                                  params: {},
                                });
                              }}
                            >
                              <div className="space-y-3">
                                {/* ✅ NOTIFICATION 2.0: Dynamic resolvers */}
                                {dynamicResolverTypes.map((option) => (
                                  <Card
                                    key={option.value}
                                    className={`
                                      cursor-pointer transition-colors
                                      ${field.value === option.value ? "border-primary bg-primary/5" : "hover:bg-muted/50"}
                                    `}
                                    onClick={() => {
                                      field.onChange(option.value);
                                      form.setValue("recipient_config", {
                                        resolver_type: option.value,
                                        params: {},
                                      });
                                    }}
                                  >
                                    <CardContent className="pt-4">
                                      <div className="flex items-start space-x-3">
                                        <RadioGroupItem value={option.value} id={option.value} />
                                        <div className="flex-1">
                                          <label
                                            htmlFor={option.value}
                                            className="text-sm font-medium cursor-pointer block"
                                          >
                                            {option.label}
                                          </label>
                                          <p className="text-xs text-muted-foreground mt-1">
                                            {option.description}
                                          </p>
                                          <div className="mt-2 bg-info-50 border-l-2 border-info-400 px-2 py-1.5 rounded">
                                            <p className="text-xs text-info-700">
                                              💡 {option.example}
                                            </p>
                                          </div>
                                        </div>
                                      </div>
                                    </CardContent>
                                  </Card>
                                ))}
                              </div>
                            </RadioGroup>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {/* User Picker - Only show when specific_users is selected */}
                    {selectedRecipient === "specific_users" && (
                      <Card>
                        <CardHeader>
                          <CardTitle className="text-sm">Chọn người dùng cụ thể</CardTitle>
                          <CardDescription>Chọn người sẽ nhận thông báo từ danh sách</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3">
                          <Popover open={userPickerOpen} onOpenChange={setUserPickerOpen}>
                            <PopoverTrigger asChild>
                              <Button
                                variant="outline"
                                role="combobox"
                                aria-expanded={userPickerOpen}
                                className="w-full justify-between"
                              >
                                {selectedUserIds.length > 0
                                  ? `${selectedUserIds.length} người được chọn`
                                  : "Chọn người dùng..."}
                                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                              </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-full p-0" align="start">
                              <Command>
                                <CommandInput placeholder="Tìm theo tên hoặc username..." />
                                <CommandList>
                                  <CommandEmpty>Không tìm thấy người dùng</CommandEmpty>
                                  <CommandGroup>
                                    {usersData?.users?.map((user) => (
                                      <CommandItem
                                        key={user.id}
                                        value={`${user.username} ${user.full_name || ""}`}
                                        onSelect={() => {
                                          setSelectedUserIds((prev) =>
                                            prev.includes(user.id)
                                              ? prev.filter((id) => id !== user.id)
                                              : [...prev, user.id]
                                          );
                                          // Update form value
                                          const currentIds = selectedUserIds.includes(user.id)
                                            ? selectedUserIds.filter((id) => id !== user.id)
                                            : [...selectedUserIds, user.id];
                                          form.setValue("recipient_config", {
                                            resolver_type: "specific_users",
                                            params: { user_ids: currentIds },
                                          });
                                        }}
                                      >
                                        <Check
                                          className={cn(
                                            "mr-2 h-4 w-4",
                                            selectedUserIds.includes(user.id)
                                              ? "opacity-100"
                                              : "opacity-0"
                                          )}
                                        />
                                        <div className="flex-1">
                                          <div className="font-medium text-sm">
                                            {user.full_name || user.username}
                                          </div>
                                          <div className="text-xs text-muted-foreground">
                                            @{user.username} • {user.role} {/* architecture-allow presentation */}
                                          </div>
                                        </div>
                                      </CommandItem>
                                    ))}
                                  </CommandGroup>
                                </CommandList>
                              </Command>
                            </PopoverContent>
                          </Popover>

                          {/* Display selected users */}
                          {selectedUserIds.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {selectedUserIds.map((userId) => {
                                const user = usersData?.users?.find((u) => u.id === userId);
                                if (!user) return null;
                                return (
                                  <Badge key={userId} variant="secondary" className="gap-1">
                                    {user.full_name || user.username}
                                    <button
                                      type="button"
                                      className="ml-1 hover:text-destructive"
                                      onClick={() => {
                                        setSelectedUserIds((prev) =>
                                          prev.filter((id) => id !== userId)
                                        );
                                        const currentIds = selectedUserIds.filter((id) => id !== userId);
                                        form.setValue("recipient_config", {
                                          resolver_type: "specific_users",
                                          params: { user_ids: currentIds },
                                        });
                                      }}
                                    >
                                      ×
                                    </button>
                                  </Badge>
                                );
                              })}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    )}
                  </div>
                )}

                {/* STEP 3: Conditions (Optional) */}
                {currentStep === 3 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <div>
                      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
                        <Filter className="h-5 w-5 text-primary" />
                        Bước 3: Điều kiện (Tùy chọn)
                        <HelpTooltip content="Thêm điều kiện để chỉ gửi thông báo khi thỏa mãn tiêu chí. Ví dụ: chỉ gửi khi người thực hiện là Manager. Bạn có thể bỏ qua bước này." />
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Chỉ gửi thông báo khi đáp ứng điều kiện (có thể bỏ qua)
                      </p>
                    </div>

                    {/* Enable/Disable Condition */}
                    <div className="flex items-center justify-between rounded-lg border p-4">
                      <div className="space-y-0.5">
                        <p className="text-sm font-medium">Bật điều kiện lọc</p>
                        <p className="text-xs text-muted-foreground">
                          Chỉ gửi thông báo khi đáp ứng điều kiện
                        </p>
                      </div>
                      <Switch
                        checked={conditionEnabled}
                        onCheckedChange={(checked) => {
                          setConditionEnabled(checked);
                          if (!checked) {
                            form.setValue("condition", null);
                            setConditionField("");
                            setConditionOperator("eq");
                            setConditionValue("");
                            setIsCompoundCondition(false);
                          }
                        }}
                      />
                    </div>

                    {/* Visual Condition Builder */}
                    {conditionEnabled && (
                      <Card>
                        <CardHeader>
                          <CardTitle className="text-sm">Thiết lập điều kiện</CardTitle>
                          <CardDescription>
                            Chỉ gửi thông báo khi thỏa mãn điều kiện dưới đây
                          </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {isCompoundCondition ? (
                            <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 space-y-2">
                              <p className="text-sm font-medium text-yellow-800">
                                Điều kiện phức hợp (AND/OR)
                              </p>
                              <p className="text-xs text-yellow-700">
                                Rule này có điều kiện phức hợp. Chỉnh sửa qua API.
                                Nếu bạn tắt điều kiện, dữ liệu cũ sẽ bị mất.
                              </p>
                              <pre className="text-xs p-2 bg-white rounded border overflow-auto max-h-32">
                                {JSON.stringify(form.getValues("condition"), null, 2)}
                              </pre>
                            </div>
                          ) : (
                            <>
                              {/* Condition Field */}
                              <div className="space-y-2">
                                <label className="text-sm font-medium">Trường dữ liệu</label>
                                <Select
                                  value={conditionField}
                                  onValueChange={(value) => {
                                    setConditionField(value);
                                    updateCondition(value, conditionOperator, conditionValue);
                                  }}
                                >
                                  <SelectTrigger>
                                    <SelectValue placeholder="Chọn trường..." />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {selectedEventMetadata?.condition_fields?.map((cf: { path: string; description: string }) => (
                                      <SelectItem key={cf.path} value={cf.path}>{cf.description}</SelectItem>
                                    )) ?? (
                                      <SelectItem value="" disabled>Chọn sự kiện trước</SelectItem>
                                    )}
                                  </SelectContent>
                                </Select>
                                <p className="text-xs text-muted-foreground">
                                  💡 Chọn trường dữ liệu từ danh sách. Các trường có sẵn phụ thuộc vào sự kiện đã chọn.
                                </p>
                              </div>

                              {/* Condition Operator */}
                              <div className="space-y-2">
                                <label className="text-sm font-medium">Phép so sánh</label>
                                <Select
                                  value={conditionOperator}
                                  onValueChange={(value) => {
                                    setConditionOperator(value);
                                    updateCondition(conditionField, value, conditionValue);
                                  }}
                                >
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {(() => {
                                      const fieldMeta = selectedEventMetadata?.condition_fields?.find(
                                        (cf: { path: string }) => cf.path === conditionField
                                      );
                                      const ops = fieldMeta?.operators ?? ["eq", "ne"];
                                      return ops.map((op: string) => (
                                        <SelectItem key={op} value={op}>
                                          {OPERATOR_LABELS[op] ?? op}
                                        </SelectItem>
                                      ));
                                    })()}
                                  </SelectContent>
                                </Select>
                              </div>

                              {/* Condition Value - Phase 2: type-aware */}
                              <div className="space-y-2">
                                <label className="text-sm font-medium">Giá trị</label>
                                {(() => {
                                  const fieldMeta = selectedEventMetadata?.condition_fields?.find(
                                    (cf: { path: string }) => cf.path === conditionField
                                  );
                                  const fieldType = fieldMeta?.type ?? "string";

                                  if (fieldType === "boolean") {
                                    return (
                                      <Select
                                        value={conditionValue}
                                        onValueChange={(value) => {
                                          setConditionValue(value);
                                          updateCondition(conditionField, conditionOperator, value);
                                        }}
                                      >
                                        <SelectTrigger>
                                          <SelectValue placeholder="Ch��n giá trị..." />
                                        </SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="true">Có (true)</SelectItem>
                                          <SelectItem value="false">Không (false)</SelectItem>
                                        </SelectContent>
                                      </Select>
                                    );
                                  }

                                  const isListOp = conditionOperator === "in" || conditionOperator === "not_in";

                                  return (
                                    <Input
                                      type={!isListOp && (fieldType === "integer" || fieldType === "float") ? "number" : "text"}
                                      placeholder={isListOp ? "Nhập danh sách phân cách bằng dấu phẩy (VD: admin, manager)" : "Nhập giá trị..."}
                                      value={conditionValue}
                                      onChange={(e) => {
                                        setConditionValue(e.target.value);
                                        updateCondition(conditionField, conditionOperator, e.target.value);
                                      }}
                                    />
                                  );
                                })()}
                                <p className="text-xs text-muted-foreground">
                                  💡 VD: actor.role eq &ldquo;manager&rdquo;, event.new_status_id eq &ldquo;contacted&rdquo;
                                </p>
                              </div>

                              {/* Preview */}
                              {conditionField && conditionValue && (
                                <div className="bg-info-50 border-l-2 border-info-400 px-3 py-2 rounded">
                                  <p className="text-xs font-medium text-info-900 mb-1">
                                    📝 Điều kiện hiện tại:
                                  </p>
                                  <code className="text-xs text-info-700">
                                    {conditionField} {conditionOperator} &ldquo;{conditionValue}&rdquo;
                                  </code>
                                </div>
                              )}
                            </>
                          )}
                        </CardContent>
                      </Card>
                    )}

                    {/* Example scenarios */}
                    <Card className="bg-muted/50">
                      <CardHeader className="pb-3">
                        <CardTitle className="text-sm">💡 Ví dụ điều kiện phổ biến</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="space-y-2 text-xs">
                          <div className="flex items-start gap-2">
                            <span className="text-muted-foreground">•</span>
                            <div>
                              <p className="font-medium">Chỉ gửi khi Manager tạo lead:</p>
                              <code className="text-muted-foreground">actor.role == &ldquo;manager&rdquo;</code>
                            </div>
                          </div>
                          <div className="flex items-start gap-2">
                            <span className="text-muted-foreground">•</span>
                            <div>
                              <p className="font-medium">Chỉ gửi khi thanh toán trên 10 triệu:</p>
                              <code className="text-muted-foreground">amount {">"} 10000000</code>
                            </div>
                          </div>
                          <div className="flex items-start gap-2">
                            <span className="text-muted-foreground">•</span>
                            <div>
                              <p className="font-medium">Chỉ gửi khi hồ sơ được duyệt:</p>
                              <code className="text-muted-foreground">application.status == &ldquo;approved&rdquo;</code>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* STEP 4: Content & Template */}
                {currentStep === 4 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <div>
                      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
                        <MessageSquare className="h-5 w-5 text-primary" />
                        Bước 4: Nội dung thông báo
                        <HelpTooltip content="Tạo tiêu đề và nội dung thông báo. Click vào các biến bên dưới để chèn thông tin tự động như tên lead, số điện thoại, v.v." />
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Soạn tiêu đề và nội dung thông báo
                      </p>
                    </div>

                    {/* Template Variables Helper */}
                    {availableVariables.length > 0 && (
                      <Card className="bg-info-50 border-info-200">
                        <CardHeader className="pb-3">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Sparkles className="h-4 w-4 text-info-600" />
                            Biến tự động
                            <HelpTooltip content="Click vào biến để chèn vào tiêu đề hoặc nội dung. Giá trị sẽ tự động thay thế khi gửi thông báo." />
                          </CardTitle>
                          <CardDescription className="text-xs">
                            Click để chèn biến vào tiêu đề hoặc nội dung
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <div className="flex flex-wrap gap-2">
                            {availableVariables.map((v) => (
                              <TooltipProvider key={v.variable} delayDuration={0}>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="sm"
                                      className="text-xs h-7"
                                      onClick={() => {
                                        // Insert into the field that's currently focused, or default to message
                                        const activeElement = document.activeElement;
                                        if (activeElement?.id === "title_template") {
                                          insertVariable("title_template", v.variable);
                                        } else {
                                          insertVariable("message_template", v.variable);
                                        }
                                      }}
                                    >
                                      {v.label}
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p className="text-xs">
                                      <code className="font-mono">{v.variable}</code> - {v.description}
                                    </p>
                                  </TooltipContent>
                                </Tooltip>
                              </TooltipProvider>
                            ))}
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {/* Title Template */}
                    <FormField
                      control={form.control}
                      name="title_template"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Tiêu đề thông báo</FormLabel>
                          <FormControl>
                            <Input
                              id="title_template"
                              placeholder="VD: Lead mới: $lead_name"
                              {...field}
                            />
                          </FormControl>
                          <FormDescription>
                            Tiêu đề ngắn gọn, súc tích. Click biến phía trên để chèn tự động.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {/* Message Template */}
                    <FormField
                      control={form.control}
                      name="message_template"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Nội dung thông báo</FormLabel>
                          <FormControl>
                            <Textarea
                              id="message_template"
                              placeholder="VD: Lead $lead_name ($lead_phone) đã được phân công cho bạn."
                              rows={4}
                              {...field}
                            />
                          </FormControl>
                          <FormDescription>
                            Mô tả chi tiết nội dung thông báo. Click biến phía trên để chèn tự động.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <Separator />

                    {/* Notification Type */}
                    <FormField
                      control={form.control}
                      name="notification_type"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Loại thông báo</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {NOTIFICATION_TYPES.map((type) => (
                                <SelectItem key={type.value} value={type.value}>
                                  <div className="flex items-center gap-2">
                                    <Badge className={type.color} variant="secondary">
                                      {type.label}
                                    </Badge>
                                    <span className="text-xs text-muted-foreground">
                                      - {type.description}
                                    </span>
                                  </div>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            Mức độ ưu tiên của thông báo
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {/* Link Template (Optional) */}
                    <FormField
                      control={form.control}
                      name="link_template"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            Liên kết (Tùy chọn)
                            <HelpTooltip content="Đường dẫn để điều hướng khi click vào thông báo. VD: /leads/$lead_id" />
                          </FormLabel>
                          <FormControl>
                            <Input
                              placeholder="VD: /leads/$lead_id"
                              {...field}
                            />
                          </FormControl>
                          <FormDescription>
                            Người dùng sẽ được chuyển đến trang này khi click thông báo
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {/* Channels */}
                    <FormField
                      control={form.control}
                      name="channels"
                      render={() => (
                        <FormItem>
                          <FormLabel>
                            Kênh gửi
                            <HelpTooltip content="Chọn cách thức gửi thông báo: trong trình duyệt, qua email, hoặc SMS" />
                          </FormLabel>
                          <FormDescription>
                            Chọn các kênh để gửi thông báo
                          </FormDescription>
                          <div className="space-y-2">
                            {/* ✅ NOTIFICATION 2.0: Dynamic channels */}
                            {dynamicChannels.map((channel) => (
                              <FormField
                                key={channel.value}
                                control={form.control}
                                name="channels"
                                render={({ field }) => (
                                  <FormItem className={`flex items-start space-x-3 space-y-0 rounded-lg border p-3 ${channel.status === "planned" ? "opacity-60" : ""}`}>
                                    <FormControl>
                                      <Checkbox
                                        checked={field.value?.includes(channel.value)}
                                        disabled={channel.status === "planned"}
                                        onCheckedChange={(checked) => {
                                          const current = field.value || [];
                                          if (checked) {
                                            field.onChange([...current, channel.value]);
                                          } else {
                                            field.onChange(
                                              current.filter((v) => v !== channel.value)
                                            );
                                          }
                                        }}
                                      />
                                    </FormControl>
                                    <div className="flex-1">
                                      <FormLabel className={`text-sm font-medium ${channel.status === "planned" ? "text-muted-foreground" : "cursor-pointer"}`}>
                                        {channel.label}
                                        {channel.status === "planned" && (
                                          <span className="ml-2 inline-flex items-center rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                                            Planned
                                          </span>
                                        )}
                                      </FormLabel>
                                      <p className="text-xs text-muted-foreground">
                                        {channel.description}
                                      </p>
                                    </div>
                                  </FormItem>
                                )}
                              />
                            ))}
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {/* Enabled Switch */}
                    <FormField
                      control={form.control}
                      name="enabled"
                      render={({ field }) => (
                        <FormItem className="flex items-center justify-between rounded-lg border p-4">
                          <div className="space-y-0.5">
                            <FormLabel className="text-base">Kích hoạt ngay</FormLabel>
                            <FormDescription>
                              Bật quy tắc này ngay sau khi tạo
                            </FormDescription>
                          </div>
                          <FormControl>
                            <Switch
                              checked={field.value}
                              onCheckedChange={field.onChange}
                            />
                          </FormControl>
                        </FormItem>
                      )}
                    />

                    {/* Preview */}
                    {(titleTemplate || messageTemplate) && (
                      <Card className="bg-muted/50">
                        <CardHeader className="pb-3">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Bell className="h-4 w-4" />
                            Xem trước thông báo
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="bg-background rounded-lg border p-4 space-y-2">
                            {titleTemplate && (
                              <p className="font-semibold text-sm">{titleTemplate}</p>
                            )}
                            {messageTemplate && (
                              <p className="text-sm text-muted-foreground">{messageTemplate}</p>
                            )}
                            <p className="text-xs text-muted-foreground/70">
                              Vừa xong
                            </p>
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                )}

                {/* STEP 5: Multi-Step Workflow ✅ NOTIFICATION 2.0 */}
                {currentStep === 5 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <div>
                      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
                        <Layers className="h-5 w-5 text-primary" />
                        Bước 5: Quy trình gửi thông báo
                        <HelpTooltip content="Cấu hình quy trình gửi thông báo qua nhiều kênh với độ trễ khác nhau. Ví dụ: Gửi Browser ngay, sau 30 phút gửi Email nhắc nhở." />
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Tạo quy trình gửi thông báo qua nhiều bước với các kênh khác nhau
                      </p>
                    </div>

                    <FormField
                      control={form.control}
                      name="actions"
                      render={({ field }) => (
                        <FormItem>
                          <FormControl>
                            {/* ✅ NOTIFICATION 2.0: Dynamic channels */}
                            <MultiStepActionEditor
                              actions={field.value || []}
                              onChange={field.onChange}
                              availableChannels={(metadata?.channels || dynamicChannels).filter((ch) => ch.status === "live").map((ch) => ch.value)}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                )}

                {/* Navigation Footer */}
                <DialogFooter className="flex items-center justify-between sm:justify-between border-t pt-4">
                  <div>
                    {currentStep > 1 && (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={prevStep}
                        disabled={isPending}
                      >
                        <ChevronLeft className="mr-2 h-4 w-4" />
                        Quay lại
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        onOpenChange(false);
                        setCurrentStep(1);
                      }}
                      disabled={isPending}
                    >
                      Hủy
                    </Button>
                    {/* ✅ NOTIFICATION 2.0: Changed from 4 to 5 */}
                    {currentStep < 5 ? (
                      <Button
                        type="button"
                        onClick={nextStep}
                        disabled={!selectedEvent && currentStep === 1}
                      >
                        Tiếp theo
                        <ChevronRight className="ml-2 h-4 w-4" />
                      </Button>
                    ) : (
                      <Button type="submit" disabled={isPending}>
                        {isPending ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            {isEditMode ? "Đang cập nhật…" : "Đang tạo…"}
                          </>
                        ) : (
                          <>
                            <Save className="mr-2 h-4 w-4" />
                            {isEditMode ? "Cập nhật" : "Tạo quy tắc"}
                          </>
                        )}
                      </Button>
                    )}
                  </div>
                </DialogFooter>
              </form>
            </Form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
