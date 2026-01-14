/**
 * PathsList Component
 *
 * Phase 3: Admission Paths List View
 * Shows all admission paths for selected context with:
 * - Status indicators
 * - Quick actions (activate/deactivate)
 * - Navigation to path wizard for editing
 */

"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  CheckCircle2,
  Circle,
  Plus,
  Power,
  PowerOff,
  Pencil,
  Loader2,
  AlertCircle,
  ChevronLeft,
} from "lucide-react";
import { toast } from "sonner";
import {
  useAdmissionPathsByAcademicInfo,
  useActivateAdmissionPath,
  useDeactivateAdmissionPath,
} from "@/hooks/admissions/useAdmissionPaths";
import type { SelectionContext, Phase3View } from "../shared/types";
import type { AdmissionPathResponse } from "@/lib/zod/admission-path";
import type { AxiosError } from "axios";

// ============================================
// TYPES
// ============================================

interface PathsListProps {
  context: SelectionContext;
  onNavigate: (view: Phase3View) => void;
  onBack: () => void;
}

// ============================================
// COMPONENT
// ============================================

export function PathsList({ context, onNavigate, onBack }: PathsListProps) {
  const [processingPathId, setProcessingPathId] = useState<number | null>(null);

  const { data: pathsData, isLoading } = useAdmissionPathsByAcademicInfo(context.academicInfoId);
  const activateMutation = useActivateAdmissionPath();
  const deactivateMutation = useDeactivateAdmissionPath();

  const paths = pathsData?.items || [];

  // Handle activate
  const handleActivate = async (pathId: number) => {
    setProcessingPathId(pathId);
    try {
      await activateMutation.mutateAsync(pathId);
      toast.success("Đã kích hoạt đợt tuyển sinh thành công");
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      toast.error(axiosError.response?.data?.detail || "Kích hoạt thất bại");
    } finally {
      setProcessingPathId(null);
    }
  };

  // Handle deactivate
  const handleDeactivate = async (pathId: number) => {
    if (!confirm("Bạn có chắc chắn muốn ngưng hoạt động đợt tuyển sinh này?")) {
      return;
    }

    setProcessingPathId(pathId);
    try {
      await deactivateMutation.mutateAsync(pathId);
      toast.success("Đã ngưng hoạt động đợt tuyển sinh thành công");
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      toast.error(axiosError.response?.data?.detail || "Ngưng hoạt động thất bại");
    } finally {
      setProcessingPathId(null);
    }
  };

  // Handle edit
  const handleEdit = (pathId: number) => {
    onNavigate({ type: "wizard", pathId, wizardStep: 1 });
  };

  // Handle create new
  const handleCreateNew = () => {
    onNavigate({ type: "wizard", wizardStep: 1 });
  };

  // Get status badge
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <Badge className="bg-green-500">
            <CheckCircle2 className="h-3 w-3 mr-1" />
            Hoạt động
          </Badge>
        );
      case "draft":
        return (
          <Badge variant="secondary">
            <Circle className="h-3 w-3 mr-1" />
            Nháp
          </Badge>
        );
      case "inactive":
        return (
          <Badge variant="outline">
            <PowerOff className="h-3 w-3 mr-1" />
            Ngưng hoạt động
          </Badge>
        );
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Button variant="ghost" size="sm" onClick={onBack}>
              <ChevronLeft className="h-4 w-4 mr-1" />
              Đổi Ngữ cảnh
            </Button>
          </div>
          <h1 className="text-3xl font-bold">Các đợt Tuyển sinh</h1>
          <p className="text-muted-foreground mt-2">
            Năm học {context.academicYear}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => onNavigate({ type: "matrix" })}>
            Xem Ma trận Phủ
          </Button>
          <Button onClick={handleCreateNew}>
            <Plus className="h-4 w-4 mr-2" />
            Thêm Đợt mới
          </Button>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle>Danh sách Đợt đã cấu hình</CardTitle>
          <CardDescription>
            Quản lý các đợt tuyển sinh và phương thức xét tuyển cho chương trình này
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : paths.length === 0 ? (
            <div className="text-center py-12">
              <Circle className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">Chưa có đợt tuyển sinh nào được cấu hình</p>
              <p className="text-sm text-muted-foreground mt-1">
                Nhấn &quot;Thêm Đợt mới&quot; để tạo đợt xét tuyển đầu tiên
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Phương thức</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Cấu hình</TableHead>
                  <TableHead className="text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paths.map((path: AdmissionPathResponse) => (
                  <TableRow key={path.id}>
                    <TableCell>
                      <div>
                        <p className="font-medium">
                          {path.display_name || path.admission_method?.name}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {path.admission_method?.code}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>{getStatusBadge(path.status)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        {path.criteria ? (
                          <span className="text-sm text-green-600 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3" />
                            Đã cấu hình tiêu chí
                          </span>
                        ) : (
                          <span className="text-sm text-muted-foreground flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            Chưa có tiêu chí
                          </span>
                        )}
                        {path.validation_errors.length === 0 && path.status === "draft" && (
                          <span className="text-sm text-muted-foreground">
                            Sẵn sàng kích hoạt
                          </span>
                        )}
                        {path.validation_errors.length > 0 && (
                          <span className="text-sm text-amber-600">
                            {path.validation_errors.length} vấn đề cần xử lý
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        {path.can_edit && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEdit(path.id)}
                            disabled={processingPathId === path.id}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                        )}
                        {path.status === "draft" && path.can_activate && (
                          <Button
                            variant="default"
                            size="sm"
                            onClick={() => handleActivate(path.id)}
                            disabled={processingPathId === path.id}
                          >
                            {processingPathId === path.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <>
                                <Power className="h-4 w-4 mr-1" />
                                Kích hoạt
                              </>
                            )}
                          </Button>
                        )}
                        {path.status === "active" && path.available_actions.includes("deactivate") && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDeactivate(path.id)}
                            disabled={processingPathId === path.id}
                          >
                            {processingPathId === path.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <>
                                <PowerOff className="h-4 w-4 mr-1" />
                                Ngưng
                              </>
                            )}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
