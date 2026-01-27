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
  UserPlus,
  Video,
  Trash2,
  Edit,
  MoreVertical,
} from "lucide-react";
import { useLeadTimeline, useDeleteConsultation } from "@/hooks/useLeads";
import { format, isToday, isYesterday, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { cn } from "@/lib/utils";
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
  if (eventType === "consultation") {
    switch (method) {
      case "phone":
        return {
          icon: Phone,
          color: "text-slate-600",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Cuộc gọi",
        };
      case "email":
        return {
          icon: Mail,
          color: "text-slate-600",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Email",
        };
      case "video":
        return {
          icon: Video,
          color: "text-slate-600",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Video call",
        };
      case "in_person":
        return {
          icon: User,
          color: "text-slate-600",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Gặp trực tiếp",
        };
      default:
        return {
          icon: MessageSquare,
          color: "text-slate-600",
          bgColor: "bg-slate-100",
          ringColor: "ring-slate-200",
          label: "Tư vấn",
        };
    }
  }

  // Assignment events (backend sends "assignment", frontend may use "assigned")
  if (eventType === "assignment" || eventType === "assigned") {
    return {
      icon: UserPlus,
      color: "text-slate-600",
      bgColor: "bg-slate-100",
      ringColor: "ring-slate-200",
      label: "Phân công",
    };
  }

  // Default
  return {
    icon: Clock,
    color: "text-slate-600",
    bgColor: "bg-slate-100",
    ringColor: "ring-slate-200",
    label: "Hoạt động",
  };
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
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export function LeadTimelineTab({ leadId, maxItems, compact, limit }: LeadTimelineTabProps) {
  const { data: timeline, isLoading } = useLeadTimeline(leadId);
  const effectiveLimit = limit ?? maxItems;
  const deleteMutation = useDeleteConsultation();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedConsultationId, setSelectedConsultationId] = useState<number | null>(null);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingConsultation, setEditingConsultation] = useState<Consultation | null>(null);
  const [showAll, setShowAll] = useState(false);

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
      <div className="text-center py-12 text-muted-foreground bg-slate-50/50 rounded-lg border border-dashed">
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
      <div className="space-y-3">
        {compactItems.map((event, index) => {
          const eventType = event.type || "lead_created";
          const eventData = event.data || {};
          const isConsultation = eventType === "consultation" || eventType === "consultation_added";
          const config = getEventConfig(
            eventType,
            isConsultation ? (eventData as { method?: string }).method : undefined
          );
          const Icon = config.icon;

          const consultData = isConsultation ? (eventData as Consultation) : null;
          const statusName = consultData?.consultation_status?.name || event.description || "Hoạt động";
          const notes = consultData?.notes || "";

          return (
            <div
              key={index}
              className="flex items-center gap-4 p-3 bg-slate-50 rounded-xl"
            >
              <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0", config.bgColor)}>
                <Icon className={cn("w-5 h-5", config.color)} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">{statusName}</span>
                  <span className="text-xs text-slate-400">
                    {format(parseISO(event.timestamp || ""), "dd/MM")} • {format(parseISO(event.timestamp || ""), "HH:mm")}
                  </span>
                </div>
                {notes && (
                  <p className="text-sm text-slate-500 truncate">{notes}</p>
                )}
              </div>
            </div>
          );
        })}
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

                // Type guard helpers for typed data access
                const getConsultationData = () => eventData as import("@/types/lead.types").ConsultationEventData;
                const getAssignmentData = () => eventData as import("@/types/lead.types").AssignmentEventData;

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

                if (isConsultation && consultData) {
                  const statusName = consultData.consultation_status?.name || "Tư vấn";
                  title = statusName;

                  // Only show notes if it's not the auto-generated "Ghi nhận nhanh: {status}" format
                  const autoNotePattern = `Ghi nhận nhanh: ${statusName}`;
                  const notes = consultData.notes || "";
                  if (notes && notes !== autoNotePattern) {
                    subtitle = notes;
                  }

                  actorName = consultData.officer?.full_name || "";
                } else if (isAssignment) {
                  // Type assertion for assignment data
                  const assignData = eventData as { reason?: string; officer?: { full_name?: string } };
                  title = "Phân công lead";
                  subtitle = assignData.reason || "Lead được gán cho officer";
                  actorName = assignData.officer?.full_name || "";
                }

                return (
                  <div key={index} className="relative flex gap-3 group">
                    {/* Timeline Dot (Icon) - smaller and neutral */}
                    <div
                      className={cn(
                        "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 border-white shadow-sm transition-all ring-1",
                        config.bgColor,
                        config.ringColor
                      )}
                    >
                      <Icon className={cn("h-3.5 w-3.5", config.color)} />
                    </div>

                    {/* Content Block */}
                    <div className="flex-1 bg-card rounded-lg border shadow-sm transition-all hover:shadow-md hover:border-primary/30">
                      <div className="p-4">
                        {/* Header: Title, Actor, Time, Actions */}
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div className="flex-1 min-w-0">
                            {/* Title with method badge */}
                            <div className="flex items-center gap-2 mb-1">
                              <h4 className="font-semibold text-sm text-foreground">
                                {title}
                              </h4>
                              {isConsultation && consultData?.method && (
                                <Badge
                                  variant="secondary"
                                  className="text-[10px] px-1.5 py-0 font-normal"
                                >
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
                              <time>
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
                                  className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                                >
                                  <MoreVertical className="h-4 w-4 text-muted-foreground" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
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
                            {/* Consultation: Scheduled follow-up */}
                            {isConsultation && consultData?.scheduled_at && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal gap-1 border-blue-200 bg-blue-50 text-blue-700"
                              >
                                <Calendar className="h-3 w-3" />
                                Hẹn: {format(parseISO(consultData.scheduled_at), "dd/MM HH:mm")}
                              </Badge>
                            )}

                            {/* Consultation: Duration */}
                            {isConsultation && consultData?.duration_minutes && consultData.duration_minutes > 0 && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal gap-1 border-slate-200 bg-slate-50 text-slate-600"
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
                                  (eventData as { method?: string }).method === "officer_reassign" && "border-blue-200 bg-blue-50 text-blue-700",
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
              className="bg-red-600 hover:bg-red-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
