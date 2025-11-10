// src/components/admin/organization/MajorListTab.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
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

  // ✅ Collect all majors from unit and its descendants
  const getAllMajors = (unit: OrganizationUnit): Major[] => {
    const majors: Major[] = [...(unit.majors || [])];

    // Recursively collect majors from children
    if (unit.children && unit.children.length > 0) {
      unit.children.forEach((child) => {
        majors.push(...getAllMajors(child));
      });
    }

    return majors;
  };

  const allMajors = getAllMajors(unit);

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
  const filteredMajors = allMajors.filter(
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

      {/* Majors Table */}
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
          <div className="px-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[150px]">Mã ngành</TableHead>
                  <TableHead>Tên ngành học</TableHead>
                  <TableHead className="w-[400px]">Mô tả</TableHead>
                  <TableHead className="text-right w-[100px]">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredMajors.map((major) => (
                  <TableRow key={major.id}>
                    <TableCell>
                      <code className="text-xs bg-muted px-2 py-1 rounded font-mono">
                        {major.code}
                      </code>
                    </TableCell>
                    <TableCell className="font-medium">{major.name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {major.description || "—"}
                    </TableCell>
                    <TableCell className="text-right">
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
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
