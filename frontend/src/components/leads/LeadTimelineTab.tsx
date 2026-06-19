// src/components/leads/LeadTimelineTab.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Clock,
  User,
  FileText,
  Phone,
  Mail,
  MessageSquare,
  Calendar,
  CalendarClock,
  CalendarX2,
  UserPlus,
  Video,
  Trash2,
  Edit,
  MoreVertical,
  AlertTriangle,
} from "lucide-react";
import { useLeadTimeline, useDeleteConsultation, useUpdateConsultation } from "@/hooks/useLeads";
import { useConsultationStatuses } from "@/hooks/usePipeline";
import { useAuthStore } from "@/lib/stores/auth.store";
import { useClientNow } from "@/hooks/useClientNow";
import { DateTimePicker } from "@/components/common/form";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { format, isToday, isYesterday, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { ConsultationDialog } from "./ConsultationDialog";
import type { Consultation, TimelineItem as TimelineItemBase } from "@/types/lead.types";
import { getLossReasonLabelMap } from "@/lib/loss-reasons";

// Extended timeline type for backward compatibility with old structure
type TimelineItem = TimelineItemBase & {
  data?: Consultation | { method?: string } | Record<string, unknown>;
};

interface LeadTimelineTabProps {
  leadId: number;
  /** Maximum items to show initially. Set 0 or undefined to show all. */
  maxItems?: number;
  /** Compact mode - simpler display without date grouping */
  compact?: boolean;
  /** Limit number of items (alias for maxItems, used in compact mode) */
  limit?: number;
}

// Get icon and color based on event type and method
const getEventConfig = (eventType: string, method?: string) => {
  // Consultation events - differentiate by method
  // Match all consultation-related event types from backend
  if (eventType === "consultation" || eventType === "consultation_added" || eventType === "consultation_updated") {
    switch (method) {
      case "phone":
        return {
          icon: Phone,
          color: "text-success-600",
          bgColor: "bg-success-50",
          ringColor: "ring-success-200",
          label: "Cuộc gọi",
        };
      case "email":
        return {
          icon: Mail,
          color: "text-info-600",
          bgColor: "bg-info-50",
          ringColor: "ring-info-200",
          label: "Email",
        };
      case "video":
      case "video_call":
        return {
          icon: Video,
          color: "text-purple-600",
          bgColor: "bg-purple-50",
          ringColor: "ring-purple-200",
          label: "Video call",
        };
      case "in_person":
        return {
          icon: User,
          color: "text-warning-600",
          bgColor: "bg-warning-50",
          ringColor: "ring-warning-200",
          label: "Gặp trực tiếp",
        };
      case "sms":
        return {
          icon: MessageSquare,
          color: "text-cyan-600",
          bgColor: "bg-cyan-50",
          ringColor: "ring-cyan-200",
          label: "SMS",
        };
      case "system":
        return {
          icon: Clock,
          color: "text-slate-500",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Hệ thống tự đóng",
        };
      default:
        return {
          icon: MessageSquare,
          color: "text-muted-foreground",
          bgColor: "bg-muted",
          ringColor: "ring-border",
          label: "Tư vấn",
        };
    }
  }

  // Assignment events (backend sends "assignment", frontend may use "assigned")
  if (eventType === "assignment" || eventType === "assigned") {
    return {
      icon: UserPlus,
      color: "text-indigo-600",
      bgColor: "bg-indigo-50",
      ringColor: "ring-indigo-200",
      label: "Phân công",
    };
  }

  // Default
  return {
    icon: Clock,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
    ringColor: "ring-border",
    label: "Hoạt động",
  };
};

// Get outcome type styling
const getOutcomeStyles = (outcomeType?: string | null) => {
  switch (outcomeType) {
    case "positive":
      return {
        badgeBg: "bg-success-100",
        badgeText: "text-success-700",
        badgeBorder: "border-success-200",
      };
    case "negative":
      return {
        badgeBg: "bg-error-100",
        badgeText: "text-error-700",
        badgeBorder: "border-error-200",
      };
    case "neutral":
    default:
      return {
        badgeBg: "bg-info-100",
        badgeText: "text-info-700",
        badgeBorder: "border-info-200",
      };
  }
};

// Format date for grouping
const formatDateGroup = (dateString: string) => {
  const date = parseISO(dateString);
  if (isToday(date)) return "Hôm nay";
  if (isYesterday(date)) return "Hôm qua";
  return format(date, "EEEE, dd/MM/yyyy", { locale: vi });
};

// Group timeline by date
const groupTimelineByDate = (timeline: TimelineItem[]) => {
  const groups: Record<string, typeof timeline> = {};

  // Sort by date descending (newest first)
  const sorted = [...timeline].sort((a, b) => {
    const dateA = new Date(a.timestamp || 0);
    const dateB = new Date(b.timestamp || 0);
    return dateB.getTime() - dateA.getTime();
  });

  sorted.forEach((event) => {
    const dateKey = format(
      parseISO(event.timestamp || new Date().toISOString()),
      "yyyy-MM-dd"
    );
    if (!groups[dateKey]) {
      groups[dateKey] = [];
    }
    groups[dateKey].push(event);
  });

  return groups;
};

// Get initials from name
const getInitials = (name: string) => {
  return name
    .split(" ")
    .filter(Boolean)
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export function LeadTimelineTab({ leadId, maxItems, compact, limit }: LeadTimelineTabProps) {
  const { data: timeline, isLoading } = useLeadTimeline(leadId);
  const effectiveLimit = limit ?? maxItems;
  const deleteMutation = useDeleteConsultation();
  const updateMutation = useUpdateConsultation();
  const { user } = useAuthStore();
  const { data: allStatuses = [] } = useConsultationStatuses();
  // Hydration-safe client time (null khi SSR) — gate hiển thị action theo "hẹn tương lai".
  const now = useClientNow();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedConsultationId, setSelectedConsultationId] = useState<number | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingConsultation, setEditingConsultation] = useState<Consultation | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [reschedulingConsultation, setReschedulingConsultation] = useState<Consultation | null>(null);
  const [rescheduleDate, setRescheduleDate] = useState<Date | undefined>(undefined);

  if (isLoading || !timeline) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (timeline.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground bg-muted/50 rounded-lg border border-dashed">
        <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-20" />
        <p className="font-medium">Chưa có hoạt động nào</p>
        <p className="text-xs mt-1">Lịch sử tương tác sẽ xuất hiện tại đây</p>
      </div>
    );
  }

  // Compact mode - simpler display for right panel
  if (compact) {
    const compactItems = effectiveLimit ? timeline.slice(0, effectiveLimit) : timeline;

    return (
      <div className="space-y-2">
        {compactItems.map((event, index) => {
          const eventType = event.type || "lead_created";
          const eventData = event.data || {};
          const isConsultation = eventType === "consultation" || eventType === "consultation_added";
          const isAssignment = eventType === "assignment" || eventType === "assigned";
          const config = getEventConfig(
            eventType,
            isConsultation ? (eventData as { method?: string }).method : undefined
          );
          const Icon = config.icon;

          const consultData = isConsultation ? (eventData as Consultation) : null;
          const assignData = isAssignment ? (eventData as { officer?: { full_name?: string }; reason?: string }) : null;
          const statusName = consultData?.consultation_status?.name || event.description || "Hoạt động";
          const statusColor = consultData?.consultation_status?.color_code;
          const outcomeType = consultData?.consultation_status?.outcome_type;
          const outcomeStyles = getOutcomeStyles(outcomeType);
          const notes = consultData?.notes || "";
          const actorName = consultData?.officer?.full_name || assignData?.officer?.full_name || "";
          const scheduledAt = consultData?.scheduled_at;
          const lossReasonCode = consultData?.loss_reason_code;
          const lossReasonNote = consultData?.loss_reason_note;

          const compactDataId = isConsultation
            ? (eventData as { id?: number })?.id
            : isAssignment
              ? (eventData as { id?: number })?.id
              : undefined;
          const compactKey = `${event.type}-${event.timestamp}-${compactDataId ?? index}`;

          const lossReasonLabels = getLossReasonLabelMap();
          const lossLabel = lossReasonCode
            ? (lossReasonCode === "OTHER"
              ? (lossReasonNote || "Lý do khác")
              : lossReasonLabels[lossReasonCode] || lossReasonCode)
            : null;

          const hasNotes = notes && !notes.startsWith("Ghi nhận:") && !notes.startsWith("Ghi nhận nhanh:");

          return (
            <div
              key={compactKey}
              className="flex items-start gap-3 p-3 bg-muted hover:bg-muted/80 rounded-xl transition-colors"
            >
              {/* Icon — method indicator */}
              <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0", config.bgColor)}>
                <Icon className={cn("w-4 h-4", config.color)} />
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                {/* Header: Status badge + timestamp */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    {isConsultation && statusColor ? (
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-xs font-medium px-2 py-0.5 border",
                          outcomeStyles.badgeBg,
                          outcomeStyles.badgeText,
                          outcomeStyles.badgeBorder
                        )}
                      >
                        <span
                          className="w-1.5 h-1.5 rounded-full mr-1.5 flex-shrink-0"
                          style={{ backgroundColor: sanitizeColorCode(statusColor) }}
                        />
                        {statusName}
                      </Badge>
                    ) : (
                      <span className="text-sm font-medium text-foreground truncate">{statusName}</span>
                    )}
                  </div>

                  <span className="text-xs text-muted-foreground flex-shrink-0" suppressHydrationWarning>
                    {format(parseISO(event.timestamp || ""), "dd/MM HH:mm")}
                  </span>
                </div>

                {/* Notes */}
                {hasNotes && (
                  <p className="text-xs text-muted-foreground mt-1 italic line-clamp-2">
                    &quot;{notes}&quot;
                  </p>
                )}

                {/* Loss reason */}
                {lossLabel && (
                  <div className="flex items-center gap-1.5 mt-1 text-xs text-amber-600">
                    <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                    <span>Lý do: {lossLabel}</span>
                  </div>
                )}

                {/* Footer: Schedule (left) + Officer (right) */}
                <div className="flex items-center justify-between gap-2 mt-1 text-xs text-muted-foreground">
                  <div>
                    {scheduledAt && (
                      <span className="text-info-600 flex items-center gap-1" suppressHydrationWarning>
                        <Calendar className="w-3 h-3" />
                        Hẹn {format(parseISO(scheduledAt), "dd/MM HH:mm")}
                      </span>
                    )}
                  </div>
                  {actorName && (
                    <span className="flex items-center gap-1">
                      <User className="w-3 h-3" />
                      {actorName}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Show more indicator if there are more items */}
        {effectiveLimit && timeline.length > effectiveLimit && (
          <div className="text-center pt-1">
            <span className="text-xs text-muted-foreground">
              +{timeline.length - effectiveLimit} hoạt động khác
            </span>
          </div>
        )}
      </div>
    );
  }

  const groupedTimeline = groupTimelineByDate(timeline);
  const dateKeys = Object.keys(groupedTimeline).sort().reverse();

  // Calculate items to show based on maxItems prop
  const hasLimit = maxItems && maxItems > 0 && !showAll;
  const totalItems = timeline.length;
  const remainingItems = hasLimit ? Math.max(0, totalItems - maxItems) : 0;
  
  // Limit items if maxItems is set and showAll is false
  const itemsToShow = hasLimit ? maxItems : totalItems;
  let itemCount = 0;

  // Quyền thao tác lịch hẹn: officer chỉ sửa được consultation MỚI NHẤT (khớp
  // BE leads.py:1091 → tránh bấm rồi ăn 403); manager/admin sửa bất kỳ.
  const userRole = user?.role;
  const isPrivilegedActor = userRole === "admin" || userRole === "manager";
  // Status "Đã hủy lịch hẹn" (sts19) — không hardcode, lấy động từ catalog.
  const cancelStatusId = allStatuses.find(
    (s) => s.id === "sts19" || s.name === "Đã hủy lịch hẹn",
  )?.id;
  // Consultation mới nhất của lead (theo consultation_date) — để gate officer.
  const latestConsultationId = (() => {
    let best: { id: number; t: number } | null = null;
    for (const ev of timeline as TimelineItem[]) {
      const et = ev.type || "";
      const d = ev.data as Consultation | undefined;
      const isConsult =
        et === "consultation" || et === "consultation_added" || et === "consultation_updated";
      if (isConsult && d?.id && d?.consultation_date) {
        const ms = new Date(d.consultation_date).getTime();
        if (!best || ms > best.t) best = { id: d.id, t: ms };
      }
    }
    return best?.id ?? null;
  })();

  const handleEditConsultation = (consultation: Consultation) => {
    setEditingConsultation(consultation);
    setEditDialogOpen(true);
  };

  const handleDeleteConsultation = (consultationId: number) => {
    setSelectedConsultationId(consultationId);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = () => {
    if (selectedConsultationId) {
      deleteMutation.mutate(
        { leadId, consultationId: selectedConsultationId },
        {
          onSuccess: () => {
            setDeleteDialogOpen(false);
            setSelectedConsultationId(null);
          },
        }
      );
    }
  };

  const openReschedule = (consultation: Consultation) => {
    setReschedulingConsultation(consultation);
    setRescheduleDate(
      consultation.scheduled_at ? new Date(consultation.scheduled_at) : undefined,
    );
  };

  const confirmReschedule = () => {
    if (reschedulingConsultation?.id && rescheduleDate) {
      updateMutation.mutate(
        {
          leadId,
          consultationId: reschedulingConsultation.id,
          data: { scheduled_at: rescheduleDate.toISOString() },
        },
        {
          onSuccess: () => {
            setReschedulingConsultation(null);
            setRescheduleDate(undefined);
          },
        },
      );
    }
  };

  // "Hủy lịch hẹn": đổi status → sts19 + xóa giờ hẹn. AN TOÀN nhờ BE guard
  // updates_pipeline (universal KHÔNG null stage lead). Sửa in-place đúng cái
  // hẹn → hết "sống" → hết nhắc phụ huynh; ghi nhận vẫn giữ trong lịch sử.
  const openCancelAppointment = (consultationId: number) => {
    setSelectedConsultationId(consultationId);
    setCancelDialogOpen(true);
  };

  const confirmCancelAppointment = () => {
    if (selectedConsultationId && cancelStatusId) {
      updateMutation.mutate(
        {
          leadId,
          consultationId: selectedConsultationId,
          data: { status_id: cancelStatusId, scheduled_at: null },
        },
        {
          onSuccess: () => {
            setCancelDialogOpen(false);
            setSelectedConsultationId(null);
          },
        },
      );
    }
  };

  return (
    <>
      <div className="space-y-8">
        {dateKeys.map((dateKey) => {
          // Get items for this date
          const dateItems = groupedTimeline[dateKey];
          
          // Filter items based on limit
          const visibleItems = dateItems.filter(() => {
            if (!hasLimit) return true;
            if (itemCount >= itemsToShow) return false;
            itemCount++;
            return true;
          });

          // Skip entire date group if no visible items
          if (visibleItems.length === 0) return null;

          return (
          <div key={dateKey}>
            {/* Date Header */}
            <div className="flex items-center gap-3 mb-4">
              <Calendar className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold text-foreground">
                {formatDateGroup(dateKey + "T00:00:00")}
              </span>
              <div className="flex-1 h-px bg-border" />
            </div>

            {/* Events for this date - with connecting line */}
            <div className="relative pl-6 space-y-6">
              {/* Connecting line */}
              <div className="absolute left-[15px] top-3 bottom-3 w-0.5 bg-gradient-to-b from-border via-border to-transparent" />

              {visibleItems.map((event, index) => {
                const eventType = event.type || "lead_created";
                // ✅ TECHNICAL DEBT FIX: Use typed event data instead of `as any`
                const eventData = event.data || {};

                // ✅ FIX: Match actual backend event types ("consultation", "assignment")
                // Backend sends: type: "consultation" | "assignment"
                // NOT "consultation_added", "consultation_updated", or "assigned"
                const isConsultation = eventType === "consultation" || eventType === "consultation_added" || eventType === "consultation_updated";
                const isAssignment = eventType === "assignment" || eventType === "assigned";

                const config = getEventConfig(
                  eventType,
                  isConsultation ? (eventData.method as string) : undefined
                );
                const Icon = config.icon;

                // Generate title and subtitle
                let title = "";
                let subtitle = "";
                let actorName = "";

                // Type assertion for consultation data (used in JSX below)
                const consultData = isConsultation ? (eventData as Consultation) : null;
                const statusColor = consultData?.consultation_status?.color_code;
                const outcomeType = consultData?.consultation_status?.outcome_type;
                const outcomeStyles = getOutcomeStyles(outcomeType);

                if (isConsultation && consultData) {
                  const statusName = consultData.consultation_status?.name || "Tư vấn";
                  title = statusName;

                  // Only show notes if it's not the auto-generated pattern
                  const notes = consultData.notes || "";
                  const autoPatterns = [
                    `Ghi nhận nhanh: ${statusName}`,
                    `Ghi nhận: ${statusName}`,
                  ];
                  if (notes && !autoPatterns.includes(notes)) {
                    subtitle = notes;
                  }

                  actorName = consultData.officer?.full_name || "";
                } else if (isAssignment) {
                  // Type assertion for assignment data
                  const assignData = eventData as { reason?: string; officer?: { full_name?: string } };
                  title = "Phân công lead";
                  subtitle = assignData.reason || "";
                  actorName = assignData.officer?.full_name || "";
                } else {
                  // Fallback for other event types (lead_created, pipeline_moved, etc.)
                  title = event.description || config.label;
                  actorName = event.actor?.full_name || "";
                }

                const consultId = isConsultation ? (eventData as { id?: number })?.id : undefined;
                const assignId = isAssignment ? (eventData as { id?: number })?.id : undefined;
                const itemId = consultId ?? assignId;
                const itemKey = `${event.type}-${event.timestamp}-${itemId ?? index}`;

                return (
                  <div key={itemKey} className="relative flex gap-3 group">
                    {/* Timeline Dot (Icon) - smaller and neutral */}
                    <div
                      className={cn(
                        "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 border-white shadow-sm transition-shadow ring-1",
                        config.bgColor,
                        config.ringColor
                      )}
                    >
                      <Icon className={cn("h-3.5 w-3.5", config.color)} />
                    </div>

                    {/* Content Block */}
                    <div className="flex-1 bg-card rounded-lg border shadow-sm transition-shadow hover:shadow-md hover:border-primary/30">
                      <div className="p-4">
                        {/* Header: Title, Actor, Time, Actions */}
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div className="flex-1 min-w-0">
                            {/* Title with status color and method badge */}
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              {isConsultation && statusColor ? (
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    "text-xs font-semibold px-2 py-0.5 border",
                                    outcomeStyles.badgeBg,
                                    outcomeStyles.badgeText,
                                    outcomeStyles.badgeBorder
                                  )}
                                >
                                  <span
                                    className="w-2 h-2 rounded-full mr-1.5 flex-shrink-0"
                                    style={{ backgroundColor: sanitizeColorCode(statusColor) }}
                                  />
                                  {title}
                                </Badge>
                              ) : (
                                <h4 className="font-semibold text-sm text-foreground">
                                  {title}
                                </h4>
                              )}
                              {isConsultation && consultData?.method && (
                                <Badge
                                  variant="secondary"
                                  className={cn(
                                    "text-[10px] px-1.5 py-0 font-normal",
                                    config.bgColor,
                                    config.color
                                  )}
                                >
                                  <Icon className="w-2.5 h-2.5 mr-1" />
                                  {config.label}
                                </Badge>
                              )}
                            </div>

                            {/* Actor and time */}
                            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                              {actorName && (
                                <>
                                  <Avatar className="h-4 w-4">
                                    <AvatarFallback className="text-[8px] bg-primary/10">
                                      {getInitials(actorName)}
                                    </AvatarFallback>
                                  </Avatar>
                                  <span className="font-medium">{actorName}</span>
                                  <span>•</span>
                                </>
                              )}
                              <time suppressHydrationWarning>
                                {format(parseISO(event.timestamp || ""), "HH:mm")}
                              </time>
                            </div>
                          </div>

                          {/* Actions Menu */}
                          {isConsultation && consultData?.id && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-11 w-11 sm:h-7 sm:w-7 p-0 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity"
                                >
                                  <MoreVertical className="h-4 w-4 text-muted-foreground" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                {(() => {
                                  // Chỉ hiện khi: hẹn ở TƯƠNG LAI (client-time, tránh
                                  // hydration) + có quyền (privileged, hoặc officer trên
                                  // consultation MỚI NHẤT — khớp BE, tránh 403).
                                  const schedMs = consultData?.scheduled_at
                                    ? new Date(consultData.scheduled_at).getTime()
                                    : null;
                                  const isFutureAppt =
                                    now !== null && schedMs !== null && schedMs > now;
                                  const canActOnAppt =
                                    isPrivilegedActor ||
                                    consultData?.id === latestConsultationId;
                                  if (!isFutureAppt || !canActOnAppt || !consultData?.id) {
                                    return null;
                                  }
                                  const cid = consultData.id;
                                  return (
                                    <>
                                      <DropdownMenuItem onClick={() => openReschedule(consultData)}>
                                        <CalendarClock className="h-4 w-4 mr-2" />
                                        Dời lịch
                                      </DropdownMenuItem>
                                      <DropdownMenuItem onClick={() => openCancelAppointment(cid)}>
                                        <CalendarX2 className="h-4 w-4 mr-2" />
                                        Hủy lịch hẹn
                                      </DropdownMenuItem>
                                      <DropdownMenuSeparator />
                                    </>
                                  );
                                })()}
                                <DropdownMenuItem
                                  onClick={() => handleEditConsultation(consultData)}
                                >
                                  <Edit className="h-4 w-4 mr-2" />
                                  Sửa
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  className="text-destructive focus:text-destructive"
                                  onClick={() => handleDeleteConsultation(consultData.id)}
                                >
                                  <Trash2 className="h-4 w-4 mr-2" />
                                  Xóa
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>

                        {/* Body: Description/Notes - only if not redundant */}
                        {subtitle && (
                          <div className="text-sm text-muted-foreground leading-relaxed mb-3">
                            <div className="flex items-start gap-2">
                              <FileText className="h-3.5 w-3.5 shrink-0 mt-0.5 opacity-40" />
                              <p className="flex-1">{subtitle}</p>
                            </div>
                          </div>
                        )}

                        {/* Footer: Metadata badges */}
                        {(isConsultation || isAssignment) && (
                          <div className="flex flex-wrap gap-2">
                            {/* Consultation: Outcome indicator */}
                            {isConsultation && outcomeType && (
                              <Badge
                                variant="outline"
                                className={cn(
                                  "text-xs font-normal gap-1",
                                  outcomeType === "positive" && "border-success-200 bg-success-50 text-success-700",
                                  outcomeType === "negative" && "border-error-200 bg-error-50 text-error-700",
                                  outcomeType === "neutral" && "border-border bg-muted text-muted-foreground"
                                )}
                              >
                                {outcomeType === "positive" && "✓ Tích cực"}
                                {outcomeType === "negative" && "✗ Tiêu cực"}
                                {outcomeType === "neutral" && "○ Trung lập"}
                              </Badge>
                            )}

                            {/* Consultation: Scheduled follow-up */}
                            {isConsultation && consultData?.scheduled_at && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal gap-1 border-info-200 bg-info-50 text-info-700"
                              >
                                <Calendar className="h-3 w-3" />
                                <span suppressHydrationWarning>Hẹn: {format(parseISO(consultData.scheduled_at), "dd/MM HH:mm")}</span>
                              </Badge>
                            )}

                            {/* Consultation: Loss reason */}
                            {isConsultation && consultData?.loss_reason_code && (() => {
                              const labels = getLossReasonLabelMap();
                              const label = consultData.loss_reason_code === "OTHER"
                                ? (consultData.loss_reason_note || "Lý do khác")
                                : labels[consultData.loss_reason_code] || consultData.loss_reason_code;
                              return (
                                <Badge
                                  variant="outline"
                                  className="text-xs font-normal gap-1 border-amber-200 bg-amber-50 text-amber-700"
                                >
                                  <AlertTriangle className="h-3 w-3" />
                                  Lý do: {label}
                                </Badge>
                              );
                            })()}

                            {/* Consultation: Duration */}
                            {isConsultation && consultData?.duration_minutes && consultData.duration_minutes > 0 && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal gap-1 border-border bg-muted text-muted-foreground"
                              >
                                <Clock className="h-3 w-3" />
                                {consultData.duration_minutes} phút
                              </Badge>
                            )}

                            {/* Assignment: Method (automatic, officer_reassign, manual) */}
                            {isAssignment && (eventData as { method?: string }).method && (
                              <Badge
                                variant="outline"
                                className={cn(
                                  "text-xs font-normal gap-1",
                                  (eventData as { method?: string }).method === "automatic" && "border-purple-200 bg-purple-50 text-purple-700",
                                  (eventData as { method?: string }).method === "officer_reassign" && "border-info-200 bg-info-50 text-info-700",
                                  (eventData as { method?: string }).method === "manual" && "border-orange-200 bg-orange-50 text-orange-700"
                                )}
                              >
                                {(eventData as { method?: string }).method === "automatic" && "Tự động"}
                                {(eventData as { method?: string }).method === "officer_reassign" && "Yêu cầu phân công lại"}
                                {(eventData as { method?: string }).method === "manual" && "Thủ công"}
                              </Badge>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          );
        })}
      </div>

      {/* Load more button */}
      {remainingItems > 0 && (
        <div className="mt-4 text-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAll(true)}
            className="text-muted-foreground hover:text-foreground"
          >
            Tải thêm ({remainingItems} mục)
          </Button>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa ghi nhận tư vấn?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này không thể hoàn tác. Ghi nhận tư vấn sẽ bị xóa vĩnh viễn khỏi timeline.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-error-600 hover:bg-error-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Cancel Appointment Confirmation */}
      <AlertDialog open={cancelDialogOpen} onOpenChange={setCancelDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Hủy lịch hẹn này?</AlertDialogTitle>
            <AlertDialogDescription>
              Lịch hẹn sẽ được đánh dấu &quot;Đã hủy lịch hẹn&quot; và gỡ giờ hẹn —
              KHÔNG gửi nhắc tới phụ huynh nữa. Ghi nhận tư vấn vẫn giữ trong lịch sử.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Không</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmCancelAppointment}
              disabled={!cancelStatusId}
              className="bg-error-600 hover:bg-error-700"
            >
              Hủy lịch hẹn
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reschedule Appointment (gọn — chỉ chọn giờ mới, không mở full form) */}
      <Dialog
        open={Boolean(reschedulingConsultation)}
        onOpenChange={(o) => {
          if (!o) {
            setReschedulingConsultation(null);
            setRescheduleDate(undefined);
          }
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Dời lịch hẹn</DialogTitle>
            <DialogDescription>Chọn giờ hẹn mới cho lịch hẹn này.</DialogDescription>
          </DialogHeader>
          <div className="py-2">
            <DateTimePicker
              value={rescheduleDate ?? null}
              onChange={(d) => setRescheduleDate(d)}
              minDate={now !== null ? new Date(now) : undefined}
              placeholder="Chọn giờ hẹn mới"
              clearable={false}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setReschedulingConsultation(null);
                setRescheduleDate(undefined);
              }}
            >
              Hủy
            </Button>
            <Button onClick={confirmReschedule} disabled={!rescheduleDate}>
              Lưu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Consultation Dialog */}
      <ConsultationDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        leadId={leadId}
        consultation={editingConsultation}
        mode="edit"
      />
    </>
  );
}
