// src/components/leads/QuickConsultationSection.tsx
"use client";

import React, { useState, useMemo, useRef, useEffect } from "react";
import { format, addMinutes, addHours, addDays, set } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Loader2,
  Clock,
  CalendarClock,
  ArrowRight,
  HelpCircle,
  PhoneForwarded,
  BookmarkCheck,
  NotebookPen,
  Phone,
  MessageSquare,
  Mail,
  Video,
  User,
  CheckCircle2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DateTimePicker } from "@/components/common/form";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { useAddConsultation, useLead } from "@/hooks/useLeads";
import type { ConsultationStatus, ConsultationCreate, ConsultationMethod } from "@/types/lead.types";
import { LossReasonQuickSelect, requiresLossReason } from "@/components/leads/LossReasonQuickSelect";

interface QuickConsultationSectionProps {
  leadId: number;
  onSuccess?: () => void;
}

// Schedule option type
type ScheduleOption = "none" | "30m" | "1h" | "tomorrow" | "custom";

// Method options configuration
const methodOptions: { value: ConsultationMethod; label: string; icon: React.ElementType }[] = [
  { value: "phone", label: "Gọi điện", icon: Phone },
  { value: "email", label: "Email", icon: Mail },
  { value: "video_call", label: "Video", icon: Video },
  { value: "sms", label: "SMS", icon: MessageSquare },
  { value: "in_person", label: "Gặp mặt", icon: User },
];

// Get scheduled datetime based on option
const getScheduledDateTime = (option: ScheduleOption, customDate?: Date): string | null => {
  const now = new Date();

  switch (option) {
    case "none":
      return null;
    case "30m":
      return addMinutes(now, 30).toISOString();
    case "1h":
      return addHours(now, 1).toISOString();
    case "tomorrow":
      // Tomorrow at 9:00 AM
      const tomorrow = addDays(now, 1);
      return set(tomorrow, { hours: 9, minutes: 0, seconds: 0, milliseconds: 0 }).toISOString();
    case "custom":
      return customDate ? customDate.toISOString() : null;
    default:
      return null;
  }
};

// Get preview text for schedule option
const getSchedulePreviewText = (option: ScheduleOption, customDate?: Date): string => {
  const now = new Date();
  switch (option) {
    case "30m":
      return format(addMinutes(now, 30), "'Gọi lại lúc' HH:mm", { locale: vi });
    case "1h":
      return format(addHours(now, 1), "'Gọi lại lúc' HH:mm", { locale: vi });
    case "tomorrow":
      return "Gọi lại lúc 09:00 ngày mai";
    case "custom":
      return customDate
        ? format(customDate, "'Gọi lại lúc' HH:mm, EEEE dd/MM", { locale: vi })
        : "Chọn thời gian...";
    default:
      return "";
  }
};

// ✅ Get color classes based on outcome_type
const getOutcomeColorClasses = (
  outcomeType: string | null | undefined,
  isCurrentStatus: boolean = false
): string => {
  if (isCurrentStatus) {
    // Current status always highlighted with ring
    return "border-2 border-info-500 bg-info-100 font-medium text-info-700 hover:bg-info-100/80";
  }

  switch (outcomeType) {
    case "positive":
      return "border border-success-200 bg-success-50 text-success-700 hover:bg-success-100";
    case "negative":
      return "border border-error-200 bg-error-50 text-error-600 hover:bg-error-100";
    case "neutral":
    default:
      return "border border-info-200 bg-info-50 text-info-700 hover:bg-info-100";
  }
};

// ✅ Get sort order for outcome_type: Positive → Neutral → Negative
const getOutcomeSortOrder = (outcomeType: string | null | undefined): number => {
  switch (outcomeType) {
    case "positive":
      return 0;
    case "neutral":
      return 1;
    case "negative":
      return 2;
    default:
      return 1; // Default to neutral
  }
};



export function QuickConsultationSection({ leadId, onSuccess }: QuickConsultationSectionProps) {
  // Get lead data to determine current consultation status
  const { data: lead } = useLead(leadId);
  const currentStatusId = lead?.consultation_status_id;

  // Get allowed next statuses based on state machine
  // ✅ FIX: Pass leadId to derive correct phase from admission_profile
  const {
    data: statuses = [],
    isLoading: statusesLoading,
    error,
    isError,
  } = useAllowedNextStatuses(currentStatusId, leadId);
  const addConsultation = useAddConsultation();

  // Form state
  const [notes, setNotes] = useState("");
  const [scheduleOption, setScheduleOption] = useState<ScheduleOption>("none");
  const [customDateTime, setCustomDateTime] = useState<Date | undefined>(undefined);
  const [savingStatusId, setSavingStatusId] = useState<string | null>(null);
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);
  const [method, setMethod] = useState<ConsultationMethod>("phone");

  // Loss reason state (for negative final statuses)
  const [lossReasonCode, setLossReasonCode] = useState<string | null>(null);
  const [lossReasonNote, setLossReasonNote] = useState("");

  // ✅ DELAYED COMMIT STATE
  const COUNTDOWN_SECONDS = 3;
  const [pendingStatus, setPendingStatus] = useState<ConsultationStatus | null>(null);
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const countdownRef = useRef<NodeJS.Timeout | null>(null);
  // ✅ FIX: Guard against concurrent saves
  const isSavingRef = useRef(false);
  // ✅ FIX: Store pending status in ref to avoid stale closure
  const pendingStatusRef = useRef<ConsultationStatus | null>(null);

  // Keep ref in sync with state
  useEffect(() => {
    pendingStatusRef.current = pendingStatus;
  }, [pendingStatus]);

  // ✅ Ctrl+Enter keyboard shortcut to save immediately
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Enter (or Cmd+Enter on Mac) commits pending status immediately
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        const statusToSave = pendingStatusRef.current;
        if (statusToSave && !isSavingRef.current) {
          e.preventDefault();
          commitSave(statusToSave);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []); // Empty deps - uses refs for current values

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (countdownRef.current) {
        clearInterval(countdownRef.current);
      }
    };
  }, []);

  // Countdown logic - when countdown reaches 0, commit the save
  useEffect(() => {
    // ✅ FIX: Check isSavingRef to prevent concurrent saves
    if (pendingStatus && countdown === 0 && !isSavingRef.current) {
      // Use ref to get the latest pending status
      const statusToSave = pendingStatusRef.current;
      if (statusToSave) {
        commitSave(statusToSave);
      }
    }
  }, [countdown, pendingStatus]);

  // Start countdown when pending status is set
  const startCountdown = (status: ConsultationStatus) => {
    // Clear any existing timer
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
    }
    
    setPendingStatus(status);
    setCountdown(COUNTDOWN_SECONDS);
    
    countdownRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (countdownRef.current) {
            clearInterval(countdownRef.current);
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // Cancel pending save
  const cancelPending = () => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
    }
    setPendingStatus(null);
    setCountdown(COUNTDOWN_SECONDS);
    setLossReasonCode(null);
    setLossReasonNote("");
  };

  // Commit the save immediately
  const commitSave = async (status: ConsultationStatus) => {
    // ✅ FIX: Guard against concurrent saves
    if (isSavingRef.current) {
      return;
    }

    // Validate loss reason for negative final statuses
    if (requiresLossReason(status) && !lossReasonCode) {
      return;
    }

    isSavingRef.current = true;

    if (countdownRef.current) {
      clearInterval(countdownRef.current);
    }

    // Determine scheduled_at based on option
    let scheduledAt: string | null = null;
    if (scheduleOption === "custom" && customDateTime) {
      scheduledAt = customDateTime.toISOString();
    } else {
      scheduledAt = getScheduledDateTime(scheduleOption);
    }

    const payload: ConsultationCreate = {
      status_id: status.id,
      method: method,
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

      // Reset form on success
      setNotes("");
      setScheduleOption("none");
      setCustomDateTime(undefined);
      setLossReasonCode(null);
      setLossReasonNote("");

      onSuccess?.();
    } catch {
      // Error is handled by the mutation
    } finally {
      setSavingStatusId(null);
      isSavingRef.current = false;
    }
  };

  // Handle loss reason selection — start countdown once reason is chosen
  const handleLossReasonSelect = (code: string | null, note?: string) => {
    setLossReasonCode(code);
    if (note !== undefined) setLossReasonNote(note);
    // Reason selected → start countdown
    if (code && pendingStatus) {
      startCountdown(pendingStatus);
    }
  };

  // Handle status badge click - start delayed commit
  const handleStatusClick = (status: ConsultationStatus) => {
    // ✅ FIX: Don't start new countdown while saving
    if (isSavingRef.current) return;

    // If clicking the same pending status, do nothing
    if (pendingStatus?.id === status.id) return;

    // Reset loss reason state when selecting a new status
    setLossReasonCode(null);
    setLossReasonNote("");

    if (requiresLossReason(status)) {
      // Negative final: pause for loss reason selection (no countdown yet)
      if (countdownRef.current) clearInterval(countdownRef.current);
      setPendingStatus(status);
      setCountdown(COUNTDOWN_SECONDS);
    } else {
      // Normal flow: start countdown immediately
      startCountdown(status);
    }
  };

  // ✅ Drag-to-scroll using callback refs with proper cleanup
  // Callback refs are called when element mounts, guaranteeing element exists
  const resultHasDraggedRef = useRef(false);
  const universalHasDraggedRef = useRef(false);

  // ✅ FIX: Store cleanup functions to prevent memory leaks
  const cleanupFunctionsRef = useRef<Map<HTMLDivElement, () => void>>(new Map());

  // Cleanup all listeners on unmount
  useEffect(() => {
    return () => {
      cleanupFunctionsRef.current.forEach((cleanup) => cleanup());
      cleanupFunctionsRef.current.clear();
    };
  }, []);

  const setupDragToScroll = (element: HTMLDivElement | null, hasDraggedRef: React.MutableRefObject<boolean>) => {
    // Clean up previous listeners for this element if any
    if (element && cleanupFunctionsRef.current.has(element)) {
      cleanupFunctionsRef.current.get(element)?.();
      cleanupFunctionsRef.current.delete(element);
    }

    if (!element) return;

    const isDragging = { current: false };
    const startX = { current: 0 };
    const scrollLeftStart = { current: 0 };

    // Wheel scroll handler
    const handleWheel = (e: WheelEvent) => {
      if (e.deltaY === 0) return;
      if (element.scrollWidth <= element.clientWidth) return;

      const { scrollLeft: sl, scrollWidth, clientWidth } = element;
      const maxScrollLeft = scrollWidth - clientWidth;

      if (e.deltaY > 0 && sl >= maxScrollLeft - 1) return;
      if (e.deltaY < 0 && sl <= 1) return;

      e.preventDefault();
      element.scrollLeft += e.deltaY;
    };

    const handleMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      hasDraggedRef.current = false;
      isDragging.current = true;
      startX.current = e.pageX - element.offsetLeft;
      scrollLeftStart.current = element.scrollLeft;
      element.style.cursor = "grabbing";
      element.style.userSelect = "none";
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      e.preventDefault();
      const x = e.pageX - element.offsetLeft;
      const walk = (x - startX.current) * 1.5;
      if (Math.abs(x - startX.current) > 5) hasDraggedRef.current = true;
      element.scrollLeft = scrollLeftStart.current - walk;
    };

    const handleMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      element.style.cursor = "grab";
      element.style.removeProperty("user-select");
    };

    const handleMouseLeave = () => {
      if (isDragging.current) {
        isDragging.current = false;
        element.style.cursor = "grab";
        element.style.removeProperty("user-select");
      }
    };

    element.style.cursor = "grab";
    element.addEventListener("wheel", handleWheel, { passive: false });
    element.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    element.addEventListener("mouseleave", handleMouseLeave);

    // ✅ FIX: Store cleanup function
    const cleanup = () => {
      element.removeEventListener("wheel", handleWheel);
      element.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      element.removeEventListener("mouseleave", handleMouseLeave);
    };
    cleanupFunctionsRef.current.set(element, cleanup);
  };
  
  // Callback refs that setup listeners when elements mount
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const universalScrollRef = useRef<HTMLDivElement | null>(null);
  
  // Setup when component mounts
  useEffect(() => {
    if (scrollContainerRef.current) {
      setupDragToScroll(scrollContainerRef.current, resultHasDraggedRef);
    }
    if (universalScrollRef.current) {
      setupDragToScroll(universalScrollRef.current, universalHasDraggedRef);
    }
  }, [statuses]); // Re-run when statuses change (containers might re-render)

  // ✅ REFACTORED GROUPING LOGIC (Previous -> Same -> Next)
  const groupedStatuses = useMemo(() => {
    // 1. Universal (Toàn cục - Row 1)
    const universal: ConsultationStatus[] = [];

    // 2. Result Groups (Kết quả - Row 2)
    const previousStage: ConsultationStatus[] = [];
    const sameStage: ConsultationStatus[] = [];
    const nextStage: ConsultationStatus[] = [];

    // ✅ FIX: Get current stage from LEAD object (not from allowed next statuses)
    // The current status is NOT in the "allowed next statuses" list
    const currentStageOrder = lead?.pipeline_stage?.order ?? -1;
    const currentStageId = lead?.pipeline_stage_id;

    const displayStatuses = statuses.filter(s => {
      if (s.is_universal) {
        universal.push(s);
        return false; // Move to universal array
      }
      return true;
    });

    displayStatuses.forEach((status) => {
      // Logic: Previous vs Same vs Next
      // We rely on stage.order from the status's associated stage
      const statusStageOrder = status.stage?.order ?? -1;

      // Grouping logic
      if (statusStageOrder < currentStageOrder && statusStageOrder !== -1 && currentStageOrder !== -1) {
        // PREVIOUS STAGE (Revert)
        previousStage.push(status);
      } else if (statusStageOrder === currentStageOrder || status.stage_id === currentStageId) {
        // SAME STAGE (Sibling / Current)
        sameStage.push(status);
      } else {
        // NEXT STAGE (Progress)
        nextStage.push(status);
      }
    });

    // ✅ Sort each group by: outcome_type (Positive → Neutral → Negative), then display_order
    const sortByOutcomeThenOrder = (a: ConsultationStatus, b: ConsultationStatus) => {
      const outcomeA = getOutcomeSortOrder(a.outcome_type);
      const outcomeB = getOutcomeSortOrder(b.outcome_type);
      if (outcomeA !== outcomeB) return outcomeA - outcomeB;
      // Secondary sort by display_order
      return (a.display_order ?? 999) - (b.display_order ?? 999);
    };

    // Sort Previous: outcome_type first, then by stage order (closest to current)
    previousStage.sort((a, b) => {
      const outcomeA = getOutcomeSortOrder(a.outcome_type);
      const outcomeB = getOutcomeSortOrder(b.outcome_type);
      if (outcomeA !== outcomeB) return outcomeA - outcomeB;
      // Within same outcome, sort by stage order desc (closest to current first)
      return (b.stage?.order ?? 0) - (a.stage?.order ?? 0);
    });

    // Sort Same Stage: outcome_type first, current status within its group, then display_order
    sameStage.sort((a, b) => {
      const outcomeA = getOutcomeSortOrder(a.outcome_type);
      const outcomeB = getOutcomeSortOrder(b.outcome_type);
      if (outcomeA !== outcomeB) return outcomeA - outcomeB;
      // Current status first within its outcome group
      if (a.id === currentStatusId) return -1;
      if (b.id === currentStatusId) return 1;
      return (a.display_order ?? 999) - (b.display_order ?? 999);
    });

    // Sort Next: outcome_type first, then by stage order (furthest first = most progress)
    nextStage.sort(sortByOutcomeThenOrder);

    return { universal, previousStage, sameStage, nextStage };
  }, [statuses, currentStatusId, lead?.pipeline_stage?.order, lead?.pipeline_stage_id]);

  // Loading state
  if (statusesLoading) {
    return (
      <div className="flex items-center justify-center p-4">
        <Loader2 className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="rounded-md bg-error-50 p-4 text-sm text-error-600">
        <p className="font-medium">Không thể tải trạng thái</p>
        <p className="mt-1 text-xs">{error?.message || "Lỗi không xác định"}</p>
      </div>
    );
  }

  // Empty state
  if (statuses.length === 0) {
    return (
      <div className="text-muted-foreground bg-muted/50 rounded-md p-4 text-sm">
        <p>Không có trạng thái nào được cấu hình.</p>
        <p className="mt-1 text-xs">Vui lòng liên hệ Admin để thiết lập.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Method Selector */}
      <div className="space-y-1.5">
        <Label className="text-muted-foreground flex items-center gap-1 text-xs">
          <Phone className="h-3 w-3" />
          Phương thức
        </Label>
        <ToggleGroup
          type="single"
          value={method}
          onValueChange={(value) => value && setMethod(value as ConsultationMethod)}
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
          htmlFor="quick-notes"
          className="text-muted-foreground flex items-center gap-1 text-xs"
        >
          <NotebookPen className="h-3 w-3" />
          Nội dung tư vấn (tùy chọn)
        </Label>
        <Textarea
          id="quick-notes"
          placeholder="VD: KH hẹn gọi lại lúc 3h chiều..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="resize-none text-sm"
        />
      </div>

      {/* Schedule Section with ToggleGroup */}
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
              // Tự động mở DateTimePicker khi chọn "Tùy chọn"
              if (value === "custom") {
                setIsDatePickerOpen(true);
              }
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

        {/* Custom DateTime Picker */}
        {scheduleOption === "custom" && (
          <div className="pt-2">
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

        {/* Enhanced Schedule Preview */}
        {scheduleOption !== "none" && (
          <div className="flex items-center gap-2 rounded-md border border-info-100 bg-info-50 px-3 py-2">
            <CalendarClock className="h-4 w-4 flex-shrink-0 text-info-600" />
            <span className="text-sm font-medium text-info-700">
              {getSchedulePreviewText(scheduleOption, customDateTime)}
            </span>
          </div>
        )}
      </div>

      {/* Divider */}
      <div className="border-t pt-3">
        {/* ROW 1: Universal Statuses (Trạng thái liên hệ) */}
        {groupedStatuses.universal.length > 0 && (
          <div className="mb-4">
            <div className="text-muted-foreground mb-2 flex items-center gap-2 text-xs">
              <PhoneForwarded className="h-3 w-3" />
              <span className="font-medium">Trạng thái liên hệ</span>
              <Badge
                variant="secondary"
                className="ml-1 h-4 bg-warning-100 px-1.5 text-[10px] text-warning-700"
              >
                không đổi trạng thái
              </Badge>
            </div>
            {/* ✅ Horizontal scroll container with drag-to-scroll */}
            <div
              ref={universalScrollRef}
              className="flex flex-nowrap items-center gap-2.5 cursor-grab overflow-x-auto overflow-y-hidden overscroll-x-contain [-ms-overflow-style:none] [scrollbar-width:none] active:cursor-grabbing [&::-webkit-scrollbar]:hidden"
            >
              {groupedStatuses.universal.map((status) => (
                <Button
                  key={status.id}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-7 flex-shrink-0 px-2.5 text-xs",
                    "border border-warning-200 bg-warning-50 text-warning-700 hover:bg-warning-100",
                    "transition hover:scale-[1.02]",
                    // Pending highlight
                    pendingStatus?.id === status.id && "ring-2 ring-info-500 ring-offset-1 scale-105"
                  )}
                  onClick={() => {
                    if (universalHasDraggedRef.current) {
                      universalHasDraggedRef.current = false;
                      return;
                    }
                    handleStatusClick(status);
                  }}
                  disabled={addConsultation.isPending}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                  ) : (
                    <ColorDot color={status.color_code} size="sm" className="mr-1.5" />
                  )}
                  {status.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* ROW 2: Result Statuses (Kết quả liên hệ) - Sorted by Stage Progression */}
        {(groupedStatuses.previousStage.length > 0 || groupedStatuses.sameStage.length > 0 || groupedStatuses.nextStage.length > 0) && (
          <div className="space-y-2">
            {/* Header with help tooltip */}
            <div className="flex items-center gap-1">
              <BookmarkCheck className="text-muted-foreground h-3 w-3 text-xs" />
              <Label className="text-muted-foreground text-xs">Kết quả liên hệ ({lead?.pipeline_stage?.name})</Label>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HelpCircle className="text-muted-foreground/60 h-3.5 w-3.5 cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-[200px] text-xs">
                    <p>Cuộn chuột hoặc kéo để xem thêm. Click vào trạng thái để lưu ngay.</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>

            {/* Scrollable Container with wheel scroll */}
            <div className="relative">
              {/* Horizontal scroll container - hidden scrollbar, uses wheel scroll */}
              <div
                ref={scrollContainerRef}
                className="flex flex-nowrap items-center gap-2.5 cursor-grab overflow-x-auto overflow-y-hidden overscroll-x-contain [-ms-overflow-style:none] [scrollbar-width:none] active:cursor-grabbing [&::-webkit-scrollbar]:hidden"
              >
                  {/* GROUP 1: PREVIOUS STAGE (Revert) - Color by outcome_type */}
                  {groupedStatuses.previousStage.length > 0 && (
                    <>
                      {groupedStatuses.previousStage.map((status) => (
                        <Button
                          key={status.id}
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-7 flex-shrink-0 px-2.5 text-xs font-normal",
                            // ✅ Use outcome_type-based colors (with slate tint for previous stage)
                            getOutcomeColorClasses(status.outcome_type),
                            "opacity-80", // Slightly dimmed to indicate it's a revert
                            "transition hover:scale-[1.02]",
                            // Pending highlight
                            pendingStatus?.id === status.id && "ring-2 ring-info-500 ring-offset-1 scale-105 opacity-100"
                          )}
                          onClick={() => {
                            if (resultHasDraggedRef.current) {
                              resultHasDraggedRef.current = false;
                              return;
                            }
                            handleStatusClick(status);
                          }}
                          disabled={addConsultation.isPending}
                        >
                          {savingStatusId === status.id ? (
                            <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                          ) : (
                            <span
                              className="mr-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full"
                              style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                            />
                          )}
                          {status.name}
                        </Button>
                      ))}

                      <ArrowRight className="text-muted-foreground/30 mx-1 h-3 w-3 flex-shrink-0" />
                    </>
                  )}

                  {/* GROUP 2: SAME STAGE (Current & Siblings) - Color by outcome_type */}
                  {groupedStatuses.sameStage.length > 0 && (
                    <>
                      {groupedStatuses.sameStage.map((status) => {
                        const isCurrentStatus = status.id === currentStatusId;
                        return (
                          <Button
                            key={status.id}
                            variant="ghost"
                            size="sm"
                            className={cn(
                              "h-7 flex-shrink-0 px-2.5 text-xs font-normal",
                              // ✅ Use outcome_type-based colors
                              getOutcomeColorClasses(status.outcome_type, isCurrentStatus),
                              "transition hover:scale-[1.02]",
                              // Pending highlight
                              pendingStatus?.id === status.id && "ring-2 ring-info-500 ring-offset-1 scale-105"
                            )}
                            onClick={() => {
                              if (resultHasDraggedRef.current) {
                                resultHasDraggedRef.current = false;
                                return;
                              }
                              handleStatusClick(status);
                            }}
                            disabled={addConsultation.isPending}
                          >
                            {savingStatusId === status.id ? (
                              <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                            ) : (
                              <span
                                className="mr-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full"
                                style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                              />
                            )}
                            {status.name}
                          </Button>
                        );
                      })}
                    </>
                  )}

                  {/* ARROW SEPARATOR */}
                  {groupedStatuses.sameStage.length > 0 && groupedStatuses.nextStage.length > 0 && (
                    <ArrowRight className="text-muted-foreground/50 mx-1 h-4 w-4 flex-shrink-0" />
                  )}

                  {/* GROUP 3: NEXT STAGE (Progress) - Color by outcome_type */}
                  {groupedStatuses.nextStage.length > 0 && (
                    <>
                      {groupedStatuses.nextStage.map((status) => (
                        <Button
                          key={status.id}
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-7 flex-shrink-0 px-2.5 text-xs font-normal",
                            // ✅ Use outcome_type-based colors
                            getOutcomeColorClasses(status.outcome_type),
                            "transition hover:scale-[1.02]",
                            // Pending highlight
                            pendingStatus?.id === status.id && "ring-2 ring-info-500 ring-offset-1 scale-105"
                          )}
                          onClick={() => {
                            if (resultHasDraggedRef.current) {
                              resultHasDraggedRef.current = false;
                              return;
                            }
                            handleStatusClick(status);
                          }}
                          disabled={addConsultation.isPending}
                        >
                          {savingStatusId === status.id ? (
                            <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                          ) : (
                            <span
                              className="mr-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full"
                              style={{ backgroundColor: sanitizeColorCode(status.color_code) }}
                            />
                          )}
                          {status.name}
                        </Button>
                      ))}
                    </>
                  )}
                </div>
              </div>

              {/* Dynamic Gradient Progress Bar */}
              {(() => {
                 // Calculate colors for gradient
                 // Fallbacks: Slate-200 (Gray), Primary (Blue/Brand), Emerald-200 (Green)
                 const prevColor = groupedStatuses.previousStage.length > 0
                    ? sanitizeColorCode(groupedStatuses.previousStage[groupedStatuses.previousStage.length - 1].color_code, "#e2e8f0")
                    : "#e2e8f0";

                 const currColor = sanitizeColorCode(
                    groupedStatuses.sameStage.find(s => s.id === currentStatusId)?.color_code
                    || groupedStatuses.sameStage[0]?.color_code,
                    "#3b82f6"
                 );

                 const nextColor = groupedStatuses.nextStage.length > 0
                    ? sanitizeColorCode(groupedStatuses.nextStage[0].color_code, "#a7f3d0")
                    : "#a7f3d0";

                 return (
                   <div 
                     className="mt-2 h-1 rounded-full opacity-80"
                     style={{
                       background: `linear-gradient(to right, ${prevColor}, ${currColor}, ${nextColor})`
                     }}
                   />
                 );
              })()}

              {/* Loss Reason Selection (shown for negative final statuses) */}
              {pendingStatus && requiresLossReason(pendingStatus) && (
                <div className="mt-3">
                  <LossReasonQuickSelect
                    value={lossReasonCode}
                    onChange={handleLossReasonSelect}
                    note={lossReasonNote}
                    onNoteChange={setLossReasonNote}
                    required
                  />
                </div>
              )}

              {/* ✅ INLINE DELAYED COMMIT CONFIRMATION BAR */}
              {pendingStatus && (lossReasonCode || !requiresLossReason(pendingStatus)) && (
                <div className="mt-3 overflow-hidden rounded-lg border border-info-200 bg-info-50">
                  {/* Progress bar (shrinks from right to left) */}
                  <div
                    className="h-1 bg-info-500 transition-[width] duration-1000 ease-linear"
                    style={{ width: `${(countdown / 3) * 100}%` }}
                  />

                  {/* Content */}
                  <div className="flex items-center justify-between gap-2 px-3 py-2">
                    {/* Left: Status info */}
                    <div className="flex items-center gap-2 min-w-0">
                      <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-info-600" />
                      <span className="text-sm text-info-700 truncate">
                        Sẽ lưu: <strong>{pendingStatus.name}</strong>
                      </span>
                    </div>

                    {/* Right: Actions + Timer */}
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {/* Undo button */}
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted"
                        onClick={cancelPending}
                      >
                        Hoàn tác
                      </Button>

                      {/* Save now button with keyboard hint */}
                      <Button
                        type="button"
                        variant="default"
                        size="sm"
                        className="h-7 px-3 text-xs bg-info-600 hover:bg-info-700"
                        onClick={() => commitSave(pendingStatus)}
                        disabled={addConsultation.isPending}
                        title="Ctrl+Enter để lưu nhanh"
                      >
                        {addConsultation.isPending ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <>
                            Lưu ngay
                            <kbd className="ml-1.5 hidden sm:inline-flex items-center px-1 py-0.5 text-[9px] font-mono bg-info-700 rounded">
                              ⌘↵
                            </kbd>
                          </>
                        )}
                      </Button>

                      {/* Countdown timer */}
                      <span className="text-xs font-medium text-info-600 w-4 text-center">
                        {countdown}s
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>

        )}

      </div>
    </div>
  );
}

export default QuickConsultationSection;
