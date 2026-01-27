// src/app/(dashboard)/leads/[id]/_components/LeadDetailClient.tsx
/**
 * LeadDetailClient - Streamlined Lead Detail Layout
 * 
 * Layout:
 * - TOP BAR: Actions only (Edit, Delete) - breadcrumbs in layout
 * - LEFT: Sidebar with name, score, stage, personal info
 * - CENTER: Insights + Consultation (2-column: History + Quick)
 * - FOOTER (optional): Next follow-up reminder
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ClipboardCheck,
  Edit,
  Trash2,
  History,
  Zap,
  AlertCircle,
  Phone,
  Copy,
  Check,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useWorkflowContext } from "@/hooks/useWorkflowContext";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ConsultationDialog } from "@/components/leads/ConsultationDialog";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import { LeadInsightsTab } from "@/components/leads/LeadInsightsTab";
import { ActionBanner } from "@/components/leads/ActionBanner";
import { LeadScoringCollapsible } from "@/components/leads/LeadScoringCollapsible";
import { AdmissionReadinessChecklist } from "@/components/leads/AdmissionReadinessChecklist";
import { LeadSidebar } from "./LeadSidebar";
import { WorkflowBreadcrumb } from "@/components/common";
import type { Lead } from "@/types/lead.types";

interface LeadDetailClientProps {
  leadId: number;
  initialData?: Lead;
}

export function LeadDetailClient({ leadId, initialData }: LeadDetailClientProps) {
  const router = useRouter();

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [consultationDialogOpen, setConsultationDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [phoneCopied, setPhoneCopied] = useState(false);

  // Copy phone number to clipboard
  const handleCopyPhone = async (phone: string) => {
    try {
      await navigator.clipboard.writeText(phone);
      setPhoneCopied(true);
      setTimeout(() => setPhoneCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy phone:", err);
    }
  };

  // Fetch lead data
  const { data: lead, isLoading, isError, error } = useLead(leadId, true, { initialData });
  const { data: timeline } = useLeadTimeline(leadId);
  const { data: insights } = useLeadInsights(leadId);
  const { data: workflowContext } = useWorkflowContext(leadId);

  // Delete mutation
  const deleteMutation = useDeleteLead();

  const handleDelete = () => {
    deleteMutation.mutate(leadId, {
      onSuccess: () => {
        router.push("/leads");
      },
    });
  };

  // Get next follow-up from timeline (if any scheduled)
  const getNextFollowUp = () => {
    if (!lead?.consultations?.length) return null;
    const scheduled = lead.consultations.find(
      (c) => c.scheduled_at && new Date(c.scheduled_at) > new Date()
    );
    return scheduled;
  };

  const nextFollowUp = getNextFollowUp();

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col h-[calc(100vh-4rem)]">
        {/* Top bar skeleton */}
        <div className="border-b px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-7 w-16" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-9 w-16" />
          </div>
        </div>
        {/* Content skeleton */}
        <div className="flex flex-1">
          <div className="w-72 border-r p-4 space-y-4">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
          <div className="flex-1 p-6">
            <Skeleton className="h-48 w-full mb-4" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (isError || !lead) {
    return (
      <div className="container mx-auto py-6">
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-red-900">Lỗi Tải Lead</CardTitle>
            <CardDescription className="text-red-700">
              {error?.message || "Không tìm thấy lead"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => router.push("/leads")}>
              ← Quay lại danh sách
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* === TOP BAR: Workflow Breadcrumb + Phone + Actions === */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-20">
        <div className="px-6 py-2 flex items-center justify-between">
          {/* Left: Workflow Breadcrumb */}
          <WorkflowBreadcrumb
            currentPhase={workflowContext?.current_phase}
            hasAdmissionProfile={workflowContext?.has_admission_profile}
          />

          {/* Center: Prominent Phone + Call Button */}
          <div className="flex items-center gap-3 px-4 py-1.5 rounded-lg bg-green-50 border border-green-200">
            <div className="flex items-center gap-2">
              <Phone className="h-4 w-4 text-green-600" />
              <span className="font-mono text-base font-semibold text-green-800">
                {lead.phone}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0 text-green-600 hover:text-green-700 hover:bg-green-100"
                onClick={() => handleCopyPhone(lead.phone)}
              >
                {phoneCopied ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
            <Button
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white font-medium px-4"
              onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
            >
              <Phone className="mr-1.5 h-4 w-4" />
              GỌI NGAY
            </Button>
          </div>

          {/* Right: Action Buttons */}
          <div className="flex items-center gap-2">
            {/* Admission Profile Button - Show View or Create based on existing profile */}
            {lead.offering_id && (
              lead.admission_profile ? (
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => router.push(`/admissions/${lead.admission_profile!.id}`)}
                >
                  <ClipboardCheck className="mr-1.5 h-4 w-4" />
                  Xem hồ sơ tuyển sinh
                </Button>
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => router.push(`/admissions/create?lead_id=${leadId}`)}
                >
                  <ClipboardCheck className="mr-1.5 h-4 w-4" />
                  Tạo hồ sơ tuyển sinh
                </Button>
              )
            )}
            <Button variant="outline" size="sm" onClick={() => setEditDialogOpen(true)}>
              <Edit className="mr-1.5 h-4 w-4" />
              Chỉnh sửa
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setDeleteDialogOpen(true)}
            >
              <Trash2 className="mr-1.5 h-4 w-4" />
              Xoá
            </Button>
          </div>
        </div>
      </div>

      {/* === MAIN CONTENT: 12-column Grid (4 + 8) === */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6">
          <div className="grid grid-cols-12 gap-6">
            {/* LEFT COLUMN (4 cols): Lead Info + Scoring + Checklist */}
            <div className="col-span-12 lg:col-span-4 space-y-4">
              {/* Lead Identity & Personal Info (from sidebar) */}
              <LeadSidebar
                lead={lead}
                timeline={timeline}
                onAssign={() => setAssignDialogOpen(true)}
                compact
              />

              {/* Scoring Collapsible */}
              <LeadScoringCollapsible
                lead={lead}
                insights={insights}
                defaultExpanded={false}
              />

              {/* Admission Readiness Checklist */}
              <AdmissionReadinessChecklist
                lead={lead}
                onCreateProfile={() => router.push(`/admissions/create?lead_id=${leadId}`)}
                onViewProfile={() => lead.admission_profile && router.push(`/admissions/${lead.admission_profile.id}`)}
              />
            </div>

            {/* RIGHT COLUMN (8 cols): Action Area */}
            <div className="col-span-12 lg:col-span-8 space-y-4">
              {/* Action Banner - Shows priority action (overdue/scheduled/hot) */}
              <ActionBanner lead={lead} />

              {/* AI Insights - Compact Bar */}
              <LeadInsightsTab leadId={leadId} insights={insights} lead={lead} />

              {/* Quick Consultation - Primary Action */}
              <Card className="border-amber-200 bg-amber-50/30">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Zap className="h-4 w-4 text-amber-500" />
                    Ghi nhận tư vấn nhanh
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <QuickConsultationSection leadId={lead.id} />
                </CardContent>
              </Card>

              {/* Timeline History */}
              <Card className="max-h-[400px] overflow-y-auto">
                <CardHeader className="pb-3 sticky top-0 bg-card z-10 border-b">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <History className="h-4 w-4 text-muted-foreground" />
                    Lịch sử tư vấn
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4">
                  <LeadTimelineTab leadId={leadId} />
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>

      {/* === FOOTER: Follow-up Reminder (optional) === */}
      {nextFollowUp && (
        <div className="border-t bg-amber-50 px-6 py-2 flex items-center gap-3 text-sm">
          <AlertCircle className="h-4 w-4 text-amber-600" />
          <span className="text-amber-800">
            <strong>Nhắc nhở:</strong> Có lịch hẹn tiếp theo vào{" "}
            {new Date(nextFollowUp.scheduled_at!).toLocaleString("vi-VN", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      )}

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
        mode="create"
      />

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Bạn có chắc chắn?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ xoá mềm lead <strong>{lead.full_name}</strong> (ID: #{lead.id}).
              <br /><br />
              Lead sẽ được đánh dấu đã xoá và ẩn khỏi danh sách.
              Tất cả dữ liệu lịch sử (tư vấn, hồ sơ, nhật ký) sẽ được giữ lại.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="bg-red-600 hover:bg-red-700"
            >
              {deleteMutation.isPending ? "Đang xoá..." : "Xoá Lead"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
