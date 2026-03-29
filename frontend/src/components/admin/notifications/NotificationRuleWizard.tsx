// src/components/admin/notifications/NotificationRuleWizard.tsx
/**
 * ✅ PHASE 2.4: Notification Rule Wizard
 *
 * Phase 3c: 4-step wizard for notification rules.
 * Step 1: Trigger (event + condition)
 * Step 2: Default content (title/message/type/link)
 * Step 3: Recipient groups (internal + external, each with channel branches)
 * Step 4: Preview & Save
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
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import * as z from "zod";
import {
  Loader2,
  Save,
  ChevronRight,
  ChevronLeft,
  HelpCircle,
  // Bell, Users, MessageSquare, Check — moved to StepIndicator
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Form,
  // FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage — moved to DefaultContentSection
} from "@/components/ui/form";
// Input, Textarea — moved to DefaultContentSection
// Select, SelectContent, SelectItem, SelectTrigger, SelectValue — moved to DefaultContentSection
// Switch — moved to FinalPreviewSection
// import { Checkbox } from "@/components/ui/checkbox"; // Phase 3c: channels moved to recipient groups
// Badge — moved to DefaultContentSection
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
// RadioGroup, RadioGroupItem moved to EventSelectorSection
// Separator — moved to DefaultContentSection
// Phase 3c: Command/Popover moved to recipient group cards
// import {
//   Command, CommandEmpty, CommandGroup,
//   CommandInput, CommandItem, CommandList,
// } from "@/components/ui/command";
// import {
//   Popover, PopoverContent, PopoverTrigger,
// } from "@/components/ui/popover";
import { toast } from "sonner";
// import { cn } from "@/lib/utils"; // Phase 3c: user picker removed

import {
  useCreateNotificationRule,
  useUpdateNotificationRule,
  useNotificationRule,
  useNotificationMetadata, // ✅ NOTIFICATION 2.0: Dynamic metadata
} from "@/hooks/useNotificationRules";
// import { useAdminUsersList } from "@/hooks/useAdminUsers"; // Phase 3c: user picker moved to recipient groups
// import { MultiStepActionEditor } from "./MultiStepActionEditor"; // Phase 3c: replaced by WizardStepRecipientGroups
import WizardStepRecipientGroups from "./WizardStepRecipientGroups";
import type { RecipientGroup, ExternalResolverOption } from "./wizard-types";
import { mapToAPI, hydrateFromAPI, validateAllSteps, flattenStepErrors, createInternalGroup, resetGroupCounter } from "./wizard-utils";
import NotificationRuleSidebar from "./NotificationRuleSidebar";
import { TriggerSection } from "./TriggerSection";
import DefaultContentSection from "./DefaultContentSection";
import FinalPreviewSection from "./FinalPreviewSection";
import StepIndicator from "./StepIndicator";

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
  channels: z.array(z.string()), // DEPRECATED: backend derives from actions. Auto-derived in onSubmit.
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
 * Category display config — UI only (label, icon, sort order).
 * Categories are derived from metadata at runtime; this map only provides display info.
 * Unknown categories get sensible defaults and sort to the end.
 */
const CATEGORY_DISPLAY: Record<string, { label: string; icon: string; order: number }> = {
  lead:          { label: "Sự kiện Lead",       icon: "👤", order: 1 },
  consultation:  { label: "Sự kiện Tư vấn",    icon: "💬", order: 2 },
  application:   { label: "Sự kiện Hồ sơ",     icon: "📝", order: 3 },
  finance:       { label: "Sự kiện Tài chính",  icon: "💰", order: 4 },
  dorm:          { label: "Sự kiện Ký túc",     icon: "🏠", order: 5 },
  asset:         { label: "Sự kiện Tài sản",    icon: "🔧", order: 6 },
  pipeline:      { label: "Sự kiện Pipeline",   icon: "📊", order: 7 },
  operational:   { label: "Sự kiện Vận hành",   icon: "⚙️", order: 8 },
  security:      { label: "Sự kiện Bảo mật",    icon: "🔒", order: 9 },
  system:        { label: "Sự kiện Hệ thống",   icon: "🔔", order: 10 },
};

const FALLBACK_CATEGORY_ORDER = 999;

// getCategoryLabel — moved to EventSelectorSection

function getCategoryOrder(category: string): number {
  return CATEGORY_DISPLAY[category]?.order ?? FALLBACK_CATEGORY_ORDER;
}

/**
 * Danh sách người nhận với mô tả và ví dụ rõ ràng
 */
const RECIPIENT_OPTIONS: RecipientOption[] = [
  {
    value: "lead_owner",
    label: "Cán bộ phụ trách lead",
    description: "Gửi cho cán bộ đang được gán lead này",
  },
  {
    value: "unit_staff",
    label: "Nhân viên cùng đơn vị",
    description: "Gửi cho tất cả cán bộ trong cùng phòng/ban",
  },
  {
    value: "unit_managers",
    label: "Quản lý đơn vị",
    description: "Chỉ gửi cho các manager của đơn vị",
  },
  {
    value: "all_admins",
    label: "Tất cả Admin",
    description: "Gửi cho tất cả người dùng có quyền Admin",
  },
  {
    value: "all_users",
    label: "Tất cả người dùng",
    description: "Gửi broadcast cho toàn bộ người dùng trong hệ thống",
  },
  {
    value: "specific_users",
    label: "Người dùng cụ thể",
    description: "Chọn danh sách người nhận theo tên",
  },
  {
    value: "dorm_residents",
    label: "Sinh viên ở ký túc",
    description: "Gửi cho các sinh viên đang ở ký túc xá",
  },
  {
    value: "dorm_staff",
    label: "Nhân viên ký túc xá",
    description: "Gửi cho đội ngũ quản lý KTX",
  },
];

// Fallback when metadata.external_resolver_types is unavailable
const EXTERNAL_RESOLVER_FALLBACK: ExternalResolverOption[] = [
  { value: "lead_contact", label: "Lead (qua Zalo/SMS)", description: "Gửi cho lead qua SĐT" },
  { value: "admission_contact", label: "Hồ sơ tuyển sinh", description: "Gửi cho ứng viên" },
  { value: "collaborator_contact", label: "Cộng tác viên", description: "Gửi cho CTV" },
];

// NOTIFICATION_TYPES — moved to DefaultContentSection

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
  return CATEGORY_DISPLAY[category]?.icon || "🔔";
}

// OPERATOR_LABELS — moved to ConditionSection

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

// StepIndicator — extracted to StepIndicator.tsx (Batch 6)

// ============================================
// MAIN COMPONENT
// ============================================

interface NotificationRuleWizardProps {
  ruleId?: number;
}

export function NotificationRuleWizard({
  ruleId,
}: NotificationRuleWizardProps) {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [highestStepVisited, setHighestStepVisited] = useState(1);
  const isEditMode = !!ruleId;

  // Tracks which steps user attempted to advance from (triggers inline errors)
  const [attemptedSteps, setAttemptedSteps] = useState<Set<number>>(new Set());

  const goToStep = (step: number) => {
    setCurrentStep(step);
    setHighestStepVisited((prev) => Math.max(prev, step));
  };

  // Show inline errors when user has attempted this step or been past it
  const shouldShowStepErrors = (step: number) =>
    attemptedSteps.has(step) || highestStepVisited > step;

  // User selection state — kept for potential future use in recipient group specific_users
  // const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  // const [userPickerOpen, setUserPickerOpen] = useState(false);

  // Condition builder state
  const [conditionEnabled, setConditionEnabled] = useState(false);
  const [conditionField, setConditionField] = useState<string>("");
  const [conditionOperator, setConditionOperator] = useState<string>("eq");
  const [conditionValue, setConditionValue] = useState<string>("");
  const [isCompoundCondition, setIsCompoundCondition] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);

  // Phase 3c: Recipient groups state
  const [recipientGroups, setRecipientGroups] = useState<RecipientGroup[]>([createInternalGroup()]);

  // Phase 3c: User picker moved into recipient group cards
  // const { data: usersData } = useAdminUsersList({ page: 1, page_size: 100 });

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
      actions: existingRule.actions?.map((a) => ({
        step: a.step,
        channel: a.channel,
        template_code: a.template_code || null,
        delay_minutes: a.delay_minutes || 0,
        config: a.config || null,
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

    // Phase 3c: Hydrate recipient groups from rule actions
    const wizardState = hydrateFromAPI(existingRule);
    setRecipientGroups(wizardState.recipientGroups);

    // Edit mode: all steps accessible since data exists
    setHighestStepVisited(4);
  }, [existingRule, isEditMode, form]);

  // Watch form values for dynamic behavior
  const selectedEvent = form.watch("event");
  // const selectedRecipient = form.watch("recipient_config.resolver_type") as string; // Phase 3c: moved to recipient groups
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
  }, [selectedEvent, form, isEditMode, isHydrated]);

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
      const cat = event.category || "other";
      if (!groups[cat]) {
        groups[cat] = [];
      }
      groups[cat].push(event);
    });
    return groups;
  }, [dynamicEvents]);

  // Sorted category keys — known categories by order, unknown at the end
  const sortedCategoryKeys = useMemo(() => {
    return Object.keys(groupedEvents).sort(
      (a, b) => getCategoryOrder(a) - getCategoryOrder(b)
    );
  }, [groupedEvents]);

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
      field: field,
      operator: operator,
      value: typedValue,
    };

    form.setValue("condition", condition);
  };

  const onSubmit = async (data: FormValues) => {
    try {
      // Unified validation: check all steps (allErrors computed in render)
      if (allErrors.length > 0) {
        goToStep(4); // Go to preview to show errors
        return;
      }

      const trigger = {
        event: data.event,
        condition: data.condition,
        enabled: data.enabled,
      };
      const defaultContent = {
        title_template: data.title_template,
        message_template: data.message_template,
        notification_type: data.notification_type,
        link_template: data.link_template ?? "",
      };

      const submitData = mapToAPI(recipientGroups, defaultContent, trigger);

      if (isEditMode && ruleId) {
        await updateMutation.mutateAsync({
          ruleId,
          data: submitData,
        });
        toast.success("Đã cập nhật quy tắc thông báo");
      } else {
        await createMutation.mutateAsync(submitData);
        toast.success("Đã tạo quy tắc thông báo mới");
      }
      form.reset();
      setRecipientGroups([createInternalGroup()]);
      resetGroupCounter();
      setCurrentStep(1);
      setHighestStepVisited(1);
      setAttemptedSteps(new Set());
      router.push("/admin/notification-rules");
    } catch {
      toast.error(
        isEditMode
          ? "Không thể cập nhật quy tắc"
          : "Không thể tạo quy tắc"
      );
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  // Unified validation — single source of truth for nav, sidebar, preview
  const stepErrors = validateAllSteps(
    selectedEvent,
    form.getValues("title_template") || "",
    form.getValues("message_template") || "",
    recipientGroups,
  );
  const allErrors = flattenStepErrors(stepErrors);
  const currentStepErrors = currentStep === 1 ? stepErrors.step1
    : currentStep === 2 ? stepErrors.step2
    : currentStep === 3 ? stepErrors.step3
    : [];
  const sidebarCanSave = allErrors.length === 0;

  // Next button: always clickable, marks step as attempted, triggers inline errors
  const handleNextClick = () => {
    setAttemptedSteps((prev) => new Set(prev).add(currentStep));
    // Trigger RHF validation for step 2 fields (populates FormMessage)
    if (currentStep === 2) {
      form.trigger(["title_template", "message_template"]);
    }
    if (currentStepErrors.length === 0) {
      goToStep(Math.min(currentStep + 1, 4));
    }
  };

  const prevStep = () => {
    goToStep(Math.max(currentStep - 1, 1));
  };

  // Step click handler: backward always ok, forward requires prior steps valid
  const handleStepClick = (targetStep: number) => {
    if (targetStep <= currentStep) {
      goToStep(targetStep);
      return;
    }
    // Forward: check all prior steps, land on first error step
    for (let s = 1; s < targetStep; s++) {
      const key = `step${s}` as keyof typeof stepErrors;
      if (stepErrors[key]?.length > 0) {
        setAttemptedSteps((prev) => new Set(prev).add(s));
        if (s === 2) form.trigger(["title_template", "message_template"]);
        goToStep(s);
        return;
      }
    }
    goToStep(targetStep);
  };

  return (
    <div className="container max-w-6xl mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            {isEditMode ? "Chỉnh sửa quy tắc thông báo" : "Tạo quy tắc thông báo mới"}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isEditMode
              ? "Cập nhật cấu hình gửi thông báo"
              : "Cấu hình khi nào, gửi cho ai, qua kênh nào"}
          </p>
        </div>
        <Button variant="outline" onClick={() => router.back()}>
          Quay lại
        </Button>
      </div>

      {loadingRule && isEditMode ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <>
            {/* Step Indicator — clickable with validation state */}
            <StepIndicator
              currentStep={currentStep}
              onStepClick={handleStepClick}
              stepErrors={stepErrors}
              highestStepVisited={highestStepVisited}
            />

            {/* 2-column layout: main + sidebar */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">

            {/* Quick Templates */}
            {currentStep === 1 && !isEditMode && (
              <Card className="bg-gradient-to-r from-info-50 to-indigo-50 border-info-200">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Zap className="h-4 w-4 text-info-600" />
                    Cấu hình nhanh
                    <HelpTooltip content="Click vào kịch bản mẫu để tự động điền form theo các trường hợp phổ biến" />
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Chọn một ví dụ để bắt đầu, sau đó tùy chỉnh theo nhu cầu
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
                        form.setValue("actions", [{ step: 1, channel: "browser", template_code: null, delay_minutes: 0, config: null }]);
                        resetGroupCounter();
                        setRecipientGroups([{
                          group_key: "group_1", label: "Nhân viên cùng đơn vị", recipient_kind: "internal",
                          recipient_config: { resolver_type: "unit_staff", params: {} }, external_resolver: null,
                          channels: [{ channel: "browser", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null }],
                        }]);
                        goToStep(2);
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
                        form.setValue("actions", [{ step: 1, channel: "browser", template_code: null, delay_minutes: 0, config: null }]);
                        resetGroupCounter();
                        setRecipientGroups([{
                          group_key: "group_1", label: "Officer phụ trách lead", recipient_kind: "internal",
                          recipient_config: { resolver_type: "lead_owner", params: {} }, external_resolver: null,
                          channels: [{ channel: "browser", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null }],
                        }]);
                        goToStep(2);
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
                        form.setValue("actions", [
                          { step: 1, channel: "browser", template_code: null, delay_minutes: 0, config: null },
                          { step: 2, channel: "email", template_code: null, delay_minutes: 0, config: null },
                        ]);
                        resetGroupCounter();
                        setRecipientGroups([{
                          group_key: "group_1", label: "Quản lý đơn vị", recipient_kind: "internal",
                          recipient_config: { resolver_type: "unit_managers", params: {} }, external_resolver: null,
                          channels: [
                            { channel: "browser", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null },
                            { channel: "email", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null },
                          ],
                        }]);
                        goToStep(2);
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
                        form.setValue("actions", [{ step: 1, channel: "browser", template_code: null, delay_minutes: 0, config: null }]);
                        resetGroupCounter();
                        setRecipientGroups([{
                          group_key: "group_1", label: "Officer phụ trách lead", recipient_kind: "internal",
                          recipient_config: { resolver_type: "lead_owner", params: {} }, external_resolver: null,
                          channels: [{ channel: "browser", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null }],
                        }]);
                        goToStep(2);
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
                {/* STEP 1: Trigger (Event + Condition) */}
                {currentStep === 1 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <TriggerSection
                      // Event props
                      value={form.watch("event")}
                      onChange={(v) => form.setValue("event", v)}
                      groupedEvents={groupedEvents}
                      sortedCategoryKeys={sortedCategoryKeys}
                      // Condition props
                      conditionEnabled={conditionEnabled}
                      onConditionEnabledChange={(checked) => {
                        setConditionEnabled(checked);
                        if (!checked) {
                          form.setValue("condition", null);
                          setConditionField("");
                          setConditionOperator("eq");
                          setConditionValue("");
                          setIsCompoundCondition(false);
                        }
                      }}
                      conditionField={conditionField}
                      onConditionFieldChange={setConditionField}
                      conditionOperator={conditionOperator}
                      onConditionOperatorChange={setConditionOperator}
                      conditionValue={conditionValue}
                      onConditionValueChange={setConditionValue}
                      isCompoundCondition={isCompoundCondition}
                      onIsCompoundConditionChange={setIsCompoundCondition}
                      conditionData={form.getValues("condition") as Record<string, unknown> | null}
                      updateCondition={updateCondition}
                      selectedEventMetadata={selectedEventMetadata}
                    />
                    {/* Inline validation for step 1 */}
                    {shouldShowStepErrors(1) && stepErrors.step1.length > 0 && (
                      <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 space-y-1">
                        {stepErrors.step1.map((err, i) => (
                          <p key={i} className="text-sm text-destructive">{"\u2022"} {err}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* STEP 2: Content & Template (Phase 3c: was old Step 4) */}
                {currentStep === 2 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <DefaultContentSection
                      formControl={form.control}
                      availableVariables={availableVariables}
                      onInsertVariable={insertVariable}
                      titleTemplate={titleTemplate}
                      messageTemplate={messageTemplate}
                    />
                  </div>
                )}

                {/* STEP 3: Recipient Groups (Phase 3c) */}
                {currentStep === 3 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <WizardStepRecipientGroups
                      groups={recipientGroups}
                      onChange={setRecipientGroups}
                      resolverOptions={dynamicResolverTypes}
                      externalResolverOptions={metadata?.external_resolver_types ?? EXTERNAL_RESOLVER_FALLBACK}
                      availableChannels={dynamicChannels.filter((c) => c.status === "live").map((c) => c.value)}
                      validationErrors={shouldShowStepErrors(3) ? stepErrors.step3 : undefined}
                    />
                  </div>
                )}

                {/* STEP 4: Preview & Save (Phase 3c) */}
                {currentStep === 4 && (
                  <div className="animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <FinalPreviewSection
                      previewErrors={allErrors}
                      eventLabel={selectedEventData?.label ?? form.getValues("event")}
                      titleTemplate={form.getValues("title_template") || ""}
                      recipientGroups={recipientGroups}
                      condition={
                        conditionEnabled && conditionField
                          ? { field: conditionField, operator: conditionOperator, value: conditionValue }
                          : null
                      }
                      enabled={form.getValues("enabled")}
                      onEnabledChange={(checked) => form.setValue("enabled", checked)}
                    />
                  </div>
                )}

                {/* Navigation Footer */}
                <div className="flex items-center justify-between pt-6 border-t mt-6">
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
                      onClick={() => router.back()}
                      disabled={isPending}
                    >
                      Hủy
                    </Button>
                    {currentStep < 4 ? (
                      <Button
                        type="button"
                        onClick={handleNextClick}
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
                </div>
              </form>
            </Form>

              {/* Sidebar — sticky on desktop */}
              <div className="hidden lg:block">
                <div className="sticky top-6">
                  <NotificationRuleSidebar
                    trigger={{
                      event: form.getValues("event") || "",
                      condition: form.getValues("condition"),
                      enabled: form.getValues("enabled"),
                    }}
                    recipientGroups={recipientGroups}
                    titleTemplate={form.watch("title_template") || ""}
                    validationErrors={allErrors}
                    enabled={form.getValues("enabled")}
                    onEnabledChange={(v) => form.setValue("enabled", v)}
                    onSave={form.handleSubmit(onSubmit)}
                    onCancel={() => router.back()}
                    isSaving={createMutation.isPending || updateMutation.isPending}
                    isEditMode={isEditMode}
                    canSave={sidebarCanSave}
                    selectedEventLabel={selectedEventData?.label}
                  />
                </div>
              </div>
            </div>
          </>
        )}
    </div>
  );
}
