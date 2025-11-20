// src/components/leads/LeadTimelineTab.tsx
"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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

// Get icon and color based on event type and method
const getEventConfig = (eventType: string, method?: string) => {
  // Consultation events - differentiate by method
  if (eventType === "consultation") {
    switch (method) {
      case "phone":
        return {
          icon: Phone,
          color: "text-blue-600",
          bgColor: "bg-blue-100",
          ringColor: "ring-blue-200",
          label: "Cuộc gọi",
        };
      case "email":
        return {
          icon: Mail,
          color: "text-yellow-600",
          bgColor: "bg-yellow-100",
          ringColor: "ring-yellow-200",
          label: "Email",
        };
      case "video":
        return {
          icon: Video,
          color: "text-purple-600",
          bgColor: "bg-purple-100",
          ringColor: "ring-purple-200",
          label: "Video call",
        };
      case "in_person":
        return {
          icon: User,
          color: "text-emerald-600",
          bgColor: "bg-emerald-100",
          ringColor: "ring-emerald-200",
          label: "Gặp trực tiếp",
        };
      default:
        return {
          icon: MessageSquare,
          color: "text-cyan-600",
          bgColor: "bg-cyan-100",
          ringColor: "ring-cyan-200",
          label: "Tư vấn",
        };
    }
  }

  // Assignment events
  if (eventType === "assignment") {
    return {
      icon: UserPlus,
      color: "text-orange-600",
      bgColor: "bg-orange-100",
      ringColor: "ring-orange-200",
      label: "Phân công",
    };
  }

  // Default
  return {
    icon: Clock,
    color: "text-gray-600",
    bgColor: "bg-gray-100",
    ringColor: "ring-gray-200",
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
const groupTimelineByDate = (timeline: Array<{
  type?: string;
  timestamp?: string;
  data?: any;
}>) => {
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

export function LeadTimelineTab({ leadId }: LeadTimelineTabProps) {
  const { data: timeline, isLoading } = useLeadTimeline(leadId);
  const deleteMutation = useDeleteConsultation();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedConsultationId, setSelectedConsultationId] = useState<number | null>(null);

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

  const groupedTimeline = groupTimelineByDate(timeline);
  const dateKeys = Object.keys(groupedTimeline).sort().reverse();

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
        {dateKeys.map((dateKey) => (
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
            <div className="relative pl-8 space-y-6">
              {/* Connecting line */}
              <div className="absolute left-[19px] top-3 bottom-3 w-0.5 bg-gradient-to-b from-border via-border to-transparent" />

              {groupedTimeline[dateKey].map((event, index) => {
                const eventType = event.type || "unknown";
                const eventData = event.data || {};
                const isConsultation = eventType === "consultation";
                const isAssignment = eventType === "assignment";

                const config = getEventConfig(
                  eventType,
                  isConsultation ? eventData.method : undefined
                );
                const Icon = config.icon;

                // Generate title based on event type
                let title = "";
                let subtitle = "";
                let actorName = "";

                if (isConsultation) {
                  const statusName = eventData.consultation_status?.name || "Tư vấn";
                  title = statusName;
                  subtitle = eventData.notes || "";
                  actorName = eventData.officer?.full_name || "";
                } else if (isAssignment) {
                  title = "Phân công lead";
                  subtitle = eventData.reason || "Lead được gán cho officer";
                  actorName = eventData.officer?.full_name || "";
                }

                return (
                  <div key={index} className="relative flex gap-4 group">
                    {/* Timeline Dot (Icon) */}
                    <div
                      className={cn(
                        "relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 border-white shadow-sm transition-all group-hover:scale-110 ring-2",
                        config.bgColor,
                        config.ringColor
                      )}
                    >
                      <Icon className={cn("h-5 w-5", config.color)} />
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
                              {isConsultation && eventData.method && (
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

                          {/* Actions */}
                          {isConsultation && eventData.id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                              onClick={() => handleDeleteConsultation(eventData.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                            </Button>
                          )}
                        </div>

                        {/* Body: Description/Notes */}
                        {subtitle && (
                          <div className="text-sm text-muted-foreground leading-relaxed pl-6 mb-3">
                            <div className="flex items-start gap-2">
                              <FileText className="h-4 w-4 shrink-0 mt-0.5 opacity-50" />
                              <p className="flex-1">{subtitle}</p>
                            </div>
                          </div>
                        )}

                        {/* Footer: Metadata */}
                        {isConsultation && (
                          <div className="flex flex-wrap gap-2 pl-6">
                            {/* Scheduled follow-up */}
                            {eventData.scheduled_at && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal gap-1 border-blue-200 bg-blue-50 text-blue-700"
                              >
                                <Calendar className="h-3 w-3" />
                                Hẹn: {format(parseISO(eventData.scheduled_at), "dd/MM HH:mm")}
                              </Badge>
                            )}

                            {/* Consultation status badge */}
                            {eventData.consultation_status && (
                              <Badge
                                variant="outline"
                                className="text-xs font-normal"
                                style={{
                                  borderColor: eventData.consultation_status.color_code,
                                  color: eventData.consultation_status.color_code,
                                }}
                              >
                                {eventData.consultation_status.name}
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
        ))}
      </div>

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
    </>
  );
}
