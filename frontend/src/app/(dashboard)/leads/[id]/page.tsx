// src/app/(dashboard)/leads/[id]/page.tsx
"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Edit,
  UserPlus,
  Calendar,
  TrendingUp,
  Clock,
  Mail,
  Phone,
  MapPin,
  Trash2,
  FileText,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
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

import { useLead, useLeadTimeline, useLeadInsights, useDeleteLead } from "@/hooks/useLeads";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ConsultationDialog } from "@/components/leads/ConsultationDialog";
import { LeadInfoTab } from "@/components/leads/LeadInfoTab";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { LeadConsultationsTab } from "@/components/leads/LeadConsultationsTab";
import { LeadInsightsTab } from "@/components/leads/LeadInsightsTab";
import { LeadApplicationTab } from "@/components/leads/LeadApplicationTab";
import { BackButton } from "@/components/common/BackButton";
import { Breadcrumbs } from "@/components/common/Breadcrumbs";
import type { LeadStatus } from "@/types/lead.types";

// Status badge variants (same as list page)
const getStatusBadgeVariant = (status: LeadStatus) => {
  switch (status) {
    case "new":
      return "default";
    case "assigned":
      return "secondary";
    case "contacted":
      return "outline";
    case "qualified":
      return "default";
    case "unqualified":
      return "destructive";
    case "converted":
      return "default";
    case "rejected":
      return "destructive";
    default:
      return "secondary";
  }
};

export default function LeadDetailPage() {
  const params = useParams();
  const router = useRouter();
  const leadId = Number(params.id);

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [consultationDialogOpen, setConsultationDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // Fetch lead data
  const { data: lead, isLoading, isError, error } = useLead(leadId);
  const { data: timeline } = useLeadTimeline(leadId);
  const { data: insights } = useLeadInsights(leadId);

  // Delete mutation
  const deleteMutation = useDeleteLead();

  const handleDelete = () => {
    deleteMutation.mutate(leadId, {
      onSuccess: () => {
        router.push("/leads");
      },
    });
  };

  if (isLoading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-6 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (isError || !lead) {
    return (
      <div className="container mx-auto py-6">
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-red-900">Error Loading Lead</CardTitle>
            <CardDescription className="text-red-700">
              {error?.message || "Lead not found"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <BackButton showLabel={true} />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-4">
            <BackButton size="sm" />
            <Breadcrumbs />
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">{lead.full_name}</h1>
            <Badge variant={getStatusBadgeVariant(lead.status)}>
              {lead.status.replace(/_/g, " ")}
            </Badge>
            <span className="text-sm text-muted-foreground">
              Lead #{lead.id}
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <div className="flex items-center gap-1">
              <Mail className="h-4 w-4" />
              {lead.email}
            </div>
            <div className="flex items-center gap-1">
              <Phone className="h-4 w-4" />
              {lead.phone}
            </div>
            {lead.location && (
              <div className="flex items-center gap-1">
                <MapPin className="h-4 w-4" />
                {lead.location}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setAssignDialogOpen(true)}
          >
            <UserPlus className="mr-2 h-4 w-4" />
            Assign
          </Button>
          <Button onClick={() => setEditDialogOpen(true)}>
            <Edit className="mr-2 h-4 w-4" />
            Edit
          </Button>
          <Button
            variant="destructive"
            onClick={() => setDeleteDialogOpen(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Lead Score</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{lead.lead_score}/100</div>
            <p className="text-xs text-muted-foreground">
              {lead.lead_score >= 75
                ? "High quality lead"
                : lead.lead_score >= 50
                  ? "Medium quality lead"
                  : "Low quality lead"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Time in Pipeline</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {Math.floor(
                (new Date().getTime() - new Date(lead.created_at).getTime()) /
                  (1000 * 60 * 60 * 24)
              )}{" "}
              days
            </div>
            <p className="text-xs text-muted-foreground">
              Since {new Date(lead.created_at).toLocaleDateString()}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Timeline Events</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{timeline?.length || 0}</div>
            <p className="text-xs text-muted-foreground">
              Total activities recorded
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="info" className="space-y-4">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="info">Information</TabsTrigger>
          <TabsTrigger value="application" className="flex items-center gap-1">
            <FileText className="h-4 w-4" />
            Hồ sơ
          </TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="consultations">Consultations</TabsTrigger>
          <TabsTrigger value="insights">AI Insights</TabsTrigger>
        </TabsList>

        <TabsContent value="info">
          <LeadInfoTab lead={lead} />
        </TabsContent>

        <TabsContent value="application">
          <LeadApplicationTab lead={lead} />
        </TabsContent>

        <TabsContent value="timeline">
          <LeadTimelineTab leadId={leadId} timeline={timeline} />
        </TabsContent>

        <TabsContent value="consultations">
          <LeadConsultationsTab
            leadId={leadId}
            lead={lead}
            onAddConsultation={() => setConsultationDialogOpen(true)}
          />
        </TabsContent>

        <TabsContent value="insights">
          <LeadInsightsTab leadId={leadId} insights={insights} />
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <LeadDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        lead={lead}
        mode="edit"
      />

      <AssignLeadDialog
        open={assignDialogOpen}
        onOpenChange={setAssignDialogOpen}
        lead={lead}
      />

      <ConsultationDialog
        open={consultationDialogOpen}
        onOpenChange={setConsultationDialogOpen}
        leadId={leadId}
      />

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
            <AlertDialogDescription>
              This action will soft delete the lead <strong>{lead.full_name}</strong> (ID: #{lead.id}).
              <br /><br />
              The lead will be marked as deleted and hidden from the lead list.
              All historical data (consultations, applications, logs) will be preserved.
              <br /><br />
              This action can be reversed by an administrator if needed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete Lead"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
