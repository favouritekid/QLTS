// src/app/(dashboard)/admin/organization/page.tsx
"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
  Building2,
  GraduationCap,
  MoreVertical,
  Plus,
  Search,
  Edit,
  Trash2,
  AlertCircle,
  BookOpen,
} from "lucide-react";
import {
  useOrganizationUnits,
  useDeleteUnit,
  useDeleteMajor,
  flattenOrganizationTree,
} from "@/hooks/useOrganization";
import { UnitDialog } from "@/components/admin/organization/UnitDialog";
import { MajorDialog } from "@/components/admin/organization/MajorDialog";
import { AcademicInfoManagement } from "@/components/admin/organization/AcademicInfoManagement";
import type { OrganizationUnit, Major } from "@/types/organization.types";

export default function OrganizationManagementPage() {
  // =====================================================================
  // STATE
  // =====================================================================

  const [activeTab, setActiveTab] = useState<"units" | "majors">("units");

  // Dialog states
  const [unitDialogOpen, setUnitDialogOpen] = useState(false);
  const [majorDialogOpen, setMajorDialogOpen] = useState(false);
  const [academicInfoManagementOpen, setAcademicInfoManagementOpen] = useState(false);
  const [selectedUnit, setSelectedUnit] = useState<OrganizationUnit | null>(null);
  const [selectedMajor, setSelectedMajor] = useState<Major | null>(null);
  const [selectedMajorForAcademicInfo, setSelectedMajorForAcademicInfo] = useState<Major | null>(null);

  // Delete confirmation states
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [itemToDelete, setItemToDelete] = useState<{
    type: "unit" | "major";
    id: number;
    name: string;
  } | null>(null);

  // Search states
  const [unitSearchQuery, setUnitSearchQuery] = useState("");
  const [majorSearchQuery, setMajorSearchQuery] = useState("");

  // =====================================================================
  // QUERIES & MUTATIONS
  // =====================================================================

  const { data: units = [], isLoading: unitsLoading, error: unitsError } = useOrganizationUnits();
  const deleteUnitMutation = useDeleteUnit();
  const deleteMajorMutation = useDeleteMajor();

  // =====================================================================
  // HANDLERS
  // =====================================================================

  const handleCreateUnit = () => {
    setSelectedUnit(null);
    setUnitDialogOpen(true);
  };

  const handleEditUnit = (unit: OrganizationUnit) => {
    setSelectedUnit(unit);
    setUnitDialogOpen(true);
  };

  const handleDeleteUnitClick = (unit: OrganizationUnit) => {
    setItemToDelete({ type: "unit", id: unit.id, name: unit.name });
    setDeleteConfirmOpen(true);
  };

  const handleCreateMajor = () => {
    setSelectedMajor(null);
    setMajorDialogOpen(true);
  };

  const handleEditMajor = (major: Major) => {
    setSelectedMajor(major);
    setMajorDialogOpen(true);
  };

  const handleDeleteMajorClick = (major: Major) => {
    setItemToDelete({ type: "major", id: major.id, name: major.name });
    setDeleteConfirmOpen(true);
  };

  const handleManageAcademicInfo = (major: Major) => {
    setSelectedMajorForAcademicInfo(major);
    setAcademicInfoManagementOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!itemToDelete) return;

    try {
      if (itemToDelete.type === "unit") {
        await deleteUnitMutation.mutateAsync(itemToDelete.id);
      } else {
        await deleteMajorMutation.mutateAsync(itemToDelete.id);
      }

      setDeleteConfirmOpen(false);
      setItemToDelete(null);
    } catch (error) {
      // Error handling is done in mutation hooks
      console.error("Delete failed:", error);
    }
  };

  // =====================================================================
  // COMPUTED DATA
  // =====================================================================

  // Flatten and filter units (only root units to avoid duplicates)
  const rootUnits = units.filter(u => u.parent_id === null);
  const flattenedUnits = flattenOrganizationTree(rootUnits);
  const filteredUnits = flattenedUnits.filter((item) =>
    item.unit.name.toLowerCase().includes(unitSearchQuery.toLowerCase())
  );

  // Get all majors and filter (only from root units to avoid duplicates)
  const allMajors: Major[] = [];
  const collectMajors = (units: OrganizationUnit[]) => {
    units.forEach((unit) => {
      if (unit.majors) {
        allMajors.push(...unit.majors);
      }
      if (unit.children && unit.children.length > 0) {
        collectMajors(unit.children);
      }
    });
  };
  collectMajors(rootUnits);

  const filteredMajors = allMajors.filter(
    (major) =>
      major.name.toLowerCase().includes(majorSearchQuery.toLowerCase()) ||
      major.code.toLowerCase().includes(majorSearchQuery.toLowerCase())
  );

  // =====================================================================
  // RENDER
  // =====================================================================

  if (unitsError) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Không thể tải dữ liệu tổ chức. Vui lòng thử lại sau.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Quản lý Tổ chức</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý các đơn vị tổ chức và ngành học trong hệ thống
        </p>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
        <TabsList className="grid w-full grid-cols-2 gap-2">
          <TabsTrigger value="units">
            <Building2 className="mr-2 h-4 w-4" />
            Đơn vị tổ chức
          </TabsTrigger>
          <TabsTrigger value="majors">
            <GraduationCap className="mr-2 h-4 w-4" />
            Ngành học
          </TabsTrigger>
        </TabsList>

        {/* Units Tab */}
        <TabsContent value="units" className="space-y-4">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Đơn vị tổ chức</CardTitle>
                <CardDescription>
                  Danh sách các đơn vị tổ chức trong hệ thống (Khoa, Phòng ban, v.v.)
                </CardDescription>
              </div>
              <Button onClick={handleCreateUnit}>
                <Plus className="w-4 h-4 mr-2" />
                Tạo mới
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {/* Search */}
            <div className="mb-4">
              <div className="relative">
                <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Tìm kiếm đơn vị..."
                  value={unitSearchQuery}
                  onChange={(e) => setUnitSearchQuery(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>

            {/* Table */}
            {unitsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : filteredUnits.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                {unitSearchQuery
                  ? "Không tìm thấy đơn vị nào"
                  : "Chưa có đơn vị tổ chức nào. Tạo mới để bắt đầu."}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tên đơn vị</TableHead>
                    <TableHead>Loại</TableHead>
                    <TableHead>Số ngành học</TableHead>
                    <TableHead>Số đơn vị con</TableHead>
                    <TableHead className="text-right">Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUnits.map(({ unit, level, hasChildren }) => (
                    <TableRow key={unit.id}>
                      <TableCell>
                        <div
                          className="font-medium"
                          style={{ paddingLeft: `${level * 1.5}rem` }}
                        >
                          {hasChildren && "↳ "}
                          {unit.name}
                        </div>
                        {unit.description && (
                          <div className="text-sm text-muted-foreground mt-1">
                            {unit.description}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>{unit.type}</TableCell>
                      <TableCell>{unit.majors?.length || 0}</TableCell>
                      <TableCell>{unit.children?.length || 0}</TableCell>
                      <TableCell className="text-right">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm">
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => handleEditUnit(unit)}>
                              <Edit className="w-4 h-4 mr-2" />
                              Chỉnh sửa
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => handleDeleteUnitClick(unit)}
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
            )}
          </CardContent>
        </Card>
        </TabsContent>

        {/* Majors Tab */}
        <TabsContent value="majors" className="space-y-4">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Ngành học</CardTitle>
                <CardDescription>
                  Danh sách các ngành học trong hệ thống
                </CardDescription>
              </div>
              <Button onClick={handleCreateMajor}>
                <Plus className="w-4 h-4 mr-2" />
                Tạo mới
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {/* Search */}
            <div className="mb-4">
              <div className="relative">
                <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Tìm kiếm ngành học..."
                  value={majorSearchQuery}
                  onChange={(e) => setMajorSearchQuery(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>

            {/* Table */}
            {unitsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : filteredMajors.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                {majorSearchQuery
                  ? "Không tìm thấy ngành học nào"
                  : "Chưa có ngành học nào. Tạo mới để bắt đầu."}
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mã ngành</TableHead>
                    <TableHead>Tên ngành học</TableHead>
                    <TableHead>Đơn vị quản lý</TableHead>
                    <TableHead className="text-right">Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredMajors.map((major) => {
                    // Find parent unit
                    const parentUnit = units.find((u) => u.id === major.unit_id);

                    return (
                      <TableRow key={major.id}>
                        <TableCell>
                          <code className="bg-muted px-2 py-1 rounded text-sm">
                            {major.code}
                          </code>
                        </TableCell>
                        <TableCell>
                          <div className="font-medium">{major.name}</div>
                          {major.description && (
                            <div className="text-sm text-muted-foreground mt-1">
                              {major.description}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          {parentUnit ? parentUnit.name : "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="sm">
                                <MoreVertical className="w-4 h-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => handleManageAcademicInfo(major)}>
                                <BookOpen className="w-4 h-4 mr-2" />
                                Thông tin học thuật
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleEditMajor(major)}>
                                <Edit className="w-4 h-4 mr-2" />
                                Chỉnh sửa
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() => handleDeleteMajorClick(major)}
                                className="text-red-600"
                              >
                                <Trash2 className="w-4 h-4 mr-2" />
                                Xóa
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <UnitDialog
        open={unitDialogOpen}
        onOpenChange={setUnitDialogOpen}
        unit={selectedUnit}
      />

      <MajorDialog
        open={majorDialogOpen}
        onOpenChange={setMajorDialogOpen}
        major={selectedMajor}
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
              Bạn có chắc chắn muốn xóa{" "}
              <strong>{itemToDelete?.type === "unit" ? "đơn vị" : "ngành học"}</strong>{" "}
              <strong>&quot;{itemToDelete?.name}&quot;</strong>?
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
