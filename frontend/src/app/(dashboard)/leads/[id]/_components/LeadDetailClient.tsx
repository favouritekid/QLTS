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
  Edit,
  Trash2,
  History,
  Zap,
  AlertCircle,
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
import { LeadDialog } from "@/components/leads/LeadDialog";
import { AssignLeadDialog } from "@/components/leads/AssignLeadDialog";
import { ConsultationDialog } from "@/components/leads/ConsultationDialog";
import { LeadTimelineTab } from "@/components/leads/LeadTimelineTab";
import { QuickConsultationSection } from "@/components/leads/QuickConsultationSection";
import { LeadInsightsTab } from "@/components/leads/LeadInsightsTab";
import { LeadSidebar } from "./LeadSidebar";
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

  // Fetch lead data
  const { data: lead, isLoading, isError, error } = useLead(leadId, true, { initialData });
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
      {/* === TOP BAR: Actions Only === */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-20">
        <div className="px-6 py-2 flex items-center justify-end">
          <div className="flex items-center gap-2">
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

      {/* === MAIN CONTENT: Sidebar + Center === */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar - Full version with name/score/stage */}
        <div className="w-72 shrink-0">
          <LeadSidebar 
            lead={lead} 
            timeline={timeline}
            onAssign={() => setAssignDialogOpen(true)}
          />
        </div>

        {/* Center - Consultation Focus */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-4">
            {/* AI Insights - Compact Bar */}
            <LeadInsightsTab leadId={leadId} insights={insights} />

            {/* 2-column: Timeline (left) + Quick Consultation (right) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Left: Timeline */}
              <Card className="h-fit lg:max-h-[500px] lg:overflow-y-auto">
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

              {/* Right: Quick Consultation */}
              <Card className="border-amber-200 bg-amber-50/30 h-fit">
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
