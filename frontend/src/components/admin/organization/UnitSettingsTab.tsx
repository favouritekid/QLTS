// src/components/admin/organization/UnitSettingsTab.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
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
  Settings,
  Edit,
  Trash2,
  Calendar,
  Building2,
} from "lucide-react";
import { useDeleteUnit } from "@/hooks/useOrganization";
import { UnitDialog } from "./UnitDialog";
import type { OrganizationUnit } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UnitSettingsTabProps {
  unit: OrganizationUnit;
  onUnitDeleted?: () => void;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UnitSettingsTab({ unit, onUnitDeleted }: UnitSettingsTabProps) {
  const [unitDialogOpen, setUnitDialogOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const deleteUnitMutation = useDeleteUnit();

  const handleEdit = () => {
    setUnitDialogOpen(true);
  };

  const handleDeleteClick = () => {
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    try {
      await deleteUnitMutation.mutateAsync(unit.id);
      setDeleteConfirmOpen(false);
      onUnitDeleted?.();
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

  // Format date
  const formatDate = (dateString: string | null | undefined) => {
    if (!dateString) return "N/A";
    return new Date(dateString).toLocaleDateString("vi-VN", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Settings aria-hidden="true" className="h-5 w-5" />
              Cài đặt đơn vị
            </h3>
            <p className="text-sm text-muted-foreground">
              Quản lý thông tin và cấu hình đơn vị
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      <ScrollArea className="flex-1">
        <div className="p-6 space-y-6">
          {/* Basic Information */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Thông tin cơ bản</CardTitle>
              <CardDescription>
                Thông tin chi tiết về đơn vị tổ chức
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4">
                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Tên đơn vị
                  </label>
                  <p className="text-sm mt-1">{unit.name}</p>
                </div>

                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Loại đơn vị
                  </label>
                  <div className="text-sm mt-1">
                    <Badge variant="outline">{unit.type}</Badge>
                  </div>
                </div>

                {unit.description && (
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">
                      Mô tả
                    </label>
                    <p className="text-sm mt-1">{unit.description}</p>
                  </div>
                )}

                {unit.parent_id && (
                  <div>
                    <label className="text-sm font-medium text-muted-foreground">
                      Đơn vị cha
                    </label>
                    <div className="text-sm mt-1 flex items-center gap-2">
                      <Building2 aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                      ID: {unit.parent_id}
                    </div>
                  </div>
                )}
              </div>

              <div className="pt-4">
                <Button onClick={handleEdit} variant="outline">
                  <Edit className="h-4 w-4 mr-2" />
                  Chỉnh sửa thông tin
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Statistics */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Thống kê</CardTitle>
              <CardDescription>
                Tổng quan về đơn vị
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Số chương trình
                  </label>
                  <p className="text-2xl font-bold mt-1">
                    {unit.major_programs?.length || 0}
                  </p>
                </div>

                <div>
                  <label className="text-sm font-medium text-muted-foreground">
                    Đơn vị con
                  </label>
                  <p className="text-2xl font-bold mt-1">
                    {unit.children?.length || 0}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Metadata */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Metadata</CardTitle>
              <CardDescription>
                Thông tin hệ thống về đơn vị
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <Calendar aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Tạo lúc:</span>
                <span>{formatDate(unit.created_at)}</span>
              </div>

              <div className="flex items-center gap-2 text-sm">
                <Calendar aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Cập nhật:</span>
                <span>{formatDate(unit.updated_at)}</span>
              </div>

              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Trạng thái:</span>
                <Badge variant={unit.is_active ? "default" : "secondary"}>
                  {unit.is_active ? "Hoạt động" : "Đã xóa"}
                </Badge>
              </div>
            </CardContent>
          </Card>

          {/* Danger Zone */}
          <Card className="border-error-200 dark:border-error-900">
            <CardHeader>
              <CardTitle className="text-base text-error-600 dark:text-error-400">
                Vùng nguy hiểm
              </CardTitle>
              <CardDescription>
                Các hành động không thể hoàn tác
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-medium">Xóa đơn vị</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Xóa mềm đơn vị này khỏi hệ thống. Đơn vị sẽ không còn hiển thị
                    nhưng dữ liệu vẫn được giữ lại.
                  </p>
                </div>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDeleteClick}
                  disabled={
                    (unit.children && unit.children.length > 0) ||
                    (unit.major_programs && unit.major_programs.length > 0)
                  }
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Xóa đơn vị
                </Button>
              </div>

              {((unit.children && unit.children.length > 0) ||
                (unit.major_programs && unit.major_programs.length > 0)) && (
                <div className="text-sm text-muted-foreground bg-muted p-3 rounded">
                  ⚠️ Không thể xóa đơn vị có đơn vị con hoặc chương trình. Vui lòng
                  xóa hoặc di chuyển chúng trước.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </ScrollArea>

      {/* Edit Unit Dialog */}
      <UnitDialog
        open={unitDialogOpen}
        onOpenChange={setUnitDialogOpen}
        unit={unit}
      />

      {/* Delete Confirmation */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa đơn vị{" "}
              <strong>&quot;{unit.name}&quot;</strong>?
              <br />
              <br />
              Đây là thao tác xóa mềm, dữ liệu vẫn được giữ lại trong hệ thống
              nhưng đơn vị sẽ không còn hiển thị.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-error-600 hover:bg-error-700"
            >
              Xóa đơn vị
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
