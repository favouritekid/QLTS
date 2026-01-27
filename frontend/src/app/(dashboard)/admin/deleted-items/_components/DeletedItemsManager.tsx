// src/app/(dashboard)/admin/deleted-items/_components/DeletedItemsManager.tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import {
  Trash2,
  RotateCcw,
  User,
  Phone,
  Mail,
  MessageSquare,
  Search,
  Loader2,
  AlertCircle,
  CheckCircle,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
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
import { Skeleton } from "@/components/ui/skeleton";

import {
  deletedItemsApi,
  type DeletedItemsResponse,
  type DeletedLeadSummary,
  type DeletedConsultationSummary,
} from "@/lib/api/deleted-items";

// ============================================
// HOOKS
// ============================================

function useDeletedItems(search?: string) {
  return useQuery<DeletedItemsResponse>({
    queryKey: ["admin", "deleted-items", search],
    queryFn: () => deletedItemsApi.getDeletedItems({ search, limit: 100 }),
    staleTime: 30 * 1000, // 30 seconds
  });
}

function useRestoreDeletedLead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (leadId: number) => deletedItemsApi.restoreDeletedLead(leadId),
    onSuccess: () => {
      toast.success("Đã khôi phục lead thành công");
      queryClient.invalidateQueries({ queryKey: ["admin", "deleted-items"] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message = error.response?.data?.detail || "Không thể khôi phục lead";
      toast.error("Lỗi", { description: message });
    },
  });
}

function useRestoreDeletedConsultation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (consultationId: number) =>
      deletedItemsApi.restoreDeletedConsultation(consultationId),
    onSuccess: () => {
      toast.success("Đã khôi phục ghi nhận tư vấn thành công");
      queryClient.invalidateQueries({ queryKey: ["admin", "deleted-items"] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const message =
        error.response?.data?.detail || "Không thể khôi phục ghi nhận tư vấn";
      toast.error("Lỗi", { description: message });
    },
  });
}

// ============================================
// DELETED LEADS TABLE
// ============================================

function DeletedLeadsTable({
  leads,
  isLoading,
  onRestore,
  isRestoring,
}: {
  leads: DeletedLeadSummary[];
  isLoading: boolean;
  onRestore: (leadId: number) => void;
  isRestoring: boolean;
}) {
  const [confirmLeadId, setConfirmLeadId] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (leads.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <CheckCircle className="h-12 w-12 text-green-500 mb-4" />
        <h3 className="text-lg font-medium">Không có lead nào bị xóa</h3>
        <p className="text-muted-foreground text-sm mt-1">
          Tất cả leads đều đang hoạt động bình thường.
        </p>
      </div>
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Lead</TableHead>
            <TableHead>Liên hệ</TableHead>
            <TableHead>Consultations</TableHead>
            <TableHead>Ngày xóa</TableHead>
            <TableHead className="text-right">Thao tác</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {leads.map((lead) => (
            <TableRow key={lead.id}>
              <TableCell>
                <div className="flex items-center gap-2">
                  <User className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <div className="font-medium">{lead.full_name}</div>
                    <div className="text-xs text-muted-foreground">
                      ID: #{lead.id}
                    </div>
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <div className="space-y-1 text-sm">
                  {lead.phone && (
                    <div className="flex items-center gap-1.5">
                      <Phone className="h-3 w-3 text-muted-foreground" />
                      {lead.phone}
                    </div>
                  )}
                  {lead.email && (
                    <div className="flex items-center gap-1.5">
                      <Mail className="h-3 w-3 text-muted-foreground" />
                      {lead.email}
                    </div>
                  )}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="secondary">{lead.consultation_count}</Badge>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {format(new Date(lead.deleted_at), "dd/MM/yyyy HH:mm", {
                  locale: vi,
                })}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmLeadId(lead.id)}
                  disabled={isRestoring}
                >
                  {isRestoring ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RotateCcw className="h-4 w-4" />
                  )}
                  <span className="ml-1.5">Khôi phục</span>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Confirm Dialog */}
      <AlertDialog
        open={confirmLeadId !== null}
        onOpenChange={() => setConfirmLeadId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Khôi phục Lead?</AlertDialogTitle>
            <AlertDialogDescription>
              Lead sẽ được khôi phục và hiển thị lại trong danh sách. Các
              consultations liên quan cũng sẽ được khôi phục.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmLeadId) {
                  onRestore(confirmLeadId);
                  setConfirmLeadId(null);
                }
              }}
            >
              Khôi phục
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// ============================================
// DELETED CONSULTATIONS TABLE
// ============================================

function DeletedConsultationsTable({
  consultations,
  isLoading,
  onRestore,
  isRestoring,
}: {
  consultations: DeletedConsultationSummary[];
  isLoading: boolean;
  onRestore: (consultationId: number) => void;
  isRestoring: boolean;
}) {
  const [confirmId, setConfirmId] = useState<number | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (consultations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <CheckCircle className="h-12 w-12 text-green-500 mb-4" />
        <h3 className="text-lg font-medium">
          Không có ghi nhận tư vấn nào bị xóa
        </h3>
        <p className="text-muted-foreground text-sm mt-1">
          Tất cả ghi nhận tư vấn đều đang hoạt động bình thường.
        </p>
      </div>
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Lead</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead>Ghi chú</TableHead>
            <TableHead>Ngày xóa</TableHead>
            <TableHead className="text-right">Thao tác</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {consultations.map((consultation) => (
            <TableRow key={consultation.id}>
              <TableCell>
                <div className="flex items-center gap-2">
                  <User className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <div className="font-medium">{consultation.lead_name}</div>
                    <div className="text-xs text-muted-foreground">
                      Lead ID: #{consultation.lead_id}
                    </div>
                  </div>
                </div>
              </TableCell>
              <TableCell>
                {consultation.consultation_status_name ? (
                  <Badge variant="outline">
                    {consultation.consultation_status_name}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground text-sm">-</span>
                )}
              </TableCell>
              <TableCell>
                {consultation.notes ? (
                  <div className="flex items-start gap-1.5 max-w-xs">
                    <MessageSquare className="h-3.5 w-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
                    <span className="text-sm truncate">{consultation.notes}</span>
                  </div>
                ) : (
                  <span className="text-muted-foreground text-sm">-</span>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {format(new Date(consultation.deleted_at), "dd/MM/yyyy HH:mm", {
                  locale: vi,
                })}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmId(consultation.id)}
                  disabled={isRestoring}
                >
                  {isRestoring ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RotateCcw className="h-4 w-4" />
                  )}
                  <span className="ml-1.5">Khôi phục</span>
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {/* Confirm Dialog */}
      <AlertDialog open={confirmId !== null} onOpenChange={() => setConfirmId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Khôi phục ghi nhận tư vấn?</AlertDialogTitle>
            <AlertDialogDescription>
              Ghi nhận tư vấn sẽ được khôi phục. Nếu đây là ghi nhận mới nhất,
              trạng thái lead sẽ được cập nhật theo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirmId) {
                  onRestore(confirmId);
                  setConfirmId(null);
                }
              }}
            >
              Khôi phục
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// ============================================
// MAIN COMPONENT
// ============================================

export function DeletedItemsManager() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Debounce search
  const handleSearchChange = (value: string) => {
    setSearch(value);
    // Simple debounce
    setTimeout(() => {
      setDebouncedSearch(value);
    }, 300);
  };

  const { data, isLoading, error } = useDeletedItems(
    debouncedSearch || undefined
  );

  const restoreLeadMutation = useRestoreDeletedLead();
  const restoreConsultationMutation = useRestoreDeletedConsultation();

  if (error) {
    return (
      <Card>
        <CardContent className="py-12">
          <div className="flex flex-col items-center text-center">
            <AlertCircle className="h-12 w-12 text-red-500 mb-4" />
            <h3 className="text-lg font-medium">Không thể tải dữ liệu</h3>
            <p className="text-muted-foreground text-sm mt-1">
              Vui lòng thử lại sau hoặc liên hệ admin.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Search */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Tìm kiếm theo tên, số điện thoại, email..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="max-w-md"
            />
          </div>
        </CardContent>
      </Card>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Leads đã xóa
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Trash2 className="h-5 w-5 text-red-500" />
              <span className="text-2xl font-bold">
                {isLoading ? (
                  <Skeleton className="h-8 w-12 inline-block" />
                ) : (
                  data?.total_leads ?? 0
                )}
              </span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Consultations đã xóa
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Trash2 className="h-5 w-5 text-orange-500" />
              <span className="text-2xl font-bold">
                {isLoading ? (
                  <Skeleton className="h-8 w-12 inline-block" />
                ) : (
                  data?.total_consultations ?? 0
                )}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="leads">
        <TabsList>
          <TabsTrigger value="leads" className="gap-2">
            <User className="h-4 w-4" />
            Leads ({data?.deleted_leads?.length ?? 0})
          </TabsTrigger>
          <TabsTrigger value="consultations" className="gap-2">
            <MessageSquare className="h-4 w-4" />
            Consultations ({data?.deleted_consultations?.length ?? 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="leads" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              <DeletedLeadsTable
                leads={data?.deleted_leads ?? []}
                isLoading={isLoading}
                onRestore={(leadId) => restoreLeadMutation.mutate(leadId)}
                isRestoring={restoreLeadMutation.isPending}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="consultations" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              <DeletedConsultationsTable
                consultations={data?.deleted_consultations ?? []}
                isLoading={isLoading}
                onRestore={(id) => restoreConsultationMutation.mutate(id)}
                isRestoring={restoreConsultationMutation.isPending}
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
