// src/app/(dashboard)/leads/[id]/_components/LeadDetailClient.tsx
// src/app/(dashboard)/leads/[id]/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
import type { Lead, LeadStatus } from "@/types/lead.types";

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

interface LeadDetailClientProps {
  leadId: number;
  initialData?: Lead;
}

export function LeadDetailClient({ leadId, initialData }: LeadDetailClientProps) {
  // const params = useParams();
  const router = useRouter();
  // const leadId = Number(params.id); // Now passed as prop

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
            <CardTitle className="text-red-900">Lỗi Tải Lead</CardTitle>
            <CardDescription className="text-red-700">
              {error?.message || "Không tìm thấy lead"}
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
            Phân công
          </Button>
          <Button onClick={() => setEditDialogOpen(true)}>
            <Edit className="mr-2 h-4 w-4" />
            Sửa
          </Button>
          <Button
            variant="destructive"
            onClick={() => setDeleteDialogOpen(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Xoá
          </Button>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Điểm Lead</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{lead.lead_score}/100</div>
            <p className="text-xs text-muted-foreground">
              {lead.lead_score >= 75
                ? "Lead chất lượng cao"
                : lead.lead_score >= 50
                  ? "Lead chất lượng trung bình"
                  : "Lead chất lượng thấp"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Thời Gian Trong Pipeline</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {Math.floor(
                (new Date().getTime() - new Date(lead.created_at).getTime()) /
                  (1000 * 60 * 60 * 24)
              )}{" "}
              ngày
            </div>
            <p className="text-xs text-muted-foreground">
              Từ {new Date(lead.created_at).toLocaleDateString()}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Sự Kiện Timeline</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{timeline?.length || 0}</div>
            <p className="text-xs text-muted-foreground">
              Tổng hoạt động đã ghi
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="info" className="space-y-4">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="info">Thông tin</TabsTrigger>
          <TabsTrigger value="application" className="flex items-center gap-1">
            <FileText className="h-4 w-4" />
            Hồ sơ
          </TabsTrigger>
          <TabsTrigger value="timeline">Lịch sử</TabsTrigger>
          <TabsTrigger value="consultations">Tư vấn</TabsTrigger>
          <TabsTrigger value="insights">AI Insights</TabsTrigger>
        </TabsList>

        <TabsContent value="info">
          <LeadInfoTab lead={lead} />
        </TabsContent>

        <TabsContent value="application">
          <LeadApplicationTab lead={lead} />
        </TabsContent>

        <TabsContent value="timeline">
          <LeadTimelineTab leadId={leadId} />
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
            <AlertDialogTitle>Bạn có chắc chắn?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ xoá mềm lead <strong>{lead.full_name}</strong> (ID: #{lead.id}).
              <br /><br />
              Lead sẽ được đánh dấu đã xoá và ẩn khỏi danh sách.
              Tất cả dữ liệu lịch sử (tư vấn, hồ sơ, nhật ký) sẽ được giữ lại.
              <br /><br />
              Admin có thể hoàn tác thao tác này nếu cần.
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
