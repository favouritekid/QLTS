// src/components/leads/command-center/LeadDetailPanel.tsx
"use client";

import React, { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { LeadConsultationsTab } from "@/components/leads/LeadConsultationsTab";
import { ConsultationDialog } from "@/components/leads/ConsultationDialog";
import { QuickDisposition } from "@/components/leads/QuickDisposition";
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

export function LeadDetailPanel({
  leadId,
  onEdit,
  onDelete,
  onAssign,
}: LeadDetailPanelProps) {
  const { data: lead, isLoading } = useLead(leadId || 0, !!leadId);
  const [consultationDialogOpen, setConsultationDialogOpen] = useState(false);

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
              <Badge
                variant="outline"
                className={cn("font-bold", getScoreColor(lead.lead_score))}
              >
                Score: {lead.lead_score}
              </Badge>
              <Badge variant="secondary">
                <span
                  className={cn(
                    "w-2 h-2 rounded-full mr-1.5",
                    getStatusColor(lead.status as LeadStatus)
                  )}
                />
                {lead.status}
              </Badge>
              {lead.consultation_status && (
                <Badge
                  variant="outline"
                  style={{
                    borderColor: lead.consultation_status.color_code,
                    color: lead.consultation_status.color_code,
                  }}
                >
                  {lead.consultation_status.name}
                </Badge>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onEdit(lead)}
              className="h-8"
            >
              <Edit className="h-3.5 w-3.5 mr-1.5" />
              Sửa
            </Button>
            {!lead.assigned_officer && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAssign(lead)}
                className="h-8"
              >
                <UserPlus className="h-3.5 w-3.5 mr-1.5" />
                Gán
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
          {/* Contact Info Card */}
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

              {/* Education */}
              {lead.education_level && (
                <div className="flex items-center gap-3 text-sm">
                  <GraduationCap className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="capitalize truncate">
                    {lead.education_level.replace(/_/g, " ")}
                    {lead.gpa && ` (GPA: ${lead.gpa})`}
                  </span>
                </div>
              )}

              {/* Offering */}
              {lead.offering && (
                <div className="flex items-center gap-3 text-sm">
                  <Building className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    {lead.offering.program?.name || lead.offering.offering_type}
                    {lead.offering.program && ` (${lead.offering.offering_type})`}
                  </span>
                </div>
              )}

              {/* Assigned Officer */}
              {lead.assigned_officer && (
                <div className="flex items-center gap-3 text-sm">
                  <UserPlus className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="truncate">
                    <strong>{lead.assigned_officer.full_name}</strong>
                  </span>
                </div>
              )}

              {/* Created Date */}
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4 shrink-0" />
                <span>
                  Tạo: {new Date(lead.created_at).toLocaleDateString("vi-VN")}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Quick Actions Card - Highlighted */}
          <Card className="bg-slate-50 border-slate-200">
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Zap className="h-4 w-4 text-amber-500" />
                Quick Actions
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4 pt-0">
              <QuickDisposition leadId={lead.id} />
            </CardContent>
          </Card>

          {/* Tabs - Timeline & History */}
          <Card>
            <CardContent className="p-0">
              <Tabs defaultValue="timeline">
                <TabsList className="w-full rounded-none border-b bg-transparent h-auto p-0">
                  <TabsTrigger
                    value="timeline"
                    className="flex-1 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3"
                  >
                    Timeline
                  </TabsTrigger>
                  <TabsTrigger
                    value="consultations"
                    className="flex-1 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3"
                  >
                    Lịch sử
                  </TabsTrigger>
                </TabsList>

                <div className="p-4">
                  <TabsContent value="timeline" className="mt-0">
                    <LeadTimelineTab leadId={lead.id} />
                  </TabsContent>

                  <TabsContent value="consultations" className="mt-0">
                    <LeadConsultationsTab
                      leadId={lead.id}
                      lead={lead}
                      onAddConsultation={() => setConsultationDialogOpen(true)}
                    />
                  </TabsContent>
                </div>
              </Tabs>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>

      {/* Consultation Dialog */}
      <ConsultationDialog
        leadId={lead.id}
        open={consultationDialogOpen}
        onOpenChange={setConsultationDialogOpen}
      />
    </div>
  );
}

export default LeadDetailPanel;
