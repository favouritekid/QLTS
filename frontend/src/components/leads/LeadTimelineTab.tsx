// src/components/leads/LeadTimelineTab.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Clock,
  User,
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

// Get outcome type styling (compact mode)
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

// ── "Đường mạch kết quả" (outcome spine) theme — full mode ────────────────────
// The vertical spine + node encode the OUTCOME of each touch, so an officer reads
// the relationship's trajectory in one glance. Restraint: only positive/negative
// carry saturated color; neutral stays quiet so the eye catches the turning points.
// All tokens are theme-aware (dark variants + /alpha) — no hardcoded white.
const getOutcomeSpine = (outcomeType?: string | null) => {
  switch (outcomeType) {
    case "positive":
      return {
        seg: "bg-success-500/70",
        node: "bg-success-500/10 dark:bg-success-500/15",
        icon: "text-success-600 dark:text-success-400",
        tag: "bg-success-500/10 text-success-700 dark:text-success-300",
        tagLabel: "Tích cực",
        emphasize: true,
      };
    case "negative":
      return {
        seg: "bg-error-500/70",
        node: "bg-error-500/10 dark:bg-error-500/15",
        icon: "text-error-600 dark:text-error-400",
        tag: "bg-error-500/10 text-error-700 dark:text-error-300",
        tagLabel: "Tiêu cực",
        emphasize: true,
      };
    default:
      // neutral / null / assignment → quiet
      return {
        seg: "bg-border",
        node: "bg-muted",
        icon: "text-muted-foreground",
        tag: "",
        tagLabel: "",
        emphasize: false,
      };
  }
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

  // ── Full mode — "Đường mạch kết quả" ────────────────────────────────────────
  // Flatten to a single outcome-ordered rail (newest → oldest). No heavy date
  // headers: per-row relative time ("2 giờ trước") answers recency directly and
  // scans better than date dividers in both the 3-item panel and the long sheet.
  const hasLimit = maxItems && maxItems > 0 && !showAll;
  const totalItems = timeline.length;
  const itemsToShow = hasLimit ? maxItems : totalItems;
  const sortedTimeline = [...(timeline as TimelineItem[])].sort(
    (a, b) => new Date(b.timestamp || 0).getTime() - new Date(a.timestamp || 0).getTime()
  );
  const visibleTimeline = hasLimit ? sortedTimeline.slice(0, itemsToShow) : sortedTimeline;
  const remainingItems = Math.max(0, totalItems - visibleTimeline.length);

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

  // Relative "time ago" — hydration-safe: absolute on SSR (now===null), relative
  // on client. Tabular mono rendering keeps the time column aligned like a log.
  const formatWhen = (ts: string): string => {
    const d = parseISO(ts);
    if (now === null) return format(d, "dd/MM HH:mm");
    const diffMs = now - d.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "vừa xong";
    if (mins < 60) return `${mins} phút trước`;
    if (isToday(d)) return `${Math.floor(mins / 60)} giờ trước`;
    if (isYesterday(d)) return `Hôm qua ${format(d, "HH:mm")}`;
    const days = Math.floor(diffMs / 86400000);
    if (days < 7) return `${days} ngày trước`;
    return format(d, "dd/MM/yyyy");
  };

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
      <div className="animate-in fade-in duration-300">
        {visibleTimeline.map((event, index) => {
          const eventType = event.type || "lead_created";
          const eventData = event.data || {};

          const isConsultation =
            eventType === "consultation" ||
            eventType === "consultation_added" ||
            eventType === "consultation_updated";
          const isAssignment = eventType === "assignment" || eventType === "assigned";

          const config = getEventConfig(
            eventType,
            isConsultation ? (eventData as { method?: string }).method : undefined
          );
          const Icon = config.icon;

          const consultData = isConsultation ? (eventData as Consultation) : null;
          const outcomeType = consultData?.consultation_status?.outcome_type;
          const spine = getOutcomeSpine(isConsultation ? outcomeType : null);

          // Title / note / actor
          let title = "";
          let note = "";
          let actorName = "";
          if (isConsultation && consultData) {
            const statusName = consultData.consultation_status?.name || "Tư vấn";
            title = statusName;
            // Bỏ note tự-sinh (trùng tên trạng thái) — chỉ giữ ghi chú thật.
            const rawNotes = consultData.notes || "";
            const autoPatterns = [
              `Ghi nhận nhanh: ${statusName}`,
              `Ghi nhận: ${statusName}`,
            ];
            if (rawNotes && !autoPatterns.includes(rawNotes)) note = rawNotes;
            actorName = consultData.officer?.full_name || "";
          } else if (isAssignment) {
            const assignData = eventData as { reason?: string; officer?: { full_name?: string } };
            title = "Phân công lead";
            note = assignData.reason || "";
            actorName = assignData.officer?.full_name || "";
          } else {
            title = event.description || config.label;
            actorName = event.actor?.full_name || "";
          }

          const itemId = isConsultation
            ? (eventData as { id?: number })?.id
            : isAssignment
              ? (eventData as { id?: number })?.id
              : undefined;
          const itemKey = `${event.type}-${event.timestamp}-${itemId ?? index}`;
          const isLast = index === visibleTimeline.length - 1;

          // Lịch hẹn: chỉ cho thao tác khi hẹn ở TƯƠNG LAI (client-time) + có quyền.
          const schedMs = consultData?.scheduled_at
            ? new Date(consultData.scheduled_at).getTime()
            : null;
          const isFutureAppt = now !== null && schedMs !== null && schedMs > now;
          const canActOnAppt = isPrivilegedActor || consultData?.id === latestConsultationId;

          const durationMin =
            consultData?.duration_minutes && consultData.duration_minutes > 0
              ? consultData.duration_minutes
              : null;

          const assignMethod = isAssignment ? (eventData as { method?: string }).method : undefined;
          const assignMethodLabel =
            assignMethod === "automatic"
              ? "Tự động"
              : assignMethod === "officer_reassign"
                ? "Yêu cầu phân công lại"
                : assignMethod === "manual"
                  ? "Thủ công"
                  : null;

          return (
            <div key={itemKey} className="group relative flex gap-3 pb-5 last:pb-0">
              {/* Spine + node — the outcome-colored rail */}
              <div className="relative flex w-6 shrink-0 justify-center">
                {!isLast && (
                  <span
                    className={cn(
                      "absolute left-1/2 top-6 -bottom-5 w-0.5 -translate-x-1/2 rounded-full",
                      spine.seg
                    )}
                  />
                )}
                <span
                  className={cn(
                    "relative z-10 flex h-6 w-6 items-center justify-center rounded-lg ring-4 ring-background",
                    spine.node
                  )}
                >
                  <Icon className={cn("h-3.5 w-3.5", spine.icon)} />
                </span>
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1">
                {/* Line 1: status · outcome tag · time · actions */}
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">{title}</span>
                  {spine.emphasize && (
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-px text-[10px] font-bold uppercase tracking-wide",
                        spine.tag
                      )}
                    >
                      {spine.tagLabel}
                    </span>
                  )}
                  <time
                    suppressHydrationWarning
                    className="ml-auto shrink-0 font-mono text-[11px] tabular-nums tracking-tight text-muted-foreground"
                  >
                    {formatWhen(event.timestamp || "")}
                  </time>

                  {/* Overflow menu: Sửa / Xóa (lịch hẹn có control riêng bên dưới) */}
                  {isConsultation && consultData?.id && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-11 w-11 sm:h-7 sm:w-7 p-0 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity shrink-0"
                        >
                          <MoreVertical className="h-4 w-4 text-muted-foreground" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => handleEditConsultation(consultData)}>
                          <Edit className="mr-2 h-4 w-4" />
                          Sửa
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => handleDeleteConsultation(consultData.id)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Xóa
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>

                {/* Line 2: method · actor · duration · assignment method */}
                {(isConsultation || isAssignment || actorName) && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
                    {(isConsultation || isAssignment) && (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/80">
                        {config.label}
                      </span>
                    )}
                    {actorName && (
                      <>
                        {(isConsultation || isAssignment) && (
                          <span className="text-muted-foreground/40">·</span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <User className="h-3 w-3" />
                          {actorName}
                        </span>
                      </>
                    )}
                    {durationMin && (
                      <>
                        <span className="text-muted-foreground/40">·</span>
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {durationMin} phút
                        </span>
                      </>
                    )}
                    {assignMethodLabel && (
                      <>
                        <span className="text-muted-foreground/40">·</span>
                        <span>{assignMethodLabel}</span>
                      </>
                    )}
                  </div>
                )}

                {/* Note — quiet secondary line */}
                {note && (
                  <p className="mt-1.5 border-l-2 border-border pl-2.5 text-[13px] leading-relaxed text-muted-foreground">
                    {note}
                  </p>
                )}

                {/* Loss reason */}
                {isConsultation && consultData?.loss_reason_code && (() => {
                  const labels = getLossReasonLabelMap();
                  const label = consultData.loss_reason_code === "OTHER"
                    ? (consultData.loss_reason_note || "Lý do khác")
                    : labels[consultData.loss_reason_code] || consultData.loss_reason_code;
                  return (
                    <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="h-3 w-3 shrink-0" />
                      Lý do: {label}
                    </div>
                  );
                })()}

                {/* Follow-up appointment — actionable when scheduled in the future */}
                {isConsultation && consultData?.scheduled_at && (
                  <div
                    className={cn(
                      "mt-2 flex flex-wrap items-center gap-2 rounded-lg px-2.5 py-1.5",
                      isFutureAppt ? "bg-primary/5 dark:bg-primary/10" : "bg-muted"
                    )}
                  >
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 text-xs font-semibold",
                        isFutureAppt ? "text-primary" : "text-muted-foreground"
                      )}
                    >
                      <Calendar className="h-3.5 w-3.5 shrink-0" />
                      <span suppressHydrationWarning>
                        Hẹn {format(parseISO(consultData.scheduled_at), "HH:mm dd/MM")}
                      </span>
                    </span>
                    {isFutureAppt && canActOnAppt && consultData?.id && (
                      <span className="ml-auto flex gap-1.5">
                        <button
                          type="button"
                          onClick={() => openReschedule(consultData)}
                          className="inline-flex min-h-8 items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                        >
                          <CalendarClock className="h-3 w-3" />
                          Dời
                        </button>
                        <button
                          type="button"
                          onClick={() => openCancelAppointment(consultData.id)}
                          className="inline-flex min-h-8 items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-error-300 hover:text-error-600"
                        >
                          <CalendarX2 className="h-3 w-3" />
                          Hủy
                        </button>
                      </span>
                    )}
                  </div>
                )}
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
