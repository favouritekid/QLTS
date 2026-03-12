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

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Edit,
  Trash2,
  Zap,
  PhoneCall,
  Copy,
  Check,
  MoreHorizontal,
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

import { useLead, useLeadTimeline, useLeadInsights, useDeleteLead } from "@/hooks/useLeads";
import { useAuth } from "@/hooks/useAuth";
import { isManagerOrAbove } from "@/lib/utils/permissions";
import { useWorkflowContext } from "@/hooks/useWorkflowContext";
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ReassignLeadDialog } from "@/components/leads/ReassignLeadDialog";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSectionV2 } from "@/components/leads/QuickConsultationSectionV2";
import { ActionBanner } from "@/components/leads/ActionBanner";
import { LeadScoringCollapsible } from "@/components/leads/LeadScoringCollapsible";
import { AdmissionReadinessChecklist } from "@/components/leads/AdmissionReadinessChecklist";
import { LeadInfoTabs } from "./LeadInfoTabs";
import { WorkflowBreadcrumb } from "@/components/common";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { getLeadScoreLabel, getLeadScoreTextColor } from "@/constants";
import type { Lead, TimelineItem, LeadInsights } from "@/types/lead.types";

interface LeadDetailClientProps {
  leadId: number;
  initialData?: Lead;
  initialTimeline?: TimelineItem[];
  initialInsights?: LeadInsights;
}

const getInitials = (name: string) => {
  return name
    .split(" ")
    .filter(Boolean)
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
};

export function LeadDetailClient({ leadId, initialData, initialTimeline, initialInsights }: LeadDetailClientProps) {
  const router = useRouter();
  const { user } = useAuth();
  const hasManagerAccess = isManagerOrAbove(user);

  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [assignDialogOpen, setAssignDialogOpen] = useState(false);
  const [reassignDialogOpen, setReassignDialogOpen] = useState(false);
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

  // Fetch lead data with SSR prefetched initialData
  const { data: lead, isLoading, isError, error } = useLead(leadId, true, { initialData });
  const { data: timeline } = useLeadTimeline(leadId, { initialData: initialTimeline });
  const { data: insights } = useLeadInsights(leadId, { initialData: initialInsights });
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

  // BUG 5: Toggle to show all timeline entries
  const [showAllTimeline, setShowAllTimeline] = useState(false);

  // Calculate quick stats
  // Client-side only via ref to avoid hydration mismatch and layout shift
  const daysInPipelineRef = useRef<number>(0);
  if (lead && typeof window !== "undefined") {
    daysInPipelineRef.current = Math.floor(
      (Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24)
    );
  }
  const daysInPipeline = daysInPipelineRef.current;
  // BUG 3: Count from timeline (already loaded) instead of lead.consultations (not loaded by shallow API)
  const successfulContacts = (timeline ?? []).filter(
    (e) => {
      const isConsultation = e.type === "consultation" || e.type === "consultation_added";
      if (!isConsultation) return false;
      const data = e.data as Record<string, unknown> | undefined;
      const status = (data as { consultation_status?: { outcome_type?: string } })?.consultation_status;
      return status?.outcome_type === "positive";
    }
  ).length;

  // Loading state
  if (isLoading) {
    return (
      <div className="flex flex-col h-[calc(100vh-4rem)]">
        <div className="border-b px-4 md:px-6 py-4">
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
        <div className="flex-1 p-4 md:p-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 md:gap-6">
            <div className="lg:col-span-4 space-y-4">
              <Skeleton className="h-64 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
            <div className="lg:col-span-8 space-y-4">
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
      <div className="container mx-auto px-4 py-4 md:py-6">
        <Card className="border-error-200 bg-error-50">
          <CardHeader>
            <CardTitle className="text-error-900">Lỗi Tải Lead</CardTitle>
            <CardDescription className="text-error-700">
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
    <div className="flex flex-col min-h-[calc(100vh-4rem)] bg-muted">
      {/* ===== WORKFLOW TABS ===== */}
      <div className="bg-card border-b border-border px-4 md:px-6">
        <WorkflowBreadcrumb
          currentPhase={workflowContext?.current_phase}
          hasAdmissionProfile={workflowContext?.has_admission_profile}
        />
      </div>

      {/* ===== HEADER: ACTION ZONE ===== */}
      <div className="bg-card border-b border-border px-4 md:px-6 py-4">
        {/* Mobile: Stack vertically, Desktop: Horizontal */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          {/* Left: Lead Info */}
          <div className="flex items-center gap-3 md:gap-4">
            <Avatar className="h-12 w-12 md:h-14 md:w-14 rounded-2xl border-2 border-background shadow-lg shrink-0">
              <AvatarFallback className="rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white text-lg md:text-xl font-bold">
                {getInitials(lead.full_name)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 md:gap-3">
                <h1 className="text-lg md:text-xl font-bold font-display text-foreground truncate">{lead.full_name}</h1>
                <span className="text-sm text-muted-foreground">#{lead.id}</span>
                {lead.consultation_status && (
                  <Badge
                    variant="outline"
                    className="border-0 font-medium shrink-0"
                    style={{
                      backgroundColor: `${sanitizeColorCode(lead.consultation_status.color_code)}20`,
                      color: sanitizeColorCode(lead.consultation_status.color_code),
                    }}
                  >
                    {lead.consultation_status.name}
                  </Badge>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 md:gap-4 mt-1 md:mt-1.5 text-xs md:text-sm text-muted-foreground">
                {lead.offering && (
                  <span className="flex items-center gap-1 md:gap-1.5">
                    <GraduationCap className="w-3.5 h-3.5 md:w-4 md:h-4 text-muted-foreground" />
                    <span className="truncate max-w-[120px] md:max-w-none">{lead.offering.program?.name || lead.offering.offering_type}</span>
                  </span>
                )}
                <span className="flex items-center gap-1 md:gap-1.5">
                  <Target className="w-3.5 h-3.5 md:w-4 md:h-4 text-amber-500" />
                  <span className={cn("font-semibold", getLeadScoreTextColor(lead.lead_score).split(" ")[0])}>
                    {lead.lead_score} điểm
                  </span>
                  <span className="text-muted-foreground hidden sm:inline">• {getLeadScoreLabel(lead.lead_score)}</span>
                </span>
              </div>
            </div>
          </div>

          {/* Center: PHONE - Primary Action */}
          <div className="flex items-center gap-3 bg-muted rounded-xl md:rounded-2xl p-2 md:p-3 border border-border">
            <div className="flex flex-col items-start md:items-end flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-base md:text-lg font-bold text-foreground">{lead.phone}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 text-muted-foreground hover:text-muted-foreground shrink-0"
                  onClick={() => handleCopyPhone(lead.phone)}
                  aria-label={phoneCopied ? "Đã sao chép" : "Sao chép số điện thoại"}
                >
                  {phoneCopied ? (
                    <Check className="h-3.5 w-3.5 text-success-600" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
              <span className="text-xs text-muted-foreground">SĐT chính</span>
            </div>
            <Button
              size="default"
              className="bg-gradient-to-r from-success-500 to-success-600 hover:from-success-600 hover:to-success-700 text-white font-semibold rounded-xl shadow-lg shadow-success-200 hover:shadow-success-300 transition-colors hover:scale-105 active:scale-95 md:size-lg shrink-0"
              onClick={() => window.open(`tel:${lead.phone}`, "_blank")}
            >
              <PhoneCall className="mr-1.5 md:mr-2 h-4 w-4 md:h-5 md:w-5" />
              <span className="hidden sm:inline">GỌI NGAY</span>
              <span className="sm:hidden">Gọi</span>
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
                <Button variant="ghost" size="icon" className="rounded-xl" aria-label="Tùy chọn khác">
                  <MoreHorizontal className="h-5 w-5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setEditDialogOpen(true)}>
                  <Edit className="mr-2 h-4 w-4" />
                  Chỉnh sửa
                </DropdownMenuItem>
                {hasManagerAccess ? (
                  <DropdownMenuItem onClick={() => setAssignDialogOpen(true)}>
                    <TrendingUp className="mr-2 h-4 w-4" />
                    Chuyển giao lead
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onClick={() => setReassignDialogOpen(true)}>
                    <TrendingUp className="mr-2 h-4 w-4" />
                    Yêu cầu đổi người phụ trách
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => setDeleteDialogOpen(true)}
                  className="text-error-600"
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
      <div className="px-4 md:px-6 pt-4">
        <ActionBanner
          lead={lead}
          onMarkComplete={handleMarkComplete}
        />
      </div>

      {/* ===== MAIN CONTENT: 12-column grid (4 + 8) ===== */}
      <div className="px-4 md:px-6 py-4 flex-1">
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
            {/* Quick Consultation */}
            <Card
              id="quick-consultation-section"
              className="rounded-2xl border-border transition-colors duration-300"
            >
              <CardHeader className="pb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                    <Zap className="w-5 h-5 text-white" />
                  </div>
                  <CardTitle className="text-base">Ghi nhận tư vấn</CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <QuickConsultationSectionV2 leadId={lead.id} />
              </CardContent>
            </Card>

            {/* Recent Consultation History - Compact */}
            <Card className="rounded-2xl border-border">
              <CardHeader className="pb-3 flex flex-row items-center justify-between">
                <CardTitle className="text-sm font-semibold">Lịch sử tư vấn gần đây</CardTitle>
                <Button
                  variant="link"
                  size="sm"
                  className="text-xs text-indigo-600 p-0 h-auto"
                  onClick={() => setShowAllTimeline(!showAllTimeline)}
                >
                  {showAllTimeline ? "Thu gọn ←" : "Xem tất cả →"}
                </Button>
              </CardHeader>
              <CardContent>
                <LeadTimelineTab leadId={leadId} compact limit={showAllTimeline ? undefined : 3} />
              </CardContent>
            </Card>

            {/* Quick Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Card className="rounded-2xl border-border text-center p-4">
                <div className="text-2xl font-bold text-indigo-600">
                  {lead.consultation_count}
                </div>
                <div className="text-xs text-muted-foreground">Lần liên hệ</div>
              </Card>
              <Card className="rounded-2xl border-border text-center p-4">
                <div className="text-2xl font-bold text-success-600">{successfulContacts}</div>
                <div className="text-xs text-muted-foreground">Kết nối thành công</div>
              </Card>
              <Card className="rounded-2xl border-border text-center p-4" suppressHydrationWarning>
                <div className="text-2xl font-bold text-amber-600">{daysInPipeline}</div>
                <div className="text-xs text-muted-foreground">Ngày từ lúc tạo</div>
              </Card>
              <Card className="rounded-2xl border-border text-center p-4">
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

      <ReassignLeadDialog
        open={reassignDialogOpen}
        onOpenChange={setReassignDialogOpen}
        lead={lead}
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
              className="bg-error-600 hover:bg-error-700"
            >
              {deleteMutation.isPending ? "Đang xoá…" : "Xoá Lead"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
