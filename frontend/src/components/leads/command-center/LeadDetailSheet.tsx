// src/components/leads/command-center/LeadDetailSheet.tsx
"use client";

import React from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useLead } from "@/hooks/useLeads";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSectionV2 } from "@/components/leads/QuickConsultationSectionV2";
import { getLeadScoreTextColor, getEducationLevelLabel } from "@/constants";
import type { Lead, LeadStatus } from "@/types/lead.types";

interface LeadDetailSheetProps {
  leadId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign: (lead: Lead) => void;
}

const getStatusColor = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "bg-info-500";
    case "assigned":
      return "bg-purple-500";
    case "contacted":
      return "bg-cyan-500";
    case "qualified":
      return "bg-success-500";
    case "unqualified":
      return "bg-muted-foreground";
    case "converted":
      return "bg-success-500";
    case "rejected":
      return "bg-error-500";
    default:
      return "bg-muted-foreground";
  }
};

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export function LeadDetailSheet({
  leadId,
  open,
  onOpenChange,
  onEdit,
  onDelete,
  onAssign,
}: LeadDetailSheetProps) {
  const { data: lead, isLoading } = useLead(leadId || 0, open && !!leadId);

  return (
    <>
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        {isLoading || !lead ? (
          <div className="space-y-4">
            <SheetHeader>
              <SheetTitle>Loading Lead...</SheetTitle>
            </SheetHeader>
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
        ) : (
          <>
            <SheetHeader className="pb-4 border-b">
              {/* Lead Header */}
              <div className="flex items-start gap-4">
                <Avatar className="h-16 w-16">
                  <AvatarFallback className="text-lg font-semibold bg-primary/10 text-primary">
                    {getInitials(lead.full_name)}
                  </AvatarFallback>
                </Avatar>
                <div className="flex-1 space-y-1">
                  <SheetTitle className="text-xl">{lead.full_name}</SheetTitle>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={cn("font-bold", getLeadScoreTextColor(lead.lead_score))}
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
            </SheetHeader>

            {/* Quick Info */}
            <div className="py-4 space-y-3 border-b">
              <div className="flex items-center gap-3 text-sm">
                <Phone className="h-4 w-4 text-muted-foreground" />
                <a href={`tel:${lead.phone}`} className="hover:underline">
                  {lead.phone}
                </a>
                {lead.phone2 && (
                  <>
                    <span className="text-muted-foreground">/</span>
                    <a href={`tel:${lead.phone2}`} className="hover:underline">
                      {lead.phone2}
                    </a>
                  </>
                )}
              </div>
              {lead.email && (
                <div className="flex items-center gap-3 text-sm">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <a href={`mailto:${lead.email}`} className="hover:underline">
                    {lead.email}
                  </a>
                </div>
              )}
              {lead.location && (
                <div className="flex items-center gap-3 text-sm">
                  <MapPin className="h-4 w-4 text-muted-foreground" />
                  <span>{lead.location}</span>
                </div>
              )}
              {lead.education_level && (
                <div className="flex items-center gap-3 text-sm">
                  <GraduationCap className="h-4 w-4 text-muted-foreground" />
                  <span>
                    {getEducationLevelLabel(lead.education_level)}
                    {lead.gpa && ` (GPA: ${lead.gpa})`}
                  </span>
                </div>
              )}
              {lead.offering && (
                <div className="flex items-center gap-3 text-sm">
                  <Building className="h-4 w-4 text-muted-foreground" />
                  <span>
                    {lead.offering.program?.name || lead.offering.offering_type}
                    {lead.offering.program && ` (${lead.offering.offering_type})`}
                  </span>
                </div>
              )}
              {lead.assigned_officer && (
                <div className="flex items-center gap-3 text-sm">
                  <UserPlus className="h-4 w-4 text-muted-foreground" />
                  <span>
                    Assigned to: <strong>{lead.assigned_officer.full_name}</strong>
                  </span>
                </div>
              )}
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4" />
                <span>
                  Created: {new Date(lead.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>

            {/* Tabs */}
            <Tabs defaultValue="quick" className="mt-4">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="quick">Tư vấn</TabsTrigger>
                <TabsTrigger value="timeline">Timeline</TabsTrigger>
              </TabsList>

              <TabsContent value="quick" className="mt-4">
                <QuickConsultationSectionV2 leadId={lead.id} />
              </TabsContent>

              <TabsContent value="timeline" className="mt-4">
                <LeadTimelineTab leadId={lead.id} />
              </TabsContent>
            </Tabs>

            {/* Action Buttons */}
            <div className="mt-6 pt-4 border-t flex gap-2">
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
                aria-label="Xóa lead"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
    </>
  );
}
