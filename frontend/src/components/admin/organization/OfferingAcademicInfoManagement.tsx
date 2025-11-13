// src/components/admin/organization/OfferingAcademicInfoManagement.tsx
"use client";

import { useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Plus,
  MoreVertical,
  Edit,
  Trash2,
  AlertCircle,
  BookOpen,
  Calendar,
  DollarSign,
  Users,
  TrendingUp,
} from "lucide-react";
import {
  useOfferingAcademicInfoList,
  useDeleteOfferingAcademicInfo,
} from "@/hooks/useOrganization";
import { OfferingAcademicInfoDialog } from "./OfferingAcademicInfoDialog";
import type { ProgramOffering, OfferingAcademicInfo } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface OfferingAcademicInfoManagementProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  offering: ProgramOffering; // Parent offering (Tier 2)
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function OfferingAcademicInfoManagement({
  open,
  onOpenChange,
  offering,
}: OfferingAcademicInfoManagementProps) {
  const [academicInfoDialogOpen, setAcademicInfoDialogOpen] = useState(false);
  const [selectedAcademicInfo, setSelectedAcademicInfo] = useState<OfferingAcademicInfo | null>(
    null
  );
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [itemToDelete, setItemToDelete] = useState<OfferingAcademicInfo | null>(null);

  const {
    data: academicInfos = [],
    isLoading,
    error,
  } = useOfferingAcademicInfoList(offering.id, false);
  const deleteAcademicInfoMutation = useDeleteOfferingAcademicInfo();

  // ✨ Tính toán danh sách các năm đã tồn tại
  const existingYears = useMemo(() => {
    return academicInfos.map((info) => info.academic_year);
  }, [academicInfos]);

  const handleCreate = () => {
    setSelectedAcademicInfo(null);
    setAcademicInfoDialogOpen(true);
  };

  const handleEdit = (info: OfferingAcademicInfo) => {
    setSelectedAcademicInfo(info);
    setAcademicInfoDialogOpen(true);
  };

  const handleDeleteClick = (info: OfferingAcademicInfo) => {
    setItemToDelete(info);
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!itemToDelete) return;

    try {
      await deleteAcademicInfoMutation.mutateAsync({
        id: itemToDelete.id,
        offeringId: offering.id,
      });
      setDeleteConfirmOpen(false);
      setItemToDelete(null);
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

  const formatCurrency = (amount: number | null | undefined) => {
    if (amount === null || amount === undefined) return "—";
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(Number(amount)); // Đảm bảo ép kiểu Number trước khi format
  };

  // ✅ AUDIT: Hàm này đảm bảo tính nhất quán dữ liệu Frontend-Backend.
  // Khi lưu thành công, dữ liệu từ Backend (newData) sẽ được set ngay vào state,
  // giúp Form hiển thị đúng dữ liệu mới nhất (bao gồm ID vừa sinh ra).
  const handleSaveSuccess = (newData: OfferingAcademicInfo, shouldClose: boolean) => {
    if (shouldClose) {
      setAcademicInfoDialogOpen(false);
      setSelectedAcademicInfo(null);
    } else {
      // Giữ dialog mở và chuyển sang chế độ Edit với dữ liệu mới
      setSelectedAcademicInfo(newData);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[90vh] sm:max-w-[900px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BookOpen className="h-5 w-5" />
              Quản lý thông tin tuyển sinh
            </DialogTitle>
            <DialogDescription>
              Loại hình: <strong>{offering.offering_type}</strong>
              <br />
              Quản lý thông tin tuyển sinh theo từng năm học
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="flex justify-end">
              <Button onClick={handleCreate} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Thêm năm học mới
              </Button>
            </div>

            {isLoading && (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>Không thể tải dữ liệu. Vui lòng thử lại sau.</AlertDescription>
              </Alert>
            )}

            {!isLoading && !error && academicInfos.length === 0 && (
              <div className="text-muted-foreground rounded-lg border-2 border-dashed py-12 text-center">
                <BookOpen className="mx-auto mb-4 h-12 w-12 opacity-50" />
                <p className="text-lg font-medium">Chưa có thông tin tuyển sinh</p>
                <p className="mt-2 text-sm">Thêm thông tin tuyển sinh cho năm học đầu tiên</p>
                <Button onClick={handleCreate} className="mt-4" size="sm">
                  <Plus className="mr-2 h-4 w-4" />
                  Thêm ngay
                </Button>
              </div>
            )}

            {!isLoading && !error && academicInfos.length > 0 && (
              <div className="overflow-hidden rounded-lg border">
                <div className="max-h-[500px] overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Năm học</TableHead>
                        <TableHead>Trạng thái</TableHead>
                        <TableHead>Học phí/năm</TableHead>
                        <TableHead>Chỉ tiêu</TableHead>
                        <TableHead>Điểm chuẩn</TableHead>
                        <TableHead className="text-right">Thao tác</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {academicInfos.map((info) => (
                        <TableRow key={info.id}>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Calendar className="text-muted-foreground h-4 w-4" />
                              <span className="font-medium">{info.academic_year}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant={info.is_published ? "default" : "secondary"}>
                              {info.is_published ? "Công khai" : "Nháp"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <DollarSign className="text-muted-foreground h-4 w-4" />
                              <span className="text-sm">
                                {formatCurrency(info.tuition_fee_per_year)}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Users className="text-muted-foreground h-4 w-4" />
                              <span className="text-sm">{info.annual_admission_quota ?? "—"}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <TrendingUp className="text-muted-foreground h-4 w-4" />
                              <span className="text-sm">
                                {info.cutoff_score_previous_year ?? "—"}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm">
                                  <MoreVertical className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => handleEdit(info)}>
                                  <Edit className="mr-2 h-4 w-4" />
                                  Chỉnh sửa
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() => handleDeleteClick(info)}
                                  className="text-red-600"
                                >
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  Xóa
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* ✅ Cập nhật: Truyền existingYears vào Dialog */}
      <OfferingAcademicInfoDialog
        open={academicInfoDialogOpen}
        onOpenChange={setAcademicInfoDialogOpen}
        offering={offering}
        academicInfo={selectedAcademicInfo}
        existingYears={existingYears}
        onSaveSuccess={handleSaveSuccess} // Prop mới
      />

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa thông tin tuyển sinh cho năm{" "}
              <strong>{itemToDelete?.academic_year}</strong>?
              <br />
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-red-600 hover:bg-red-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
