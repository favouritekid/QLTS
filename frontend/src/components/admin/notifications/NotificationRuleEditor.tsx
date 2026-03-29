// src/components/admin/notifications/NotificationRuleEditor.tsx
/**
 * Notification Rule Editor — full-page 4-step editor for notification rules.
 *
 * Step 1: Trigger (event + condition)
 * Step 2: Default content (title/message/type/link)
 * Step 3: Recipient groups (internal + external, each with channel branches)
 * Step 4: Preview & Save
 *
 * Orchestrates form state, metadata, and delegates rendering to section components.
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
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";

import {
  useCreateNotificationRule,
  useUpdateNotificationRule,
  useNotificationRule,
  useNotificationMetadata,
} from "@/hooks/useNotificationRules";
import WizardStepRecipientGroups from "./WizardStepRecipientGroups";
import type { RecipientGroup } from "./wizard-types";
import {
  mapToAPI,
  hydrateFromAPI,
  validateAllSteps,
  flattenStepErrors,
  createInternalGroup,
  resetGroupCounter,
  OPERATOR_ALIAS_MAP,
  resolveFieldAlias,
} from "./wizard-utils";
import {
  SYSTEM_EVENTS,
  RECIPIENT_OPTIONS,
  EXTERNAL_RESOLVER_FALLBACK,
  TEMPLATE_VARIABLES,
  getCategoryIcon,
  getCategoryOrder,
} from "./wizard-constants";
import type { EventOption, RecipientOption } from "./wizard-constants";
import NotificationRuleSidebar from "./NotificationRuleSidebar";
import { TriggerSection } from "./TriggerSection";
import DefaultContentSection from "./DefaultContentSection";
import FinalPreviewSection from "./FinalPreviewSection";
import StepIndicator from "./StepIndicator";

// ============================================
// FORM SCHEMA
// ============================================

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
  channels: z.array(z.string()),
  recipient_config: z.record(z.string(), z.unknown()),
  condition: z.record(z.string(), z.unknown()).nullable(),
  enabled: z.boolean(),
  actions: z.array(actionSchema).optional(),
});

type FormValues = z.infer<typeof formSchema>;

// ============================================
// HELPER COMPONENTS
// ============================================

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

// ============================================
// MAIN COMPONENT
// ============================================

interface NotificationRuleEditorProps {
  ruleId?: number;
}

export function NotificationRuleEditor({
  ruleId,
}: NotificationRuleEditorProps) {
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

  // Condition builder state
  const [conditionEnabled, setConditionEnabled] = useState(false);
  const [conditionField, setConditionField] = useState<string>("");
  const [conditionOperator, setConditionOperator] = useState<string>("eq");
  const [conditionValue, setConditionValue] = useState<string>("");
  const [isCompoundCondition, setIsCompoundCondition] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);

  // Recipient groups state
  const [recipientGroups, setRecipientGroups] = useState<RecipientGroup[]>([createInternalGroup()]);

  // Data hooks
  const { data: metadata } = useNotificationMetadata();
  const { data: existingRule, isLoading: loadingRule } = useNotificationRule(ruleId);
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
      channels: ["browser"],
      recipient_config: { resolver_type: "lead_owner", params: {} },
      condition: null,
      enabled: true,
      actions: [{ step: 1, channel: "browser", template_code: null, delay_minutes: 0, config: null }],
    },
  });

  // Hydrate form when editing existing rule
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
        const rawVal = cond.value;
        if (Array.isArray(rawVal)) {
          setConditionValue(rawVal.join(", "));
        } else {
          setConditionValue(String(rawVal ?? ""));
        }
      }
    }
    setIsHydrated(true);

    // Hydrate recipient groups from rule actions
    const wizardState = hydrateFromAPI(existingRule);
    setRecipientGroups(wizardState.recipientGroups);

    // Edit mode: all steps accessible since data exists
    setHighestStepVisited(4);
  }, [existingRule, isEditMode, form]);

  // Watch form values for dynamic behavior
  const selectedEvent = form.watch("event");
  const titleTemplate = form.watch("title_template");
  const messageTemplate = form.watch("message_template");

  // Reset condition state on event change (only if not hydrating)
  useEffect(() => {
    if (isEditMode && !isHydrated) return;
    setConditionField("");
    setConditionOperator("eq");
    setConditionValue("");
    setConditionEnabled(false);
    setIsCompoundCondition(false);
    form.setValue("condition", null);
  }, [selectedEvent, form, isEditMode, isHydrated]);

  // ====== Dynamic data from metadata ======

  const dynamicEvents = useMemo<EventOption[]>(() => {
    if (!metadata?.events) return SYSTEM_EVENTS;
    return metadata.events.map((event) => ({
      value: event.event,
      label: event.display_name,
      category: event.category,
      description: event.description,
      icon: getCategoryIcon(event.category),
    }));
  }, [metadata]);

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
      { value: "zalo", status: "live" as const },
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

  const dynamicResolverTypes = useMemo<RecipientOption[]>(() => {
    if (!metadata?.resolver_types) return RECIPIENT_OPTIONS;
    return metadata.resolver_types.map((resolver) => ({
      value: resolver.value,
      label: resolver.label,
      description: resolver.description,
    }));
  }, [metadata]);

  const selectedEventData = useMemo(() => {
    return dynamicEvents.find((e) => e.value === selectedEvent);
  }, [selectedEvent, dynamicEvents]);

  const selectedEventMetadata = useMemo(() => {
    if (!metadata?.events || !selectedEvent) return null;
    return metadata.events.find((e) => e.event === selectedEvent);
  }, [metadata, selectedEvent]);

  const availableVariables = useMemo(() => {
    if (!selectedEventMetadata?.variables) {
      if (!selectedEventData) return [];
      return TEMPLATE_VARIABLES[selectedEventData.category] || [];
    }
    return selectedEventMetadata.variables.map((v) => ({
      variable: `$${v.name}`,
      label: v.description,
      description: `${v.type}${v.required ? " (bắt buộc)" : ""}`,
    }));
  }, [selectedEventMetadata, selectedEventData]);

  const groupedEvents = useMemo(() => {
    const groups: Record<string, EventOption[]> = {};
    dynamicEvents.forEach((event) => {
      const cat = event.category || "other";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(event);
    });
    return groups;
  }, [dynamicEvents]);

  const sortedCategoryKeys = useMemo(() => {
    return Object.keys(groupedEvents).sort(
      (a, b) => getCategoryOrder(a) - getCategoryOrder(b)
    );
  }, [groupedEvents]);

  // ====== Helpers ======

  const insertVariable = (field: "title_template" | "message_template", variable: string) => {
    const currentValue = form.getValues(field);
    form.setValue(field, `${currentValue}${variable} `);
  };

  const updateCondition = (field: string, operator: string, rawValue: string) => {
    if (!field || !rawValue) {
      form.setValue("condition", null);
      return;
    }
    const fieldMeta = selectedEventMetadata?.condition_fields?.find(
      (cf: { path: string; type: string }) => cf.path === field
    );
    const fieldType = fieldMeta?.type ?? "string";

    let typedValue: unknown = rawValue;
    if (operator === "in" || operator === "not_in") {
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

    form.setValue("condition", { field, operator, value: typedValue });
  };

  // ====== Submit ======

  const onSubmit = async (data: FormValues) => {
    try {
      if (allErrors.length > 0) {
        goToStep(4);
        return;
      }

      const trigger = { event: data.event, condition: data.condition, enabled: data.enabled };
      const defaultContent = {
        title_template: data.title_template,
        message_template: data.message_template,
        notification_type: data.notification_type,
        link_template: data.link_template ?? "",
      };

      const submitData = mapToAPI(recipientGroups, defaultContent, trigger);

      if (isEditMode && ruleId) {
        await updateMutation.mutateAsync({ ruleId, data: submitData });
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
      toast.error(isEditMode ? "Không thể cập nhật quy tắc" : "Không thể tạo quy tắc");
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  // ====== Unified validation ======

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

  const handleNextClick = () => {
    setAttemptedSteps((prev) => new Set(prev).add(currentStep));
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

  const handleStepClick = (targetStep: number) => {
    if (targetStep <= currentStep) {
      goToStep(targetStep);
      return;
    }
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

  // ====== Render ======

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
            <StepIndicator
              currentStep={currentStep}
              onStepClick={handleStepClick}
              stepErrors={stepErrors}
              highestStepVisited={highestStepVisited}
            />

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
                    <Button type="button" variant="outline" className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_created");
                        form.setValue("recipient_config", { resolver_type: "unit_staff", params: {} });
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
                      }}>
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Manager tạo lead → Gửi cho Officers</p>
                        <p className="text-xs text-muted-foreground">Khi manager tạo lead, gửi thông báo cho tất cả officers cùng đơn vị</p>
                      </div>
                    </Button>

                    <Button type="button" variant="outline" className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_assigned");
                        form.setValue("recipient_config", { resolver_type: "lead_owner", params: {} });
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
                      }}>
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Lead được phân công</p>
                        <p className="text-xs text-muted-foreground">Thông báo cho officer khi được gán lead mới</p>
                      </div>
                    </Button>

                    <Button type="button" variant="outline" className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "lead_assignment_failed");
                        form.setValue("recipient_config", { resolver_type: "unit_managers", params: {} });
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
                      }}>
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Phân công thất bại → Gửi Manager</p>
                        <p className="text-xs text-muted-foreground">Cảnh báo manager khi không thể phân công lead tự động</p>
                      </div>
                    </Button>

                    <Button type="button" variant="outline" className="h-auto py-3 px-4 justify-start text-left"
                      onClick={() => {
                        form.setValue("event", "consultation_reminder");
                        form.setValue("recipient_config", { resolver_type: "lead_owner", params: {} });
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
                      }}>
                      <div className="space-y-1">
                        <p className="font-medium text-sm">Nhắc lịch tư vấn</p>
                        <p className="text-xs text-muted-foreground">Nhắc officer trước khi đến giờ tư vấn</p>
                      </div>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                {/* STEP 1: Trigger */}
                {currentStep === 1 && (
                  <div className="space-y-6 animate-in fade-in-0 slide-in-from-right-4 duration-300">
                    <TriggerSection
                      value={form.watch("event")}
                      onChange={(v) => form.setValue("event", v)}
                      groupedEvents={groupedEvents}
                      sortedCategoryKeys={sortedCategoryKeys}
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
                    {shouldShowStepErrors(1) && stepErrors.step1.length > 0 && (
                      <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 space-y-1">
                        {stepErrors.step1.map((err, i) => (
                          <p key={i} className="text-sm text-destructive">{"\u2022"} {err}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* STEP 2: Content */}
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

                {/* STEP 3: Recipient Groups */}
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

                {/* STEP 4: Preview & Save */}
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
                      <Button type="button" variant="outline" onClick={prevStep} disabled={isPending}>
                        <ChevronLeft className="mr-2 h-4 w-4" />
                        Quay lại
                      </Button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button type="button" variant="ghost" onClick={() => router.back()} disabled={isPending}>
                      Hủy
                    </Button>
                    {currentStep < 4 ? (
                      <Button type="button" onClick={handleNextClick}>
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

              {/* Sidebar */}
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
