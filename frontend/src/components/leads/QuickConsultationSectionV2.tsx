// src/components/leads/QuickConsultationSectionV2.tsx
// V2: Status-first layout with progressive disclosure
"use client";

import React, { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { format, addMinutes, addHours, addDays, set } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Loader2,
  Clock,
  CalendarClock,
  HelpCircle,
  Phone,
  MessageSquare,
  Mail,
  Video,
  User,
  CheckCircle2,
  ChevronDown,
  NotebookPen,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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

const methodOptions: {
  value: ConsultationMethod;
  label: string;
  icon: React.ElementType;
}[] = [
  { value: "phone", label: "Gọi điện", icon: Phone },
  { value: "email", label: "Email", icon: Mail },
  { value: "video_call", label: "Video", icon: Video },
  { value: "sms", label: "SMS", icon: MessageSquare },
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
// V2 COMPONENT
// =============================================================================

export function QuickConsultationSectionV2({
  leadId,
  onSuccess,
}: QuickConsultationSectionV2Props) {
  // --- Data ---
  const { data: lead } = useLead(leadId);
  const currentStatusId = lead?.consultation_status_id;
  const {
    data: statuses = [],
    isLoading: statusesLoading,
    error,
    isError,
  } = useAllowedNextStatuses(currentStatusId, leadId);
  const addConsultation = useAddConsultation();

  // --- Form state ---
  const [notes, setNotes] = useState("");
  const [scheduleOption, setScheduleOption] = useState<ScheduleOption>("none");
  const [customDateTime, setCustomDateTime] = useState<Date | undefined>();
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);
  const [method, setMethod] = useState<ConsultationMethod>("phone");
  const [savingStatusId, setSavingStatusId] = useState<string | null>(null);

  // --- Loss reason state ---
  const [lossReasonCode, setLossReasonCode] = useState<string | null>(null);
  const [lossReasonNote, setLossReasonNote] = useState("");

  // --- Delayed commit state ---
  const COUNTDOWN_SECONDS = 3;
  const [pendingStatus, setPendingStatus] = useState<ConsultationStatus | null>(
    null
  );
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const countdownRef = useRef<NodeJS.Timeout | null>(null);
  const isSavingRef = useRef(false);
  const pendingStatusRef = useRef<ConsultationStatus | null>(null);
  const commitSaveRef = useRef<((status: ConsultationStatus) => Promise<void>) | null>(null);

  // --- Collapsible details ---
  // Initialize as false to avoid hydration mismatch, sync from localStorage after mount
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("qc-details-open");
    if (stored === "true") setDetailsOpen(true);
  }, []);

  // Persist collapse state
  const toggleDetails = useCallback(() => {
    setDetailsOpen((prev) => {
      const next = !prev;
      localStorage.setItem("qc-details-open", String(next));
      return next;
    });
  }, []);

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
  }, [countdown, pendingStatus]);

  // ==========================================================================
  // ACTIONS
  // ==========================================================================

  const startCountdown = (status: ConsultationStatus) => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    setPendingStatus(status);
    setCountdown(COUNTDOWN_SECONDS);
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
    setLossReasonCode(null);
    setLossReasonNote("");
  };

  const commitSave = async (status: ConsultationStatus) => {
    if (isSavingRef.current) return;
    if (requiresLossReason(status) && !lossReasonCode) {
      toast.error("Vui lòng chọn lý do mất lead trước khi lưu");
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
      await addConsultation.mutateAsync({ leadId, data: payload });
      // Reset form
      setNotes("");
      setScheduleOption("none");
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

  // Keep commitSaveRef pointing to the latest commitSave so the Ctrl+Enter
  // handler (which has empty deps) always calls the current version.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { commitSaveRef.current = commitSave; });

  const handleStatusClick = (status: ConsultationStatus) => {
    if (isSavingRef.current) return;
    if (pendingStatus?.id === status.id) return;

    setLossReasonCode(null);
    setLossReasonNote("");

    if (requiresLossReason(status)) {
      if (countdownRef.current) clearInterval(countdownRef.current);
      setPendingStatus(status);
      setCountdown(COUNTDOWN_SECONDS);
    } else {
      startCountdown(status);
    }
  };

  const handleLossReasonSelect = (code: string | null, note?: string) => {
    setLossReasonCode(code);
    if (note !== undefined) setLossReasonNote(note);
    if (code && pendingStatus) startCountdown(pendingStatus);
  };

  // ==========================================================================
  // STATUS GROUPING (Same logic as V1, reused)
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

    // Sort: Positive → Neutral → Negative, then display_order
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

    sameStage.sort((a, b) => {
      const diff = getOutcomeSortOrder(a.outcome_type) - getOutcomeSortOrder(b.outcome_type);
      if (diff !== 0) return diff;
      if (a.id === currentStatusId) return -1;
      if (b.id === currentStatusId) return 1;
      return (a.display_order ?? 999) - (b.display_order ?? 999);
    });

    nextStage.sort(sortByOutcomeThenOrder);

    return { universal, previousStage, sameStage, nextStage };
  }, [statuses, currentStatusId, lead?.pipeline_stage?.order, lead?.pipeline_stage_id]);

  const hasResultStatuses =
    groupedStatuses.previousStage.length > 0 ||
    groupedStatuses.sameStage.length > 0 ||
    groupedStatuses.nextStage.length > 0;

  // ==========================================================================
  // RENDER
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

  // Helper: get style classes for a status button
  const getStatusButtonClasses = (
    status: ConsultationStatus,
    group: "previous" | "same" | "next"
  ) => {
    const isCurrentStatus = status.id === currentStatusId;
    const isPending = pendingStatus?.id === status.id;

    const base =
      "relative flex items-center gap-2 rounded-lg px-3 text-sm font-medium min-h-[40px] transition-colors";

    if (isCurrentStatus) {
      return cn(base, "border-2 border-primary bg-primary/5 text-primary", "cursor-default");
    }
    if (isPending) {
      return cn(base, "ring-2 ring-primary ring-offset-1 scale-[1.02]", getOutcomeBg(status.outcome_type));
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

  // Render a group of status buttons in a grid
  const renderStatusGrid = (
    items: ConsultationStatus[],
    group: "previous" | "same" | "next"
  ) => (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {items.map((status) => {
        const isCurrentStatus = status.id === currentStatusId;
        return (
          <button
            key={status.id}
            type="button"
            className={getStatusButtonClasses(status, group)}
            onClick={() => { if (!isCurrentStatus) handleStatusClick(status); }}
            disabled={addConsultation.isPending || isCurrentStatus}
            aria-label={`Chuyển sang trạng thái: ${status.name}`}
          >
            {savingStatusId === status.id ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin flex-shrink-0" />
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

  return (
    <div className="space-y-4">
      {/* ================================================================ */}
      {/* SECTION 1: Current Status Indicator                              */}
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
            <Badge variant="outline" className="ml-auto text-[10px] font-normal">
              {lead.pipeline_stage.name}
            </Badge>
          )}
        </div>
      )}

      {/* ================================================================ */}
      {/* SECTION 2: Result Statuses — Grouped Grid (PRIMARY ACTION)       */}
      {/* ================================================================ */}
      {hasResultStatuses && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <Label className="text-muted-foreground text-xs font-medium">
              Chọn kết quả
            </Label>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <HelpCircle className="text-muted-foreground/50 h-3.5 w-3.5 cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[220px] text-xs">
                  <p>Click vào trạng thái để ghi nhận kết quả tư vấn. Bạn có 3 giây để hoàn tác.</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          {/* Grouped result statuses */}
          <div className="space-y-3">
            {/* Previous stage (revert) */}
            {groupedStatuses.previousStage.length > 0 && (
              <div>
                <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mb-1.5">
                  ← Giai đoạn trước
                </div>
                {renderStatusGrid(groupedStatuses.previousStage, "previous")}
              </div>
            )}

            {/* Same stage (current) */}
            {groupedStatuses.sameStage.length > 0 && (
              <div>
                {groupedStatuses.previousStage.length > 0 && (
                  <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mb-1.5">
                    Giai đoạn hiện tại
                  </div>
                )}
                {renderStatusGrid(groupedStatuses.sameStage, "same")}
              </div>
            )}

            {/* Next stage (progress) */}
            {groupedStatuses.nextStage.length > 0 && (
              <div>
                <div className="text-[10px] text-muted-foreground/60 uppercase tracking-wider mb-1.5">
                  Tiến tới →
                </div>
                {renderStatusGrid(groupedStatuses.nextStage, "next")}
              </div>
            )}
          </div>

          {/* Gradient progress bar */}
          {(() => {
            const prevColor = groupedStatuses.previousStage.length > 0
              ? sanitizeColorCode(groupedStatuses.previousStage[groupedStatuses.previousStage.length - 1].color_code, "#e2e8f0")
              : "#e2e8f0";
            const currColor = sanitizeColorCode(
              groupedStatuses.sameStage.find((s) => s.id === currentStatusId)?.color_code
                || groupedStatuses.sameStage[0]?.color_code,
              "#3b82f6"
            );
            const nextColor = groupedStatuses.nextStage.length > 0
              ? sanitizeColorCode(groupedStatuses.nextStage[0].color_code, "#a7f3d0")
              : "#a7f3d0";
            return (
              <div
                className="mt-1 h-1 rounded-full opacity-80"
                style={{ background: `linear-gradient(to right, ${prevColor}, ${currColor}, ${nextColor})` }}
              />
            );
          })()}
        </div>
      )}

      {/* ================================================================ */}
      {/* SECTION 2b: Universal Statuses — Smaller, Secondary              */}
      {/* ================================================================ */}
      {groupedStatuses.universal.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Label className="text-muted-foreground text-[11px]">
              Ghi nhận liên hệ
            </Label>
            <Badge
              variant="secondary"
              className="h-4 bg-amber-100 px-1.5 text-[10px] text-amber-700"
            >
              không đổi trạng thái
            </Badge>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {groupedStatuses.universal.map((status) => (
              <button
                key={status.id}
                type="button"
                className={cn(
                  "flex items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100",
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

      {/* ================================================================ */}
      {/* SECTION 3: Loss Reason (Conditional)                             */}
      {/* ================================================================ */}
      {pendingStatus && requiresLossReason(pendingStatus) && (
        <div className="animate-in slide-in-from-top-2 duration-200">
          <LossReasonQuickSelect
            value={lossReasonCode}
            onChange={handleLossReasonSelect}
            note={lossReasonNote}
            onNoteChange={setLossReasonNote}
            required
          />
        </div>
      )}

      {/* ================================================================ */}
      {/* SECTION 4: Delayed Commit Confirmation Bar                       */}
      {/* ================================================================ */}
      {pendingStatus &&
        (lossReasonCode || !requiresLossReason(pendingStatus)) && (
          <div className="animate-in slide-in-from-top-2 overflow-hidden rounded-lg border border-primary/20 bg-primary/5 duration-200">
            {/* Progress bar */}
            <div
              className="h-1 bg-primary transition-[width] duration-1000 ease-linear"
              style={{ width: `${(countdown / COUNTDOWN_SECONDS) * 100}%` }}
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
                  className="h-7 px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={cancelPending}
                >
                  Hoàn tác
                </Button>
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  className="h-7 px-3 text-xs"
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
                        ⌘↵
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

      {/* ================================================================ */}
      {/* SECTION 5: Collapsible Details (Method + Notes + Schedule)       */}
      {/* ================================================================ */}
      <div className="border-t pt-3">
        <button
          type="button"
          className="flex w-full items-center justify-between rounded-md px-1 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          onClick={toggleDetails}
          aria-expanded={detailsOpen}
        >
          <span className="flex items-center gap-1.5 font-medium">
            <NotebookPen className="h-3 w-3" />
            Chi tiết tư vấn
            {/* Show indicators when details have values but section is collapsed */}
            {!detailsOpen && (notes || scheduleOption !== "none") && (
              <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                {[notes && "ghi chú", scheduleOption !== "none" && "lịch hẹn"]
                  .filter(Boolean)
                  .join(", ")}
              </Badge>
            )}
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform duration-200",
              detailsOpen && "rotate-180"
            )}
          />
        </button>

        {detailsOpen && (
          <div className="animate-in slide-in-from-top-1 mt-3 space-y-3 duration-200">
            {/* Method Selector */}
            <div className="space-y-1.5">
              <Label className="text-muted-foreground flex items-center gap-1 text-xs">
                <Phone className="h-3 w-3" />
                Phương thức
              </Label>
              <ToggleGroup
                type="single"
                value={method}
                onValueChange={(value) =>
                  value && setMethod(value as ConsultationMethod)
                }
                className="flex justify-start gap-1"
              >
                {methodOptions.map((opt) => {
                  const Icon = opt.icon;
                  return (
                    <ToggleGroupItem
                      key={opt.value}
                      value={opt.value}
                      size="sm"
                      className={cn(
                        "h-8 gap-1.5 px-2.5 text-xs",
                        "data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">{opt.label}</span>
                    </ToggleGroupItem>
                  );
                })}
              </ToggleGroup>
            </div>

            {/* Notes Input */}
            <div className="space-y-1.5">
              <Label
                htmlFor="quick-notes-v2"
                className="text-muted-foreground flex items-center gap-1 text-xs"
              >
                <NotebookPen className="h-3 w-3" />
                Nội dung tư vấn
              </Label>
              <Textarea
                id="quick-notes-v2"
                placeholder="VD: KH hẹn gọi lại lúc 3h chiều…"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="resize-none text-sm"
              />
            </div>

            {/* Schedule Section */}
            <div className="space-y-2">
              <Label className="text-muted-foreground flex items-center gap-1.5 text-xs">
                <Clock className="h-3 w-3" />
                Hẹn gọi lại
              </Label>

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
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-7 px-2.5 text-xs"
                >
                  Không
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="30m"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-7 px-2.5 text-xs"
                >
                  30p
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="1h"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-7 px-2.5 text-xs"
                >
                  1h
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="tomorrow"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-7 px-2.5 text-xs"
                >
                  Ngày mai
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="custom"
                  size="sm"
                  className="data-[state=on]:bg-primary data-[state=on]:text-primary-foreground h-7 px-2.5 text-xs"
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
                    className="h-8 text-xs"
                    open={isDatePickerOpen}
                    onOpenChange={setIsDatePickerOpen}
                    hideTrigger
                  />
                </div>
              )}

              {scheduleOption !== "none" && (
                <div className="flex items-center gap-2 rounded-md border border-primary/10 bg-primary/5 px-3 py-2">
                  <CalendarClock className="h-4 w-4 flex-shrink-0 text-primary" />
                  <span className="text-sm font-medium text-primary">
                    {getSchedulePreviewText(scheduleOption, customDateTime)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default QuickConsultationSectionV2;
