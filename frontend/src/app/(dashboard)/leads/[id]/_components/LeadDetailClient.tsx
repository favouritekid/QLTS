// src/app/(dashboard)/leads/[id]/_components/LeadDetailClient.tsx
/**
 * LeadDetailClient - Lead Detail Page following wireframe design
 *
 * Layout Structure:
 * - HEADER: Avatar + Name + Score | Phone + GỌI NGAY | Actions
 * - ACTION BANNER: Next action reminder (overdue/scheduled/hot)
 * - MAIN CONTENT: 12-column grid (4 + 8)
 *   - LEFT (4 cols): Tabs (Overview/History/Profile) + Scoring + Checklist
 *   - RIGHT (8 cols): Quick Consultation Form + Recent History + Quick Stats
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
  Phone,
  PhoneCall,
  Copy,
  Check,
  MoreHorizontal,
  Clock,
  Calendar,
  TrendingUp,
  Target,
  FileText,
  GraduationCap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { useLead, useLeadTimeline, useLeadInsights, useDeleteLead, useAddConsultation } from "@/hooks/useLeads";
import { useWorkflowContext } from "@/hooks/useWorkflowContext";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ConsultationDialog } from "@/components/leads/ConsultationDialog";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import { ActionBanner } from "@/components/leads/ActionBanner";
import { LeadScoringCollapsible } from "@/components/leads/LeadScoringCollapsible";
import { AdmissionReadinessChecklist } from "@/components/leads/AdmissionReadinessChecklist";
import { LeadInfoTabs } from "./LeadInfoTabs";
import { WorkflowBreadcrumb } from "@/components/common";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";

interface LeadDetailClientProps {
  leadId: number;
  initialData?: Lead;
}

const getInitials = (name: string) => {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

const getScoreLabel = (score: number) => {
  if (score >= 70) return "Tiềm năng cao";
  if (score >= 50) return "Trung bình";
  if (score >= 30) return "Thấp";
  return "Rất thấp";
};

const getScoreColor = (score: number) => {
  if (score >= 70) return "text-emerald-600 bg-emerald-50";
  if (score >= 50) return "text-blue-600 bg-blue-50";
  if (score >= 30) return "text-amber-600 bg-amber-50";
  return "text-gray-500 bg-gray-50";
};

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

  // Add consultation mutation (for Mark Complete)
  const addConsultationMutation = useAddConsultation();

  const handleDelete = () => {
    deleteMutation.mutate(leadId, {
      onSuccess: () => {
        router.push("/leads");
      },
    });
  };

  // Mark scheduled appointment as complete
  // Instead of auto-creating consultation, scroll to QuickConsultationSection
  // so user can select the appropriate outcome status (respects FSM rules)
  const handleMarkComplete = () => {
    // Scroll to the consultation section for user to record the outcome
    const consultSection = document.getElementById("quick-consultation-section");
    if (consultSection) {
      consultSection.scrollIntoView({ behavior: "smooth", block: "start" });
      // Add visual highlight
      consultSection.classList.add("ring-2", "ring-amber-400", "ring-offset-2");
      setTimeout(() => {
        consultSection.classList.remove("ring-2", "ring-amber-400", "ring-offset-2");
      }, 2000);
    }
  };

  // Calculate quick stats
  const daysInPipeline = lead
    ? Math.floor((new Date().getTime() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : 0;
  const successfulContacts = lead?.consultations?.filter(
    (c) => c.consultation_status?.outcome_type === "positive"
  ).length || 0;

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col h-[calc(100vh-4rem)]">
        <div className="border-b px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Skeleton className="h-14 w-14 rounded-2xl" />
              <div className="space-y-2">
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-4 w-32" />
              </div>
            </div>
            <Skeleton className="h-12 w-64" />
            <Skeleton className="h-10 w-40" />
          </div>
        </div>
        <div className="flex-1 p-6">
          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-4 space-y-4">
              <Skeleton className="h-64 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
            <div className="col-span-8 space-y-4">
              <Skeleton className="h-96 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
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
    <div className="flex flex-col min-h-[calc(100vh-4rem)] bg-slate-50">
      {/* ===== WORKFLOW TABS ===== */}
      <div className="bg-white border-b border-slate-200 px-6">
        <WorkflowBreadcrumb
          currentPhase={workflowContext?.current_phase}
          hasAdmissionProfile={workflowContext?.has_admission_profile}
        />
      </div>

      {/* ===== HEADER: ACTION ZONE ===== */}
      <div className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="flex items-center justify-between">
          {/* Left: Lead Info */}
          <div className="flex items-center gap-4">
            <Avatar className="h-14 w-14 rounded-2xl border-2 border-background shadow-lg">
              <AvatarFallback className="rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white text-xl font-bold">
                {getInitials(lead.full_name)}
              </AvatarFallback>
            </Avatar>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-slate-900">{lead.full_name}</h1>
                <span className="text-sm text-slate-400">#{lead.id}</span>
                {lead.consultation_status && (
                  <Badge
                    variant="outline"
                    className="border-0 font-medium"
                    style={{
                      backgroundColor: `${lead.consultation_status.color_code}20`,
                      color: lead.consultation_status.color_code,
                    }}
                  >
                    {lead.consultation_status.name}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-4 mt-1.5 text-sm text-slate-600">
                {lead.offering && (
                  <span className="flex items-center gap-1.5">
                    <GraduationCap className="w-4 h-4 text-slate-400" />
                    {lead.offering.program?.name || lead.offering.offering_type}
                  </span>
                )}
                <span className="flex items-center gap-1.5">
                  <Target className="w-4 h-4 text-amber-500" />
                  <span className={cn("font-semibold", getScoreColor(lead.lead_score).split(" ")[0])}>
                    {lead.lead_score} điểm
                  </span>
                  <span className="text-slate-400">• {getScoreLabel(lead.lead_score)}</span>
                </span>
              </div>
            </div>
          </div>

          {/* Center: PHONE - Primary Action */}
          <div className="flex items-center gap-3 bg-slate-50 rounded-2xl p-3 border border-slate-200">
            <div className="flex flex-col items-end">
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-slate-900">{lead.phone}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 text-slate-400 hover:text-slate-600"
                  onClick={() => handleCopyPhone(lead.phone)}
                >
                  {phoneCopied ? (
                    <Check className="h-3.5 w-3.5 text-green-600" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
              <span className="text-xs text-slate-400">SĐT chính</span>
            </div>
            <Button
              size="lg"
              className="bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white font-semibold rounded-xl shadow-lg shadow-emerald-200 hover:shadow-emerald-300 transition-all hover:scale-105 active:scale-95"
              onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
            >
              <PhoneCall className="mr-2 h-5 w-5" />
              GỌI NGAY
            </Button>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            {lead.offering_id && (
              lead.admission_profile ? (
                <Button
                  variant="default"
                  className="bg-indigo-600 hover:bg-indigo-700 rounded-xl shadow-lg shadow-indigo-200"
                  onClick={() => router.push(`/admissions/${lead.admission_profile!.id}`)}
                >
                  <FileText className="mr-1.5 h-4 w-4" />
                  Xem hồ sơ tuyển sinh
                </Button>
              ) : (
                <Button
                  variant="default"
                  className="bg-indigo-600 hover:bg-indigo-700 rounded-xl shadow-lg shadow-indigo-200"
                  onClick={() => router.push(`/admissions/create?lead_id=${leadId}`)}
                >
                  <FileText className="mr-1.5 h-4 w-4" />
                  Tạo hồ sơ tuyển sinh
                </Button>
              )
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="rounded-xl">
                  <MoreHorizontal className="h-5 w-5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setEditDialogOpen(true)}>
                  <Edit className="mr-2 h-4 w-4" />
                  Chỉnh sửa
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setAssignDialogOpen(true)}>
                  <TrendingUp className="mr-2 h-4 w-4" />
                  Phân công lại
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => setDeleteDialogOpen(true)}
                  className="text-red-600"
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Xoá lead
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      {/* ===== ACTION BANNER ===== */}
      <div className="px-6 pt-4">
        <ActionBanner
          lead={lead}
          onMarkComplete={handleMarkComplete}
        />
      </div>

      {/* ===== MAIN CONTENT: 12-column grid (4 + 8) ===== */}
      <div className="px-6 py-4 flex-1">
        <div className="grid grid-cols-12 gap-4">
          {/* ===== LEFT PANEL (4 cols): Reference Info ===== */}
          <div className="col-span-12 lg:col-span-4 space-y-4">
            {/* Tabs: Overview / History / Profile */}
            <LeadInfoTabs
              lead={lead}
              timeline={timeline}
              onAssign={() => setAssignDialogOpen(true)}
              onCreateProfile={() => router.push(`/admissions/create?lead_id=${leadId}`)}
              onViewProfile={() =>
                lead.admission_profile && router.push(`/admissions/${lead.admission_profile.id}`)
              }
            />

            {/* Lead Scoring - Collapsible */}
            <LeadScoringCollapsible
              lead={lead}
              insights={insights}
              defaultExpanded={false}
            />

            {/* Admission Checklist */}
            <AdmissionReadinessChecklist
              lead={lead}
              onCreateProfile={() => router.push(`/admissions/create?lead_id=${leadId}`)}
              onViewProfile={() =>
                lead.admission_profile && router.push(`/admissions/${lead.admission_profile.id}`)
              }
            />
          </div>

          {/* ===== RIGHT PANEL (8 cols): Quick Actions ===== */}
          <div className="col-span-12 lg:col-span-8 space-y-4">
            {/* Quick Consultation Form */}
            <Card
              id="quick-consultation-section"
              className="rounded-2xl border-slate-200 transition-all duration-300"
            >
              <CardHeader className="pb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                    <Zap className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Ghi nhận tư vấn</CardTitle>
                    <p className="text-xs text-muted-foreground">
                      Ghi lại kết quả cuộc gọi / liên hệ
                    </p>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <QuickConsultationSection leadId={lead.id} />
              </CardContent>
            </Card>

            {/* Recent Consultation History - Compact */}
            <Card className="rounded-2xl border-slate-200">
              <CardHeader className="pb-3 flex flex-row items-center justify-between">
                <CardTitle className="text-sm font-semibold">Lịch sử tư vấn gần đây</CardTitle>
                <Button variant="link" size="sm" className="text-xs text-indigo-600 p-0 h-auto">
                  Xem tất cả →
                </Button>
              </CardHeader>
              <CardContent>
                <LeadTimelineTab leadId={leadId} compact limit={3} />
              </CardContent>
            </Card>

            {/* Quick Stats */}
            <div className="grid grid-cols-4 gap-3">
              <Card className="rounded-2xl border-slate-200 text-center p-4">
                <div className="text-2xl font-bold text-indigo-600">
                  {lead.consultation_count}
                </div>
                <div className="text-xs text-muted-foreground">Lần liên hệ</div>
              </Card>
              <Card className="rounded-2xl border-slate-200 text-center p-4">
                <div className="text-2xl font-bold text-emerald-600">{successfulContacts}</div>
                <div className="text-xs text-muted-foreground">Kết nối thành công</div>
              </Card>
              <Card className="rounded-2xl border-slate-200 text-center p-4">
                <div className="text-2xl font-bold text-amber-600">{daysInPipeline}</div>
                <div className="text-xs text-muted-foreground">Ngày từ lúc tạo</div>
              </Card>
              <Card className="rounded-2xl border-slate-200 text-center p-4">
                <div className="text-2xl font-bold text-purple-600">{lead.days_in_stage}</div>
                <div className="text-xs text-muted-foreground">Ngày trong giai đoạn</div>
              </Card>
            </div>
          </div>
        </div>
      </div>

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
              <br />
              <br />
              Lead sẽ được đánh dấu đã xoá và ẩn khỏi danh sách. Tất cả dữ liệu lịch sử (tư vấn,
              hồ sơ, nhật ký) sẽ được giữ lại.
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
