// src/components/leads/QuickConsultationSection.tsx
"use client";

import React, { useState, useMemo } from "react";
import { format, addMinutes, addHours, addDays, set } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Loader2,
  PhoneOff,
  ThumbsUp,
  XCircle,
  Clock,
  CalendarClock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { DateTimePicker } from "@/components/common/form";
import { cn } from "@/lib/utils";
import { useAllowedNextStatuses } from "@/hooks/usePipeline";
import { useAddConsultation, useLead } from "@/hooks/useLeads";
import type { ConsultationStatus, ConsultationCreate } from "@/types/lead.types";

interface QuickConsultationSectionProps {
  leadId: number;
  onSuccess?: () => void;
}

// Schedule option type
type ScheduleOption = "none" | "30m" | "1h" | "tomorrow" | "custom";

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

export function QuickConsultationSection({ leadId, onSuccess }: QuickConsultationSectionProps) {
  // Get lead data to determine current consultation status
  const { data: lead } = useLead(leadId);
  const currentStatusId = lead?.consultation_status_id;

  // Get allowed next statuses based on state machine
  const { data: statuses = [], isLoading: statusesLoading, error, isError } = useAllowedNextStatuses(currentStatusId);
  const addConsultation = useAddConsultation();

  // Form state
  const [notes, setNotes] = useState("");
  const [scheduleOption, setScheduleOption] = useState<ScheduleOption>("none");
  const [customDateTime, setCustomDateTime] = useState<Date | undefined>(undefined);
  const [savingStatusId, setSavingStatusId] = useState<string | null>(null);
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);

  // Group statuses by outcome_type and universal flag
  const groupedStatuses = useMemo(() => {
    const universal: ConsultationStatus[] = []; // ✅ NEW - Universal/retry statuses
    const neutral: ConsultationStatus[] = [];
    const positive: ConsultationStatus[] = [];
    const negative: ConsultationStatus[] = [];

    statuses.forEach((status) => {
      // ✅ NEW: Universal statuses in separate group
      if (status.is_universal) {
        universal.push(status);
      } else {
        // Existing grouping logic for non-universal statuses
        switch (status.outcome_type) {
          case "neutral":
            neutral.push(status);
            break;
          case "positive":
            positive.push(status);
            break;
          case "negative":
            negative.push(status);
            break;
          default:
            neutral.push(status);
        }
      }
    });

    return { universal, neutral, positive, negative };
  }, [statuses]);

  // Handle status badge click - save immediately
  const handleStatusClick = async (status: ConsultationStatus) => {
    // Determine scheduled_at based on option
    let scheduledAt: string | null = null;

    if (scheduleOption === "custom" && customDateTime) {
      // DateTimePicker already includes time in customDateTime
      scheduledAt = customDateTime.toISOString();
    } else {
      scheduledAt = getScheduledDateTime(scheduleOption);
    }

    const payload: ConsultationCreate = {
      status_id: status.id,
      method: "phone",
      notes: notes.trim() || `Ghi nhận: ${status.name}`,
      scheduled_at: scheduledAt,
    };

    try {
      setSavingStatusId(status.id);
      await addConsultation.mutateAsync({ leadId, data: payload });

      // Reset form on success
      setNotes("");
      setScheduleOption("none");
      setCustomDateTime(undefined);

      onSuccess?.();
    } catch {
      // Error is handled by the mutation
    } finally {
      setSavingStatusId(null);
    }
  };

  // Loading state
  if (statusesLoading) {
    return (
      <div className="flex items-center justify-center p-4">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="p-4 text-sm text-red-600 bg-red-50 rounded-md">
        <p className="font-medium">Không thể tải trạng thái</p>
        <p className="text-xs mt-1">{error?.message || "Lỗi không xác định"}</p>
      </div>
    );
  }

  // Empty state
  if (statuses.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground bg-muted/50 rounded-md">
        <p>Không có trạng thái nào được cấu hình.</p>
        <p className="text-xs mt-1">Vui lòng liên hệ Admin để thiết lập.</p>
      </div>
    );
  }

  const scheduleOptions: { value: ScheduleOption; label: string; icon?: React.ReactNode }[] = [
    { value: "none", label: "Không" },
    { value: "30m", label: "30p" },
    { value: "1h", label: "1h" },
    { value: "tomorrow", label: "Ngày mai" },
    { value: "custom", label: "Tùy chọn", icon: <CalendarClock className="h-3 w-3" /> },
  ];

  return (
    <div className="space-y-3">
      {/* Notes Input - Always visible */}
      <div className="space-y-1.5">
        <Label htmlFor="quick-notes" className="text-xs text-muted-foreground">
          Ghi chú nhanh (tùy chọn)
        </Label>
        <Textarea
          id="quick-notes"
          placeholder="VD: KH hẹn gọi lại lúc 3h chiều..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="text-sm resize-none"
        />
      </div>

      {/* Schedule Section */}
      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Clock className="h-3 w-3" />
          Hẹn gọi lại
        </Label>
        <div className="flex flex-wrap gap-1.5">
          {scheduleOptions.map((option) => (
            <Button
              key={option.value}
              type="button"
              variant={scheduleOption === option.value ? "default" : "outline"}
              size="sm"
              className={cn(
                "h-7 text-xs px-2.5",
                scheduleOption === option.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-background hover:bg-muted"
              )}
              onClick={() => {
                setScheduleOption(option.value);
                // Tự động mở DateTimePicker khi chọn "Tùy chọn"
                if (option.value === "custom") {
                  setIsDatePickerOpen(true);
                }
              }}
            >
              {option.icon && <span className="mr-1">{option.icon}</span>}
              {option.label}
            </Button>
          ))}
        </div>

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

        {/* Schedule Preview */}
        {scheduleOption !== "none" && (
          <div className="text-xs text-muted-foreground flex items-center gap-1.5 pt-1">
            <CalendarClock className="h-3 w-3 text-blue-500" />
            <span>
              {scheduleOption === "custom" && customDateTime
                ? `Hẹn: ${format(customDateTime, "HH:mm dd/MM", { locale: vi })}`
                : scheduleOption === "30m"
                  ? `Hẹn: ${format(addMinutes(new Date(), 30), "HH:mm", { locale: vi })}`
                  : scheduleOption === "1h"
                    ? `Hẹn: ${format(addHours(new Date(), 1), "HH:mm", { locale: vi })}`
                    : scheduleOption === "tomorrow"
                      ? `Hẹn: 09:00 ngày mai`
                      : ""}
            </span>
          </div>
        )}
      </div>

      {/* Divider */}
      <div className="border-t pt-3">
        <Label className="text-xs text-muted-foreground mb-3 block">
          Chọn kết quả tư vấn (click để lưu)
        </Label>

        {/* ✅ NEW: Universal Statuses - Retry/Transient (không thay đổi trạng thái lead) */}
        {groupedStatuses.universal.length > 0 && (
          <div className="space-y-2 mb-4 pb-4 border-b">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <PhoneOff className="h-3.5 w-3.5" />
              <span className="font-medium">Kết quả cuộc gọi</span>
              <span className="text-[10px] ml-auto text-amber-600 font-medium">
                (không thay đổi trạng thái)
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {groupedStatuses.universal.map((status) => (
                <Button
                  key={status.id}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-7 text-xs px-2.5",
                    "bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200",
                    "transition-all hover:scale-[1.02]"
                  )}
                  onClick={() => handleStatusClick(status)}
                  disabled={addConsultation.isPending}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                  ) : (
                    <span
                      className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                      style={{ backgroundColor: status.color_code }}
                    />
                  )}
                  {status.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* Neutral Group - Retry/Callback */}
        {groupedStatuses.neutral.length > 0 && (
          <div className="space-y-2 mb-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <PhoneOff className="h-3.5 w-3.5" />
              <span className="font-medium">Kết nối thất bại / Gọi lại</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {groupedStatuses.neutral.map((status) => (
                <Button
                  key={status.id}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-7 text-xs px-2.5",
                    "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200",
                    "transition-all hover:scale-[1.02]"
                  )}
                  onClick={() => handleStatusClick(status)}
                  disabled={addConsultation.isPending}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                  ) : (
                    <span
                      className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                      style={{ backgroundColor: status.color_code }}
                    />
                  )}
                  {status.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* Positive Group - Progress/Success */}
        {groupedStatuses.positive.length > 0 && (
          <div className="space-y-2 mb-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ThumbsUp className="h-3.5 w-3.5" />
              <span className="font-medium">Tích cực / Tiến triển</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {groupedStatuses.positive.map((status) => (
                <Button
                  key={status.id}
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-7 text-xs px-2.5",
                    "bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200",
                    "font-medium transition-all hover:scale-[1.02]"
                  )}
                  onClick={() => handleStatusClick(status)}
                  disabled={addConsultation.isPending}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                  ) : (
                    <span
                      className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                      style={{ backgroundColor: status.color_code }}
                    />
                  )}
                  {status.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* Negative Group - Stop/Remove */}
        {groupedStatuses.negative.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <XCircle className="h-3.5 w-3.5" />
              <span className="font-medium">Dừng / Loại bỏ</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {groupedStatuses.negative.map((status) => (
                <Button
                  key={status.id}
                  variant="ghost"
                  size="sm"
                  className={cn(
                    "h-7 text-xs px-2.5",
                    "bg-red-50 hover:bg-red-100 text-red-600 border border-red-200",
                    "transition-all hover:scale-[1.02]"
                  )}
                  onClick={() => handleStatusClick(status)}
                  disabled={addConsultation.isPending}
                >
                  {savingStatusId === status.id ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                  ) : (
                    <span
                      className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                      style={{ backgroundColor: status.color_code }}
                    />
                  )}
                  {status.name}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default QuickConsultationSection;
