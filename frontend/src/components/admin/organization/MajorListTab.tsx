// src/components/admin/organization/MajorListTab.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  Plus,
  Search,
  MoreVertical,
  Edit,
  Trash2,
  BookOpen,
  GraduationCap,
} from "lucide-react";
import { useDeleteMajor } from "@/hooks/useOrganization";
import { MajorDialog } from "./MajorDialog";
import { AcademicInfoManagement } from "./AcademicInfoManagement";
import type { OrganizationUnit, Major } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface MajorListTabProps {
  unit: OrganizationUnit;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function MajorListTab({ unit }: MajorListTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [majorDialogOpen, setMajorDialogOpen] = useState(false);
  const [selectedMajor, setSelectedMajor] = useState<Major | null>(null);
  const [academicInfoManagementOpen, setAcademicInfoManagementOpen] = useState(false);
  const [selectedMajorForAcademicInfo, setSelectedMajorForAcademicInfo] =
    useState<Major | null>(null);

  // Delete confirmation
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [majorToDelete, setMajorToDelete] = useState<Major | null>(null);
  const deleteMajorMutation = useDeleteMajor();

  // Handlers
  const handleCreateMajor = () => {
    setSelectedMajor(null);
    setMajorDialogOpen(true);
  };

  const handleEditMajor = (major: Major) => {
    setSelectedMajor(major);
    setMajorDialogOpen(true);
  };

  const handleDeleteMajorClick = (major: Major) => {
    setMajorToDelete(major);
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!majorToDelete) return;
    try {
      await deleteMajorMutation.mutateAsync(majorToDelete.id);
      setDeleteConfirmOpen(false);
      setMajorToDelete(null);
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

  const handleManageAcademicInfo = (major: Major) => {
    setSelectedMajorForAcademicInfo(major);
    setAcademicInfoManagementOpen(true);
  };

  // Filter majors
  const majors = unit.majors || [];
  const filteredMajors = majors.filter(
    (major) =>
      major.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      major.code.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Ngành học</h3>
            <p className="text-sm text-muted-foreground">
              Quản lý các ngành học thuộc đơn vị này
            </p>
          </div>
          <Button onClick={handleCreateMajor}>
            <Plus className="h-4 w-4 mr-2" />
            Tạo ngành học
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Tìm kiếm ngành học..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Majors List */}
      <ScrollArea className="flex-1">
        {filteredMajors.length === 0 ? (
          <div className="p-12 text-center">
            <GraduationCap className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
            <h4 className="text-lg font-medium mb-2">
              {searchQuery ? "Không tìm thấy ngành học" : "Chưa có ngành học"}
            </h4>
            <p className="text-sm text-muted-foreground mb-4">
              {searchQuery
                ? "Thử tìm kiếm với từ khóa khác"
                : "Tạo ngành học đầu tiên cho đơn vị này"}
            </p>
            {!searchQuery && (
              <Button onClick={handleCreateMajor} size="sm">
                <Plus className="h-4 w-4 mr-2" />
                Tạo ngành học
              </Button>
            )}
          </div>
        ) : (
          <div className="p-6 grid gap-4">
            {filteredMajors.map((major) => (
              <Card key={major.id} className="overflow-hidden">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <CardTitle className="text-base flex items-center gap-2">
                        <GraduationCap className="h-4 w-4 text-muted-foreground" />
                        {major.name}
                      </CardTitle>
                      <CardDescription className="mt-1">
                        <code className="text-xs bg-muted px-2 py-0.5 rounded">
                          {major.code}
                        </code>
                      </CardDescription>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => handleManageAcademicInfo(major)}
                        >
                          <BookOpen className="h-4 w-4 mr-2" />
                          Thông tin học thuật
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => handleEditMajor(major)}>
                          <Edit className="h-4 w-4 mr-2" />
                          Chỉnh sửa
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleDeleteMajorClick(major)}
                          className="text-red-600"
                        >
                          <Trash2 className="h-4 w-4 mr-2" />
                          Xóa
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </CardHeader>
                {major.description && (
                  <CardContent className="pt-0">
                    <p className="text-sm text-muted-foreground">
                      {major.description}
                    </p>
                  </CardContent>
                )}
              </Card>
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Major Dialog */}
      <MajorDialog
        open={majorDialogOpen}
        onOpenChange={setMajorDialogOpen}
        major={selectedMajor}
        preselectedUnitId={unit.id}
      />

      {/* Academic Info Management */}
      {selectedMajorForAcademicInfo && (
        <AcademicInfoManagement
          open={academicInfoManagementOpen}
          onOpenChange={setAcademicInfoManagementOpen}
          major={selectedMajorForAcademicInfo}
        />
      )}

      {/* Delete Confirmation */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa ngành học{" "}
              <strong>&quot;{majorToDelete?.name}&quot;</strong>?
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
    </div>
  );
}
