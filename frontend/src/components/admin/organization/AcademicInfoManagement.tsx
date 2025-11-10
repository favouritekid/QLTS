// src/components/admin/organization/AcademicInfoManagement.tsx
"use client";

import { useState } from "react";
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
} from "lucide-react";
import {
  useAcademicInfoHistory,
  useDeleteAcademicInfo,
} from "@/hooks/useOrganization";
import { AcademicInfoDialog } from "./AcademicInfoDialog";
import type { Major, MajorAcademicInfo } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface AcademicInfoManagementProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  major: Major;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function AcademicInfoManagement({
  open,
  onOpenChange,
  major,
}: AcademicInfoManagementProps) {
  // States
  const [academicInfoDialogOpen, setAcademicInfoDialogOpen] = useState(false);
  const [selectedAcademicInfo, setSelectedAcademicInfo] =
    useState<MajorAcademicInfo | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [itemToDelete, setItemToDelete] = useState<MajorAcademicInfo | null>(null);

  // Queries & Mutations
  const {
    data: academicInfos = [],
    isLoading,
    error,
  } = useAcademicInfoHistory(major.id, false);
  const deleteAcademicInfoMutation = useDeleteAcademicInfo();

  // Handlers
  const handleCreate = () => {
    setSelectedAcademicInfo(null);
    setAcademicInfoDialogOpen(true);
  };

  const handleEdit = (info: MajorAcademicInfo) => {
    setSelectedAcademicInfo(info);
    setAcademicInfoDialogOpen(true);
  };

  const handleDeleteClick = (info: MajorAcademicInfo) => {
    setItemToDelete(info);
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!itemToDelete) return;

    try {
      await deleteAcademicInfoMutation.mutateAsync({
        id: itemToDelete.id,
        majorId: major.id,
      });
      setDeleteConfirmOpen(false);
      setItemToDelete(null);
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

  // Format currency
  const formatCurrency = (amount: number | null | undefined) => {
    if (amount === null || amount === undefined) return "—";
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(amount);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[900px] max-h-[90vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BookOpen className="h-5 w-5" />
              Quản lý thông tin học thuật
            </DialogTitle>
            <DialogDescription>
              <strong>{major.name}</strong> ({major.code})
              <br />
              Quản lý thông tin học thuật theo từng năm học
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Create Button */}
            <div className="flex justify-end">
              <Button onClick={handleCreate} size="sm">
                <Plus className="w-4 h-4 mr-2" />
                Thêm năm học mới
              </Button>
            </div>

            {/* Loading State */}
            {isLoading && (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-16 w-full" />
                ))}
              </div>
            )}

            {/* Error State */}
            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Không thể tải dữ liệu. Vui lòng thử lại sau.
                </AlertDescription>
              </Alert>
            )}

            {/* Empty State */}
            {!isLoading && !error && academicInfos.length === 0 && (
              <div className="text-center py-12 text-muted-foreground border-2 border-dashed rounded-lg">
                <BookOpen className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-lg font-medium">Chưa có thông tin học thuật</p>
                <p className="text-sm mt-2">
                  Thêm thông tin học thuật cho năm học đầu tiên
                </p>
                <Button onClick={handleCreate} className="mt-4" size="sm">
                  <Plus className="w-4 h-4 mr-2" />
                  Thêm ngay
                </Button>
              </div>
            )}

            {/* Data Table */}
            {!isLoading && !error && academicInfos.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <div className="max-h-[500px] overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Năm học</TableHead>
                        <TableHead>Trạng thái</TableHead>
                        <TableHead>Học phí/năm</TableHead>
                        <TableHead>Chỉ tiêu</TableHead>
                        <TableHead className="text-right">Thao tác</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {academicInfos.map((info) => (
                        <TableRow key={info.id}>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Calendar className="h-4 w-4 text-muted-foreground" />
                              <span className="font-medium">{info.academic_year}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={info.is_published ? "default" : "secondary"}
                            >
                              {info.is_published ? "Công khai" : "Nháp"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <DollarSign className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm">
                                {formatCurrency(info.tuition_fee_per_year)}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Users className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm">
                                {info.annual_admission_quota ?? "—"}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm">
                                  <MoreVertical className="w-4 h-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => handleEdit(info)}>
                                  <Edit className="w-4 h-4 mr-2" />
                                  Chỉnh sửa
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onClick={() => handleDeleteClick(info)}
                                  className="text-red-600"
                                >
                                  <Trash2 className="w-4 h-4 mr-2" />
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

      {/* Academic Info Dialog (Create/Edit) */}
      <AcademicInfoDialog
        open={academicInfoDialogOpen}
        onOpenChange={setAcademicInfoDialogOpen}
        majorId={major.id}
        majorName={major.name}
        academicInfo={selectedAcademicInfo}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa thông tin học thuật cho năm{" "}
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
