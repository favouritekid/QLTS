// src/components/leads/command-center/LeadDetailPanel.tsx
"use client";

import React, { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  if (score >= 80) return "text-red-600 bg-red-50";
  if (score >= 50) return "text-yellow-600 bg-yellow-50";
  return "text-gray-600 bg-gray-50";
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
              Select a lead to view details
            </p>
            <p className="text-sm text-muted-foreground/70">
              Click on a lead from the list
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
            </div>
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* Quick Info */}
          <div className="space-y-2.5 pb-4 border-b">
            <div className="flex items-center gap-3 text-sm">
              <Phone className="h-4 w-4 text-muted-foreground shrink-0" />
              <a href={`tel:${lead.phone}`} className="hover:underline truncate">
                {lead.phone}
              </a>
              {lead.phone2 && (
                <>
                  <span className="text-muted-foreground">/</span>
                  <a href={`tel:${lead.phone2}`} className="hover:underline truncate">
                    {lead.phone2}
                  </a>
                </>
              )}
            </div>
            <div className="flex items-center gap-3 text-sm">
              <Mail className="h-4 w-4 text-muted-foreground shrink-0" />
              <a href={`mailto:${lead.email}`} className="hover:underline truncate">
                {lead.email}
              </a>
            </div>
            {lead.location && (
              <div className="flex items-center gap-3 text-sm">
                <MapPin className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="truncate">{lead.location}</span>
              </div>
            )}
            {lead.education_level && (
              <div className="flex items-center gap-3 text-sm">
                <GraduationCap className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="capitalize truncate">
                  {lead.education_level.replace(/_/g, " ")}
                  {lead.gpa && ` (GPA: ${lead.gpa})`}
                </span>
              </div>
            )}
            {lead.offering && (
              <div className="flex items-center gap-3 text-sm">
                <Building className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="truncate">
                  {lead.offering.program?.name || lead.offering.offering_type}
                  {lead.offering.program && ` (${lead.offering.offering_type})`}
                </span>
              </div>
            )}
            {lead.assigned_officer && (
              <div className="flex items-center gap-3 text-sm">
                <UserPlus className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="truncate">
                  Assigned to: <strong>{lead.assigned_officer.full_name}</strong>
                </span>
              </div>
            )}
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Calendar className="h-4 w-4 shrink-0" />
              <span>
                Created: {new Date(lead.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>

          {/* QuickDisposition - Pinned at top */}
          <div className="pb-4 border-b">
            <h3 className="text-sm font-medium mb-3">Quick Actions</h3>
            <QuickDisposition leadId={lead.id} />
          </div>

          {/* Tabs */}
          <Tabs defaultValue="timeline" className="mt-2">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="consultations">History</TabsTrigger>
            </TabsList>

            <TabsContent value="timeline" className="mt-3">
              <LeadTimelineTab leadId={lead.id} />
            </TabsContent>

            <TabsContent value="consultations" className="mt-3">
              <LeadConsultationsTab
                leadId={lead.id}
                lead={lead}
                onAddConsultation={() => setConsultationDialogOpen(true)}
              />
            </TabsContent>
          </Tabs>
        </div>
      </ScrollArea>

      {/* Action Buttons - Fixed at bottom */}
      <div className="shrink-0 p-4 border-t bg-background flex gap-2">
        <Button
          variant="outline"
          className="flex-1"
          onClick={() => onEdit(lead)}
        >
          <Edit className="h-4 w-4 mr-2" />
          Edit
        </Button>
        {!lead.assigned_officer && (
          <Button
            variant="outline"
            className="flex-1"
            onClick={() => onAssign(lead)}
          >
            <UserPlus className="h-4 w-4 mr-2" />
            Assign
          </Button>
        )}
        <Button
          variant="destructive"
          size="icon"
          onClick={() => onDelete(lead)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

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
