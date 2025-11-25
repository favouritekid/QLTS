// src/components/leads/command-center/LeadDetailPanel.tsx
"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Edit,
  Trash2,
  UserPlus,
  Phone,
  Mail,
  MapPin,
  GraduationCap,
  Building,
  Calendar,
  User,
  Zap,
  History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import type { Lead, LeadStatus } from "@/types/lead.types";

interface LeadDetailPanelProps {
  leadId: number | null;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign: (lead: Lead) => void;
}

const getStatusColor = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "bg-blue-500";
    case "assigned":
      return "bg-purple-500";
    case "contacted":
      return "bg-cyan-500";
    case "qualified":
      return "bg-emerald-500";
    case "unqualified":
      return "bg-gray-500";
    case "converted":
      return "bg-green-500";
    case "rejected":
      return "bg-red-500";
    default:
      return "bg-gray-500";
  }
};

const getScoreColor = (score: number) => {
  if (score >= 80) return "text-red-600 bg-red-50 border-red-200";
  if (score >= 50) return "text-yellow-600 bg-yellow-50 border-yellow-200";
  return "text-gray-600 bg-gray-50 border-gray-200";
};

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

const getEducationLevelLabel = (level: string) => {
  const labels: Record<string, string> = {
    high_school: "Trung học phổ thông",
    diploma: "Cao đẳng",
    bachelor: "Cử nhân",
    master: "Thạc sĩ",
    phd: "Tiến sĩ",
    other: "Khác",
  };
  return labels[level] || level;
};

export function LeadDetailPanel({
  leadId,
  onEdit,
  onDelete,
  onAssign,
}: LeadDetailPanelProps) {
  const { data: lead, isLoading } = useLead(leadId || 0, !!leadId);

  // Empty state
  if (!leadId) {
    return (
      <div className="h-full flex items-center justify-center bg-muted/20">
        <div className="text-center space-y-3">
          <div className="mx-auto w-12 h-12 rounded-full bg-muted flex items-center justify-center">
            <User className="h-6 w-6 text-muted-foreground" />
          </div>
          <div>
            <p className="font-medium text-muted-foreground">
              Chọn lead để xem chi tiết
            </p>
            <p className="text-sm text-muted-foreground/70">
              Click vào lead trong danh sách
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Loading state
  if (isLoading || !lead) {
    return (
      <div className="h-full p-4 space-y-4">
        <div className="flex items-center gap-4">
          <Skeleton className="h-16 w-16 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="shrink-0 p-4 border-b bg-background">
        <div className="flex items-start gap-4">
          <Avatar className="h-14 w-14">
            <AvatarFallback className="text-base font-semibold bg-primary/10 text-primary">
              {getInitials(lead.full_name)}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1 space-y-1 min-w-0">
            <h2 className="text-lg font-semibold truncate">{lead.full_name}</h2>
            <div className="flex items-center gap-2 flex-wrap">
              {lead.pipeline_stage && (
                <Badge variant="outline" className="font-medium">
                  {lead.pipeline_stage.name}
                </Badge>
              )}
              <Badge variant="secondary">
                <Calendar className="h-3 w-3 mr-1.5" />
                {new Date(lead.created_at).toLocaleDateString("vi-VN")}
              </Badge>
            </div>
          </div>

          {/* Các nút hành động */}
          <div className="flex gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onEdit(lead)}
              className="h-8"
            >
              <Edit className="h-3.5 w-3.5 mr-1.5" />
              Chỉnh sửa
            </Button>
            {!lead.assigned_officer && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAssign(lead)}
                className="h-8"
              >
                <UserPlus className="h-3.5 w-3.5 mr-1.5" />
                Phân công
              </Button>
            )}
            <Button
              variant="destructive"
              size="sm"
              onClick={() => onDelete(lead)}
              className="h-8 px-2"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* Thông tin liên hệ */}
          <Card>
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm font-medium">Thông tin liên hệ</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4 pt-0 space-y-2.5">
              {/* Phone with Call Button */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-sm">
                  <Phone className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">{lead.phone}</span>
                  {lead.phone2 && (
                    <>
                      <span className="text-muted-foreground">/</span>
                      <span className="truncate">{lead.phone2}</span>
                    </>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                  onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
                >
                  <Phone className="h-3 w-3 mr-1" />
                  Gọi
                </Button>
              </div>

              {/* Email */}
              {lead.email && (
                <div className="flex items-center gap-3 text-sm">
                  <Mail className="h-4 w-4 text-muted-foreground shrink-0" />
                  <a href={`mailto:${lead.email}`} className="hover:underline truncate text-blue-600">
                    {lead.email}
                  </a>
                </div>
              )}

              {/* Location */}
              {lead.location && (
                <div className="flex items-center gap-3 text-sm">
                  <MapPin className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">{lead.location}</span>
                </div>
              )}

              {/* Trình độ học vấn */}
              {lead.education_level && (
                <div className="flex items-center gap-3 text-sm">
                  <GraduationCap className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    {getEducationLevelLabel(lead.education_level)}
                    {lead.gpa && ` (GPA: ${lead.gpa})`}
                  </span>
                </div>
              )}

              {/* Chương trình */}
              {lead.offering && (
                <div className="flex items-center gap-3 text-sm">
                  <Building className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    {lead.offering.program?.name || lead.offering.offering_type}
                    {lead.offering.program && ` (${lead.offering.offering_type})`}
                  </span>
                </div>
              )}

              {/* Tư vấn viên phụ trách */}
              {lead.assigned_officer && (
                <div className="flex items-center gap-3 text-sm">
                  <UserPlus className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    <strong>{lead.assigned_officer.full_name}</strong>
                  </span>
                </div>
              )}

              {/* Ngày tạo */}
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4 shrink-0" />
                <span>
                  Ngày tạo: {new Date(lead.created_at).toLocaleDateString("vi-VN")}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Ghi nhận tư vấn nhanh */}
          <Card className="bg-slate-50 border-slate-200">
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Zap className="h-4 w-4 text-amber-500" />
                Ghi nhận tư vấn
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4 pt-0">
              <QuickConsultationSection leadId={lead.id} />
            </CardContent>
          </Card>

          {/* Dòng thời gian */}
          <Card>
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <History className="h-4 w-4 text-muted-foreground" />
                Dòng thời gian
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4 pt-0">
              <LeadTimelineTab leadId={lead.id} />
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}

export default LeadDetailPanel;
