// src/components/leads/QuickConsultationSectionV2.tsx
// V2.2: Streamlined two-step layout — note fast, choose result
"use client";

import React, { useState, useMemo, useRef, useEffect } from "react";
import { toast } from "sonner";
import { format, addMinutes, addHours, addDays, set } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Loader2,
  CalendarClock,
  Phone,
  MessageSquare,
  Mail,
  Video,
  User,
  CheckCircle2,
  ChevronDown,
  Check,
  AlertTriangle,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
// Tooltip removed — Step 2 uses inline hint text instead
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DateTimePicker } from "@/components/common/form";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { useAddConsultation, useLead } from "@/hooks/useLeads";
import type {
  ConsultationStatus,
  ConsultationCreate,
  ConsultationMethod,
} from "@/types/lead.types";
import {
  LossReasonQuickSelect,
  showsLossReason,
  requiresLossReason,
} from "@/components/leads/LossReasonQuickSelect";

// =============================================================================
// TYPES & CONFIG
// =============================================================================

interface QuickConsultationSectionV2Props {
  leadId: number;
  onSuccess?: () => void;
}

type ScheduleOption = "none" | "30m" | "1h" | "tomorrow" | "custom";

const DEFAULT_METHOD: ConsultationMethod = "phone";

const methodOptions: {
  value: ConsultationMethod;
  label: string;
  icon: React.ElementType;
}[] = [
  { value: "phone", label: "Gọi điện", icon: Phone },
  { value: "sms", label: "SMS", icon: MessageSquare },
  { value: "video_call", label: "Video", icon: Video },
  { value: "email", label: "Email", icon: Mail },
  { value: "in_person", label: "Gặp mặt", icon: User },
];

// =============================================================================
// HELPERS
// =============================================================================

const getScheduledDateTime = (
  option: ScheduleOption,
  customDate?: Date
): string | null => {
  const now = new Date();
  switch (option) {
    case "none":
      return null;
    case "30m":
      return addMinutes(now, 30).toISOString();
    case "1h":
      return addHours(now, 1).toISOString();
    case "tomorrow": {
      const tomorrow = addDays(now, 1);
      return set(tomorrow, {
        hours: 9,
        minutes: 0,
        seconds: 0,
        milliseconds: 0,
      }).toISOString();
    }
    case "custom":
      return customDate ? customDate.toISOString() : null;
    default:
      return null;
  }
};

const getSchedulePreviewText = (
  option: ScheduleOption,
  customDate?: Date
): string => {
  const now = new Date();
  switch (option) {
    case "30m":
      return format(addMinutes(now, 30), "'Gọi lại lúc' HH:mm", {
        locale: vi,
      });
    case "1h":
      return format(addHours(now, 1), "'Gọi lại lúc' HH:mm", { locale: vi });
    case "tomorrow":
      return "Gọi lại lúc 09:00 ngày mai";
    case "custom":
      return customDate
        ? format(customDate, "'Gọi lại lúc' HH:mm, EEEE dd/MM", {
            locale: vi,
          })
        : "Chọn thời gian…";
    default:
      return "";
  }
};

const getOutcomeSortOrder = (
  outcomeType: string | null | undefined
): number => {
  switch (outcomeType) {
    case "positive":
      return 0;
    case "neutral":
      return 1;
    case "negative":
      return 2;
    default:
      return 1;
  }
};

// =============================================================================
// V2.2 COMPONENT
// =============================================================================

export function QuickConsultationSectionV2({
  leadId,
  onSuccess,
}: QuickConsultationSectionV2Props) {
  // --- Data ---
  const { data: lead } = useLead(leadId);
  const currentStatusId = lead?.consultation_status_id;
  const {
    data: fsmStatuses = [],
    isLoading: statusesLoading,
    error,
    isError,
  } = useAllowedNextStatuses(currentStatusId, leadId);
  const addConsultation = useAddConsultation();

  // Source of truth: lead.consultation_status is the current status.
  // FSM engine only returns configured transitions and may omit it.
  // Inject current status from lead data if FSM didn't include it.
  const statuses = useMemo(() => {
    if (!lead?.consultation_status || !currentStatusId) return fsmStatuses;
    const hasCurrentInFsm = fsmStatuses.some((s) => s.id === currentStatusId);
    if (hasCurrentInFsm) return fsmStatuses;
    return [lead.consultation_status as ConsultationStatus, ...fsmStatuses];
  }, [fsmStatuses, lead?.consultation_status, currentStatusId]);

  // --- Form state ---
  const [notes, setNotes] = useState("");
  const [scheduleOption, setScheduleOption] = useState<ScheduleOption>("none");
  const [customDateTime, setCustomDateTime] = useState<Date | undefined>();
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);
  const [method, setMethod] = useState<ConsultationMethod>(DEFAULT_METHOD);
  const [savingStatusId, setSavingStatusId] = useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);

  // --- Loss reason state ---
  const [lossReasonCode, setLossReasonCode] = useState<string | null>(null);
  const [lossReasonNote, setLossReasonNote] = useState("");

  // --- Delayed commit state ---
  const COUNTDOWN_SECONDS = 5;
  const [pendingStatus, setPendingStatus] = useState<ConsultationStatus | null>(
    null
  );
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const [countdownActive, setCountdownActive] = useState(false);
  const countdownRef = useRef<NodeJS.Timeout | null>(null);
  const isSavingRef = useRef(false);
  const pendingStatusRef = useRef<ConsultationStatus | null>(null);
  const commitSaveRef = useRef<((status: ConsultationStatus) => Promise<void>) | null>(null);

  // --- Previous stage expand ---
  const [showPreviousStage, setShowPreviousStage] = useState(false);

  // --- Form dirty detection (for beforeunload warning) ---
  const isFormDirty = useMemo(() => {
    return (
      notes.trim().length > 0 ||
      method !== DEFAULT_METHOD ||
      scheduleOption !== "none" ||
      pendingStatus !== null ||
      lossReasonCode !== null
    );
  }, [notes, method, scheduleOption, pendingStatus, lossReasonCode]);

  // --- Keep ref in sync ---
  useEffect(() => {
    pendingStatusRef.current = pendingStatus;
  }, [pendingStatus]);

  // --- Ctrl+Enter shortcut ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        const statusToSave = pendingStatusRef.current;
        if (statusToSave && !isSavingRef.current) {
          e.preventDefault();
          commitSaveRef.current?.(statusToSave);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // --- Cleanup timer on unmount ---
  useEffect(() => {
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, []);

  // --- Countdown auto-commit ---
  useEffect(() => {
    if (pendingStatus && countdown === 0 && !isSavingRef.current) {
      const statusToSave = pendingStatusRef.current;
      if (statusToSave) commitSave(statusToSave);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countdown, pendingStatus]);

  // --- Phase A: Warn on unsaved changes ---
  useEffect(() => {
    if (!isFormDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isFormDirty]);

  // ==========================================================================
  // ACTIONS
  // ==========================================================================

  const startCountdown = (status: ConsultationStatus) => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    setPendingStatus(status);
    setCountdown(COUNTDOWN_SECONDS);
    setCountdownActive(true);
    countdownRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (countdownRef.current) clearInterval(countdownRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const cancelPending = () => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    setPendingStatus(null);
    setCountdown(COUNTDOWN_SECONDS);
    setCountdownActive(false);
    setLossReasonCode(null);
    setLossReasonNote("");
  };

  const commitSave = async (status: ConsultationStatus) => {
    if (isSavingRef.current) return;
    if (requiresLossReason(status) && !lossReasonCode) {
      toast.error("Vui lòng chọn lý do mất lead trước khi lưu");
      return;
    }
    if (lossReasonCode === "OTHER" && !lossReasonNote.trim()) {
      toast.error("Vui lòng nhập lý do cụ thể");
      return;
    }

    isSavingRef.current = true;
    if (countdownRef.current) clearInterval(countdownRef.current);

    let scheduledAt: string | null = null;
    if (scheduleOption === "custom" && customDateTime) {
      scheduledAt = customDateTime.toISOString();
    } else {
      scheduledAt = getScheduledDateTime(scheduleOption);
    }

    const payload: ConsultationCreate = {
      status_id: status.id,
      method,
      notes: notes.trim() || `Ghi nhận: ${status.name}`,
      scheduled_at: scheduledAt,
      ...(lossReasonCode && {
        loss_reason_code: lossReasonCode,
        loss_reason_note: lossReasonNote || undefined,
      }),
    };

    try {
      setSavingStatusId(status.id);
      setPendingStatus(null);
      setCountdown(COUNTDOWN_SECONDS);
      setCountdownActive(false);
      await addConsultation.mutateAsync({ leadId, data: payload });
      // Reset form
      setNotes("");
      setMethod(DEFAULT_METHOD);
      setScheduleOption("none");
      setScheduleOpen(false);
      setCustomDateTime(undefined);
      setLossReasonCode(null);
      setLossReasonNote("");
      onSuccess?.();
    } catch {
      // handled by mutation
    } finally {
      setSavingStatusId(null);
      isSavingRef.current = false;
    }
  };

  useEffect(() => { commitSaveRef.current = commitSave; });

  const handleStatusClick = (status: ConsultationStatus) => {
    if (isSavingRef.current) return;
    if (pendingStatus?.id === status.id) return;

    setLossReasonCode(null);
    setLossReasonNote("");

    if (showsLossReason(status)) {
      // Negative outcome: pause countdown so officer has time to pick loss reason
      if (countdownRef.current) clearInterval(countdownRef.current);
      setPendingStatus(status);
      setCountdown(COUNTDOWN_SECONDS);
      setCountdownActive(false);
    } else {
      startCountdown(status);
    }
  };

  const handleLossReasonSelect = (code: string | null, note?: string) => {
    setLossReasonCode(code);
    if (note !== undefined) setLossReasonNote(note);

    if (!code || code === "OTHER") {
      // Cleared or OTHER: stop any running countdown
      if (countdownRef.current) clearInterval(countdownRef.current);
      setCountdownActive(false);
      setCountdown(COUNTDOWN_SECONDS);
    } else if (pendingStatus) {
      // Concrete reason selected: start countdown
      startCountdown(pendingStatus);
    }
  };

  // ==========================================================================
  // STATUS GROUPING
  // ==========================================================================

  const groupedStatuses = useMemo(() => {
    const universal: ConsultationStatus[] = [];
    const previousStage: ConsultationStatus[] = [];
    const sameStage: ConsultationStatus[] = [];
    const nextStage: ConsultationStatus[] = [];

    const currentStageOrder = lead?.pipeline_stage?.order ?? -1;
    const currentStageId = lead?.pipeline_stage_id;

    const displayStatuses = statuses.filter((s) => {
      if (s.is_universal) {
        universal.push(s);
        return false;
      }
      return true;
    });

    displayStatuses.forEach((status) => {
      const statusStageOrder = status.stage?.order ?? -1;
      if (
        statusStageOrder < currentStageOrder &&
        statusStageOrder !== -1 &&
        currentStageOrder !== -1
      ) {
        previousStage.push(status);
      } else if (
        statusStageOrder === currentStageOrder ||
        status.stage_id === currentStageId
      ) {
        sameStage.push(status);
      } else {
        nextStage.push(status);
      }
    });

    const sortByOutcomeThenOrder = (
      a: ConsultationStatus,
      b: ConsultationStatus
    ) => {
      const diff = getOutcomeSortOrder(a.outcome_type) - getOutcomeSortOrder(b.outcome_type);
      if (diff !== 0) return diff;
      return (a.display_order ?? 999) - (b.display_order ?? 999);
    };

    previousStage.sort((a, b) => {
      const diff = getOutcomeSortOrder(a.outcome_type) - getOutcomeSortOrder(b.outcome_type);
      if (diff !== 0) return diff;
      return (b.stage?.order ?? 0) - (a.stage?.order ?? 0);
    });

    sameStage.sort(sortByOutcomeThenOrder);
    nextStage.sort(sortByOutcomeThenOrder);

    return { universal, previousStage, sameStage, nextStage };
  }, [statuses, lead?.pipeline_stage?.order, lead?.pipeline_stage_id]);

  // ==========================================================================
  // RENDER HELPERS
  // ==========================================================================

  const getStatusButtonClasses = (
    status: ConsultationStatus,
    group: "previous" | "same" | "next"
  ) => {
    const isCurrentStatus = status.id === currentStatusId;
    const isPending = pendingStatus?.id === status.id;

    const base =
      "relative flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors min-h-11 sm:min-h-0";

    if (isPending) {
      return cn(base, "ring-2 ring-primary ring-offset-1 scale-[1.02]", getOutcomeBg(status.outcome_type));
    }
    if (isCurrentStatus) {
      return cn(base, "border-2 border-primary bg-primary/5 text-primary hover:bg-primary/10");
    }
    if (group === "previous") {
      return cn(base, "opacity-60 hover:opacity-90", getOutcomeBg(status.outcome_type));
    }
    return cn(base, getOutcomeBg(status.outcome_type));
  };

  const getOutcomeBg = (outcomeType: string | null | undefined) => {
    switch (outcomeType) {
      case "positive":
        return "border border-success-200 bg-success-50 text-success-700 hover:bg-success-100";
      case "negative":
        return "border border-error-200 bg-error-50 text-error-600 hover:bg-error-100";
      default:
        return "border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100";
    }
  };

  const renderStatusGrid = (
    items: ConsultationStatus[],
    group: "previous" | "same" | "next"
  ) => (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {items.map((status) => {
        const isCurrentStatus = status.id === currentStatusId;
        const isPending = pendingStatus?.id === status.id;
        return (
          <button
            key={status.id}
            type="button"
            className={getStatusButtonClasses(status, group)}
            onClick={() => handleStatusClick(status)}
            disabled={addConsultation.isPending}
            aria-label={`Chuyển sang trạng thái: ${status.name}`}
          >
            {savingStatusId === status.id ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin flex-shrink-0" />
            ) : isPending ? (
              <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0" />
            ) : isCurrentStatus ? (
              <Check className="h-3.5 w-3.5 flex-shrink-0" />
            ) : (
              <span
                className="h-2 w-2 flex-shrink-0 rounded-full"
                style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
              />
            )}
            <span className="truncate">{status.name}</span>
          </button>
        );
      })}
    </div>
  );

  // ==========================================================================
  // LOADING / ERROR / EMPTY
  // ==========================================================================

  if (statusesLoading) {
    return (
      <div className="flex items-center justify-center p-6">
        <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg bg-error-50 p-4 text-sm text-error-600">
        <p className="font-medium">Không thể tải trạng thái</p>
        <p className="mt-1 text-xs">{error?.message || "Lỗi không xác định"}</p>
      </div>
    );
  }

  if (statuses.length === 0) {
    return (
      <div className="text-muted-foreground bg-muted/50 rounded-lg p-4 text-sm">
        <p>Không có trạng thái nào được cấu hình.</p>
        <p className="mt-1 text-xs">Vui lòng liên hệ Admin để thiết lập.</p>
      </div>
    );
  }

  // ==========================================================================
  // MAIN RENDER
  // ==========================================================================

  return (
    <div id="quick-consultation-section" className="space-y-4">
      {/* ================================================================ */}
      {/* CURRENT STATUS INDICATOR                                        */}
      {/* ================================================================ */}
      {lead?.consultation_status && (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2">
          <Check className="h-4 w-4 text-primary" />
          <span className="text-xs text-muted-foreground">Hiện tại:</span>
          <div className="flex items-center gap-1.5">
            <ColorDot
              color={lead.consultation_status.color_code}
              size="sm"
            />
            <span className="text-sm font-semibold text-foreground">
              {lead.consultation_status.name}
            </span>
          </div>
          {lead.pipeline_stage && (
            <Badge variant="outline" className="ml-auto text-xs font-normal">
              {lead.pipeline_stage.name}
            </Badge>
          )}
        </div>
      )}

      {/* ================================================================ */}
      {/* STEP 1: Content (always open, no labels for fields)             */}
      {/* ================================================================ */}
      <div className="space-y-3">
        <Label className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
          Bước 1: Nội dung tư vấn
        </Label>

        {/* Method Selector — no label, self-explanatory */}
        <ToggleGroup
          type="single"
          value={method}
          onValueChange={(value) =>
            value && setMethod(value as ConsultationMethod)
          }
          className="flex flex-wrap justify-start gap-1"
        >
          {methodOptions.map((opt) => {
            const Icon = opt.icon;
            return (
              <ToggleGroupItem
                key={opt.value}
                value={opt.value}
                size="sm"
                className={cn(
                  "h-11 sm:h-8 gap-1.5 px-2.5 text-xs",
                  "data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {opt.label}
              </ToggleGroupItem>
            );
          })}
        </ToggleGroup>

        {/* Notes */}
        <Textarea
          id="quick-notes-v2"
          aria-label="Nội dung tư vấn"
          placeholder="Nội dung tư vấn..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="resize-none text-sm"
        />

        {/* Schedule — collapsed by default, click to expand */}
        <div>
          <button
            type="button"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors min-h-11 sm:min-h-0 py-2 sm:py-0"
            onClick={() => setScheduleOpen((prev) => !prev)}
          >
            <CalendarClock className="h-3.5 w-3.5" />
            <span>Đặt lịch hẹn</span>
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 transition-transform duration-200",
                scheduleOpen && "rotate-180"
              )}
            />
            {scheduleOption !== "none" && !scheduleOpen && (
              <Badge variant="secondary" className="ml-1 h-4 px-1.5 text-xs">
                {getSchedulePreviewText(scheduleOption, customDateTime)}
              </Badge>
            )}
          </button>

          {scheduleOpen && (
            <div className="mt-2 space-y-2 animate-in slide-in-from-top-1 duration-200">
              <ToggleGroup
                type="single"
                value={scheduleOption}
                onValueChange={(value) => {
                  if (value) {
                    setScheduleOption(value as ScheduleOption);
                    if (value === "custom") setIsDatePickerOpen(true);
                  }
                }}
                className="flex flex-wrap justify-start gap-1"
              >
                <ToggleGroupItem
                  value="none"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-11 sm:h-7 px-2.5 text-xs"
                >
                  Không
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="30m"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-11 sm:h-7 px-2.5 text-xs"
                >
                  30p
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="1h"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-11 sm:h-7 px-2.5 text-xs"
                >
                  1h
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="tomorrow"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-11 sm:h-7 px-2.5 text-xs"
                >
                  Ngày mai
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="custom"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-11 sm:h-7 px-2.5 text-xs"
                >
                  <CalendarClock className="mr-1 h-3 w-3" />
                  Tùy chọn
                </ToggleGroupItem>
              </ToggleGroup>

              {scheduleOption === "custom" && (
                <div className="pt-1">
                  <DateTimePicker
                    value={customDateTime}
                    onChange={(date) => setCustomDateTime(date)}
                    placeholder="Chọn ngày giờ"
                    minDate={new Date()}
                    className="h-11 sm:h-8 text-xs"
                    open={isDatePickerOpen}
                    onOpenChange={setIsDatePickerOpen}
                    hideTrigger
                  />
                </div>
              )}

              {scheduleOption !== "none" &&
                (scheduleOption === "custom" ? (
                  // Custom: box preview = nút MỞ LẠI picker để chỉnh ngày giờ
                  // (picker hideTrigger + chỉ auto-mở khi ĐỔI toggle sang custom →
                  // sau khi bấm Xong không còn đường mở lại; box này là trigger).
                  <button
                    type="button"
                    onClick={() => setIsDatePickerOpen(true)}
                    aria-label="Chỉnh sửa ngày giờ hẹn"
                    className="flex min-h-11 w-full items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-left transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 sm:min-h-0"
                  >
                    <CalendarClock className="h-4 w-4 flex-shrink-0 text-primary" />
                    <span className="flex-1 text-sm font-medium text-primary">
                      {getSchedulePreviewText(scheduleOption, customDateTime)}
                    </span>
                    <Pencil className="h-3.5 w-3.5 flex-shrink-0 text-primary/60" aria-hidden="true" />
                  </button>
                ) : (
                  <div className="flex items-center gap-2 rounded-md border border-primary/10 bg-primary/5 px-3 py-2">
                    <CalendarClock className="h-4 w-4 flex-shrink-0 text-primary" />
                    <span className="text-sm font-medium text-primary">
                      {getSchedulePreviewText(scheduleOption, customDateTime)}
                    </span>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* ================================================================ */}
      {/* STEP 2: Choose Result                                           */}
      {/* ================================================================ */}
      <div className="border-t pt-4 space-y-3">
        {/* Mobile: xếp DỌC (tiêu đề trên, gợi ý dưới) để không chật/wrap xấu;
            ngang từ sm+. */}
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
          <Label className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
            Bước 2: Kết quả tư vấn
          </Label>
          {!pendingStatus && (
            <span className="text-xs text-amber-600">
              Chọn một kết quả bên dưới để lưu
            </span>
          )}
        </div>

        {/* ── Không liên hệ được ── */}
        {groupedStatuses.universal.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs">
              Không liên hệ được
            </Label>
            <div className="flex flex-wrap gap-1.5">
              {groupedStatuses.universal.map((status) => (
                <button
                  key={status.id}
                  type="button"
                  className={cn(
                    "flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 min-h-11 sm:min-h-0",
                    pendingStatus?.id === status.id &&
                      "ring-2 ring-primary ring-offset-1"
                  )}
                  onClick={() => handleStatusClick(status)}
                  disabled={addConsultation.isPending}
                  aria-label={`Ghi nhận: ${status.name}`}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <ColorDot color={status.color_code} size="sm" />
                  )}
                  {status.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Liên hệ được ── */}
        {groupedStatuses.sameStage.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs">
              Liên hệ được
            </Label>
            {renderStatusGrid(groupedStatuses.sameStage, "same")}
          </div>
        )}

        {/* Next stage */}
        {groupedStatuses.nextStage.length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs">
              Tiến tới →
            </Label>
            {renderStatusGrid(groupedStatuses.nextStage, "next")}
          </div>
        )}

        {/* Previous stage — collapsed */}
        {groupedStatuses.previousStage.length > 0 && (
          <div>
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors min-h-11 sm:min-h-0 py-2 sm:py-0"
              onClick={() => setShowPreviousStage((prev) => !prev)}
            >
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform duration-200",
                  showPreviousStage && "rotate-180"
                )}
              />
              Xem thêm (giai đoạn trước)
            </button>
            {showPreviousStage && (
              <div className="mt-2 animate-in slide-in-from-top-1 duration-200">
                {renderStatusGrid(groupedStatuses.previousStage, "previous")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ================================================================ */}
      {/* TERMINAL WARNING (is_final status — e.g. "Đã ngừng tư vấn")      */}
      {/* Thin-client: trust the is_final flag from the API, not a hardcoded id */}
      {/* ================================================================ */}
      {pendingStatus?.is_final && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 animate-in slide-in-from-top-2 duration-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>
            <strong>Trạng thái cuối.</strong> Lead sẽ ngừng tư vấn và{" "}
            <strong>không thể tiếp tục</strong> trừ khi được mở lại (cần
            manager/admin duyệt).
          </span>
        </div>
      )}

      {/* ================================================================ */}
      {/* LOSS REASON (Conditional)                                       */}
      {/* ================================================================ */}
      {pendingStatus && showsLossReason(pendingStatus) && (
        <div className="animate-in slide-in-from-top-2 duration-200">
          <LossReasonQuickSelect
            value={lossReasonCode}
            onChange={handleLossReasonSelect}
            note={lossReasonNote}
            onNoteChange={setLossReasonNote}
            required={requiresLossReason(pendingStatus)}
          />
        </div>
      )}

      {/* ================================================================ */}
      {/* DELAYED COMMIT BAR                                              */}
      {/* ================================================================ */}
      {pendingStatus &&
        (lossReasonCode || !requiresLossReason(pendingStatus)) && (
          <div className="animate-in slide-in-from-top-2 overflow-hidden rounded-lg border border-primary/20 bg-primary/5 duration-200">
            <div
              key={pendingStatus.id + (countdownActive ? "-active" : "")}
              className={cn("h-1 bg-primary", countdownActive ? "countdown-bar" : "w-full")}
            />

            <div className="flex items-center justify-between gap-2 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-primary" />
                <span className="truncate text-sm text-primary">
                  Sẽ lưu: <strong>{pendingStatus.name}</strong>
                </span>
              </div>

              <div className="flex flex-shrink-0 items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-11 sm:h-7 px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={cancelPending}
                >
                  Hoàn tác
                </Button>
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  className="h-11 sm:h-7 px-3 text-xs"
                  onClick={() => commitSave(pendingStatus)}
                  disabled={addConsultation.isPending}
                  title="Ctrl+Enter để lưu nhanh"
                >
                  {addConsultation.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <>
                      Lưu ngay
                      <kbd className="ml-1.5 hidden items-center rounded bg-primary-foreground/20 px-1 py-0.5 font-mono text-[9px] sm:inline-flex">
                        {typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent) ? "⌘↵" : "Ctrl+↵"}
                      </kbd>
                    </>
                  )}
                </Button>
                <span className="w-4 text-center text-xs font-medium text-primary">
                  {countdown}s
                </span>
              </div>
            </div>
          </div>
        )}
    </div>
  );
}

export default QuickConsultationSectionV2;
