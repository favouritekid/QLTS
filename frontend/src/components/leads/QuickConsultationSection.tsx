// src/components/leads/QuickConsultationSection.tsx
"use client";

import React, { useState, useMemo, useRef, useEffect } from "react";
import { format, addMinutes, addHours, addDays, set } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Loader2,
  PhoneOff,
  Clock,
  CalendarClock,
  ArrowRight,
  HelpCircle,
  PhoneForwarded,
  Trophy,
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
  
  // Ref for horizontal scroll container
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Setup wheel scroll handler with passive: false
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const handleWheel = (e: WheelEvent) => {
      if (e.deltaY !== 0) {
        e.preventDefault();
        scrollContainer.scrollLeft += e.deltaY;
      }
    };

    scrollContainer.addEventListener("wheel", handleWheel, { passive: false });
    
    return () => {
      scrollContainer.removeEventListener("wheel", handleWheel);
    };
  }, [statuses]); // Re-attach when statuses load

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

      {/* Schedule Section with ToggleGroup */}
      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
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
          <ToggleGroupItem value="none" size="sm" className="h-7 text-xs px-2.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            Không
          </ToggleGroupItem>
          <ToggleGroupItem value="30m" size="sm" className="h-7 text-xs px-2.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            30p
          </ToggleGroupItem>
          <ToggleGroupItem value="1h" size="sm" className="h-7 text-xs px-2.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            1h
          </ToggleGroupItem>
          <ToggleGroupItem value="tomorrow" size="sm" className="h-7 text-xs px-2.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            Ngày mai
          </ToggleGroupItem>
          <ToggleGroupItem value="custom" size="sm" className="h-7 text-xs px-2.5 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground">
            <CalendarClock className="h-3 w-3 mr-1" />
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
          <div className="flex items-center gap-2 py-2 px-3 bg-blue-50 rounded-md border border-blue-100">
            <CalendarClock className="h-4 w-4 text-blue-600 flex-shrink-0" />
            <span className="text-sm font-medium text-blue-700">
              {getSchedulePreviewText(scheduleOption, customDateTime)}
            </span>
          </div>
        )}
      </div>

      {/* Divider */}
      <div className="border-t pt-3">
        {/* Universal Statuses - Stay at top (không thay đổi trạng thái lead) */}
        {groupedStatuses.universal.length > 0 && (
          <div className="mb-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
              <PhoneForwarded className="h-3.5 w-3.5 text-amber-600" />
              <span className="font-medium">Kết quả cuộc gọi</span>
              <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1.5 bg-amber-100 text-amber-700">
                không đổi trạng thái
              </Badge>
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

        {/* Horizontal Slider - Status Progression */}
        {(groupedStatuses.negative.length > 0 || groupedStatuses.neutral.length > 0 || groupedStatuses.positive.length > 0) && (
          <div className="space-y-2">
            {/* Header with help tooltip */}
            <div className="flex items-center gap-1">
              <Trophy className="h-3.5 w-3.5 text-amber-600" />
              <Label className="text-xs text-muted-foreground">
                Chọn kết quả
              </Label>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HelpCircle className="h-3.5 w-3.5 text-muted-foreground/60 cursor-help" />
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
                className="overflow-x-auto overflow-y-hidden overscroll-x-contain cursor-grab active:cursor-grabbing [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
              >
                <div className="flex items-center gap-1.5 px-1 min-w-max">
                  {/* Negative Zone */}
                  {groupedStatuses.negative.length > 0 && (
                    <>
                      {groupedStatuses.negative.map((status) => (
                        <Button
                          key={status.id}
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-7 text-xs px-2.5 flex-shrink-0",
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
                      {/* Arrow separator */}
                      {(groupedStatuses.neutral.length > 0 || groupedStatuses.positive.length > 0) && (
                        <ArrowRight className="h-4 w-4 text-muted-foreground/50 flex-shrink-0 mx-1" />
                      )}
                    </>
                  )}

                  {/* Neutral Zone */}
                  {groupedStatuses.neutral.length > 0 && (
                    <>
                      {groupedStatuses.neutral.map((status) => (
                        <Button
                          key={status.id}
                          variant="ghost"
                          size="sm"
                          className={cn(
                            "h-7 text-xs px-2.5 flex-shrink-0",
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
                      {/* Arrow separator */}
                      {groupedStatuses.positive.length > 0 && (
                        <ArrowRight className="h-4 w-4 text-muted-foreground/50 flex-shrink-0 mx-1" />
                      )}
                    </>
                  )}

                  {/* Positive Zone */}
                  {groupedStatuses.positive.length > 0 && (
                    <>
                      {groupedStatuses.positive.map((status) => (
                        <Button
                          key={status.id}
                          variant="outline"
                          size="sm"
                          className={cn(
                            "h-7 text-xs px-2.5 flex-shrink-0",
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
                    </>
                  )}
                </div>
              </div>

              {/* Progress indicator bar */}
              <div className="h-1 rounded-full mt-2 bg-gradient-to-r from-red-200 via-slate-200 to-emerald-200" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default QuickConsultationSection;
