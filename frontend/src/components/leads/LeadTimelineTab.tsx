// src/components/leads/LeadTimelineTab.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Clock,
  User,
  FileText,
  Phone,
  CheckCircle,
  AlertCircle,
  Calendar,
  ArrowRight,
  MessageSquare,
  Edit,
  Trash2,
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

interface LeadTimelineTabProps {
  leadId: number;
}

// Event type icons and colors
const getEventConfig = (eventType: string) => {
  switch (eventType) {
    case "lead_created":
      return {
        icon: CheckCircle,
        color: "text-blue-600",
        bgColor: "bg-blue-100",
        label: "Tạo lead",
      };
    case "assigned":
      return {
        icon: User,
        color: "text-purple-600",
        bgColor: "bg-purple-100",
        label: "Gán lead",
      };
    case "consultation_added":
      return {
        icon: Phone,
        color: "text-emerald-600",
        bgColor: "bg-emerald-100",
        label: "Tư vấn",
      };
    case "status_changed":
      return {
        icon: ArrowRight,
        color: "text-amber-600",
        bgColor: "bg-amber-100",
        label: "Đổi trạng thái",
      };
    case "pipeline_moved":
      return {
        icon: ArrowRight,
        color: "text-cyan-600",
        bgColor: "bg-cyan-100",
        label: "Pipeline",
      };
    case "note_added":
      return {
        icon: MessageSquare,
        color: "text-gray-600",
        bgColor: "bg-gray-100",
        label: "Ghi chú",
      };
    default:
      return {
        icon: Clock,
        color: "text-gray-600",
        bgColor: "bg-gray-100",
        label: "Hoạt động",
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
const groupTimelineByDate = (timeline: Array<{
  id?: number;
  type?: string;
  event_type?: string;
  timestamp?: string;
  created_at?: string | null;
  description?: string;
  actor_id?: number | null;
  actor?: { id: number; full_name: string } | null;
  metadata?: Record<string, unknown>;
}>) => {
  const groups: Record<string, typeof timeline> = {};

  // Sort by date descending (newest first)
  const sorted = [...timeline].sort((a, b) => {
    const dateA = new Date(a.created_at || a.timestamp || 0);
    const dateB = new Date(b.created_at || b.timestamp || 0);
    return dateB.getTime() - dateA.getTime();
  });

  sorted.forEach((event) => {
    const dateKey = format(
      parseISO(event.created_at || event.timestamp || new Date().toISOString()),
      "yyyy-MM-dd"
    );
    if (!groups[dateKey]) {
      groups[dateKey] = [];
    }
    groups[dateKey].push(event);
  });

  return groups;
};

export function LeadTimelineTab({ leadId }: LeadTimelineTabProps) {
  const { data: timeline, isLoading } = useLeadTimeline(leadId);
  const deleteMutation = useDeleteConsultation();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);

  if (isLoading || !timeline) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-20 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (timeline.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <Clock className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">Chưa có hoạt động nào</p>
      </div>
    );
  }

  const groupedTimeline = groupTimelineByDate(timeline);
  const dateKeys = Object.keys(groupedTimeline).sort().reverse();

  const handleDeleteConsultation = (eventId: number) => {
    setSelectedEventId(eventId);
    setDeleteDialogOpen(true);
  };

  const confirmDelete = () => {
    if (selectedEventId) {
      // Extract consultation ID from event metadata or use event ID
      deleteMutation.mutate(
        { leadId, consultationId: selectedEventId },
        {
          onSuccess: () => {
            setDeleteDialogOpen(false);
            setSelectedEventId(null);
          },
        }
      );
    }
  };

  return (
    <>
      <div className="space-y-6">
        {dateKeys.map((dateKey) => (
          <div key={dateKey}>
            {/* Date Header */}
            <div className="flex items-center gap-2 mb-3">
              <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                {formatDateGroup(dateKey + "T00:00:00")}
              </span>
              <div className="flex-1 h-px bg-border" />
            </div>

            {/* Events for this date */}
            <div className="space-y-3 pl-1">
              {groupedTimeline[dateKey].map((event, index) => {
                const eventType = event.event_type || event.type || "unknown";
                const config = getEventConfig(eventType);
                const Icon = config.icon;
                const metadata = event.metadata || {};
                const isConsultation = eventType === "consultation_added";

                return (
                  <div
                    key={event.id || index}
                    className={cn(
                      "relative flex gap-3 p-3 rounded-lg border bg-card",
                      "hover:shadow-sm transition-shadow"
                    )}
                  >
                    {/* Icon */}
                    <div
                      className={cn(
                        "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
                        config.bgColor
                      )}
                    >
                      <Icon className={cn("h-4 w-4", config.color)} />
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      {/* Header */}
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge
                            variant="secondary"
                            className="text-[10px] px-1.5 py-0"
                          >
                            {config.label}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {format(
                              parseISO(event.created_at || event.timestamp || new Date().toISOString()),
                              "HH:mm"
                            )}
                          </span>
                        </div>

                        {/* Actions for consultation */}
                        {isConsultation && event.id && (
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 w-6 p-0"
                              onClick={() => handleDeleteConsultation(event.id!)}
                            >
                              <Trash2 className="h-3 w-3 text-muted-foreground hover:text-red-600" />
                            </Button>
                          </div>
                        )}
                      </div>

                      {/* Description */}
                      <p className="text-sm">{event.description}</p>

                      {/* Consultation details */}
                      {isConsultation && metadata && (
                        <div className="mt-2 space-y-1.5">
                          {/* Notes */}
                          {metadata.notes && (
                            <div className="flex items-start gap-2 text-xs bg-muted/50 rounded p-2">
                              <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
                              <span className="text-muted-foreground">
                                {String(metadata.notes)}
                              </span>
                            </div>
                          )}

                          {/* Method */}
                          {metadata.method && (
                            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                              <Phone className="h-3 w-3" />
                              <span className="capitalize">{String(metadata.method)}</span>
                            </div>
                          )}

                          {/* Scheduled follow-up */}
                          {metadata.scheduled_at && (
                            <div className="flex items-center gap-1.5 text-xs text-blue-600">
                              <Calendar className="h-3 w-3" />
                              <span>
                                Hẹn: {format(parseISO(String(metadata.scheduled_at)), "dd/MM HH:mm")}
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Status change details */}
                      {eventType === "status_changed" && metadata && (
                        <div className="mt-1.5 flex items-center gap-1.5 text-xs">
                          {metadata.old_status && (
                            <>
                              <Badge variant="outline" className="text-[10px]">
                                {String(metadata.old_status)}
                              </Badge>
                              <ArrowRight className="h-3 w-3 text-muted-foreground" />
                            </>
                          )}
                          {metadata.new_status && (
                            <Badge variant="secondary" className="text-[10px]">
                              {String(metadata.new_status)}
                            </Badge>
                          )}
                        </div>
                      )}

                      {/* Actor */}
                      {(event.actor?.full_name || event.actor_id) && (
                        <p className="text-xs text-muted-foreground mt-1.5">
                          bởi {event.actor?.full_name || `User #${event.actor_id}`}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa ghi nhận tư vấn?</AlertDialogTitle>
            <AlertDialogDescription>
              Hành động này không thể hoàn tác. Ghi nhận tư vấn sẽ bị xóa vĩnh viễn.
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
    </>
  );
}
