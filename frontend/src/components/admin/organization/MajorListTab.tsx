// src/components/admin/organization/MajorListTab.tsx
"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Plus,
  Search,
  MoreVertical,
  Edit,
  Trash2,
  GraduationCap,
  ChevronRight,
  ChevronDown,
  Layers,
  CalendarCheck,
  CheckCircle,
  XCircle,
} from "lucide-react";
import {
  useOrganizationUnits,
  useDeleteMajorProgram,
  useDeleteProgramOffering,
} from "@/hooks/useOrganization";
import { MajorProgramDialog } from "./MajorProgramDialog";
import { ProgramOfferingDialog } from "./ProgramOfferingDialog";
import { OfferingAcademicInfoManagement } from "./OfferingAcademicInfoManagement";
import type { OrganizationUnit, MajorProgram, ProgramOffering } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface MajorListTabProps {
  unit: OrganizationUnit;
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

/**
 * Recursively collect all major programs from unit and its descendants
 */
function collectAllMajorPrograms(unit: OrganizationUnit): MajorProgram[] {
  const programs: MajorProgram[] = [...(unit.major_programs || [])];

  if (unit.children && unit.children.length > 0) {
    unit.children.forEach((child) => {
      programs.push(...collectAllMajorPrograms(child));
    });
  }

  return programs;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function MajorListTab({ unit }: MajorListTabProps) {
  const [searchQuery, setSearchQuery] = useState("");

  // Dialog states - Tier 1 (MajorProgram)
  const [programDialogOpen, setProgramDialogOpen] = useState(false);
  const [selectedProgram, setSelectedProgram] = useState<MajorProgram | null>(null);
  const [programToDelete, setProgramToDelete] = useState<MajorProgram | null>(null);
  const [deleteProgramConfirmOpen, setDeleteProgramConfirmOpen] = useState(false);

  // Dialog states - Tier 2 (ProgramOffering)
  const [offeringDialogOpen, setOfferingDialogOpen] = useState(false);
  const [selectedOffering, setSelectedOffering] = useState<ProgramOffering | null>(null);
  const [selectedProgramForOffering, setSelectedProgramForOffering] = useState<MajorProgram | null>(
    null
  );
  const [offeringToDelete, setOfferingToDelete] = useState<ProgramOffering | null>(null);
  const [deleteOfferingConfirmOpen, setDeleteOfferingConfirmOpen] = useState(false);

  // Dialog states - Tier 3 (Academic Info Management)
  const [academicInfoManagementOpen, setAcademicInfoManagementOpen] = useState(false);
  const [selectedOfferingForAcademicInfo, setSelectedOfferingForAcademicInfo] =
    useState<ProgramOffering | null>(null);

  // Expand/Collapse state for programs
  const [expandedPrograms, setExpandedPrograms] = useState<Set<number>>(new Set());

  // Mutations
  const deleteProgramMutation = useDeleteMajorProgram();
  const deleteOfferingMutation = useDeleteProgramOffering();

  // Query
  const { isLoading } = useOrganizationUnits();

  // Get programs to display
  const isRootUnit = unit.parent_id === null;
  const allPrograms = isRootUnit ? collectAllMajorPrograms(unit) : unit.major_programs || [];

  // Filter programs
  const filteredPrograms = allPrograms.filter((program) => {
    const matchesSearch =
      program.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      program.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      program.degree_level.toLowerCase().includes(searchQuery.toLowerCase());

    if (matchesSearch) return true;

    // Also check if any offering matches search
    return program.offerings?.some((offering) =>
      offering.offering_type.toLowerCase().includes(searchQuery.toLowerCase())
    );
  });

  // Group programs by status
  const activePrograms = filteredPrograms.filter((p) => p.is_active);
  const inactivePrograms = filteredPrograms.filter((p) => !p.is_active);

  // ===================================================================
  // HANDLERS - TIER 1 (MajorProgram)
  // ===================================================================

  const handleCreateProgram = () => {
    setSelectedProgram(null);
    setProgramDialogOpen(true);
  };

  const handleEditProgram = (program: MajorProgram) => {
    setSelectedProgram(program);
    setProgramDialogOpen(true);
  };

  const handleDeleteProgramClick = (program: MajorProgram) => {
    setProgramToDelete(program);
    setDeleteProgramConfirmOpen(true);
  };

  const handleConfirmDeleteProgram = async () => {
    if (!programToDelete) return;
    try {
      await deleteProgramMutation.mutateAsync(programToDelete.id);
      setDeleteProgramConfirmOpen(false);
      setProgramToDelete(null);
    } catch (error) {
      console.error("Delete program failed:", error);
    }
  };

  // ===================================================================
  // HANDLERS - TIER 2 (ProgramOffering)
  // ===================================================================

  const handleCreateOffering = (program: MajorProgram) => {
    setSelectedProgramForOffering(program);
    setSelectedOffering(null);
    setOfferingDialogOpen(true);
  };

  const handleEditOffering = (program: MajorProgram, offering: ProgramOffering) => {
    setSelectedProgramForOffering(program);
    setSelectedOffering(offering);
    setOfferingDialogOpen(true);
  };

  const handleDeleteOfferingClick = (offering: ProgramOffering) => {
    setOfferingToDelete(offering);
    setDeleteOfferingConfirmOpen(true);
  };

  const handleConfirmDeleteOffering = async () => {
    if (!offeringToDelete) return;
    try {
      await deleteOfferingMutation.mutateAsync(offeringToDelete.id);
      setDeleteOfferingConfirmOpen(false);
      setOfferingToDelete(null);
    } catch (error) {
      console.error("Delete offering failed:", error);
    }
  };

  // ===================================================================
  // HANDLERS - TIER 3 (Academic Info)
  // ===================================================================

  const handleManageAcademicInfo = (offering: ProgramOffering) => {
    setSelectedOfferingForAcademicInfo(offering);
    setAcademicInfoManagementOpen(true);
  };

  // ===================================================================
  // EXPAND/COLLAPSE
  // ===================================================================

  const toggleProgramExpand = (programId: number) => {
    const newExpanded = new Set(expandedPrograms);
    if (newExpanded.has(programId)) {
      newExpanded.delete(programId);
    } else {
      newExpanded.add(programId);
    }
    setExpandedPrograms(newExpanded);
  };

  // ===================================================================
  // RENDER
  // ===================================================================

  const directProgramsCount = (unit.major_programs || []).length;
  const totalProgramsCount = allPrograms.length;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="space-y-4 border-b p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Chương trình đào tạo</h3>
            <p className="text-muted-foreground text-sm">
              {isRootUnit ? (
                <>
                  Hiển thị tất cả {totalProgramsCount} chương trình{" "}
                  {directProgramsCount > 0 && (
                    <span className="font-medium">
                      (bao gồm {directProgramsCount} trực thuộc và{" "}
                      {totalProgramsCount - directProgramsCount} từ các đơn vị con)
                    </span>
                  )}
                </>
              ) : (
                <>
                  Hiển thị {totalProgramsCount} chương trình trực thuộc đơn vị này
                  {totalProgramsCount === 0 && " - Chưa có chương trình nào"}
                </>
              )}
            </p>
          </div>
          <Button onClick={handleCreateProgram}>
            <Plus className="mr-2 h-4 w-4" />
            Tạo chương trình
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="text-muted-foreground absolute top-2.5 left-3 h-4 w-4" />
          <Input
            placeholder="Tìm kiếm chương trình, loại hình..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Programs List */}
      <ScrollArea className="flex-1">
        {isLoading ? (
          // Loading state
          <div className="space-y-3 p-6">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : filteredPrograms.length === 0 ? (
          // Empty state
          <div className="p-12 text-center">
            <GraduationCap className="text-muted-foreground/50 mx-auto mb-4 h-16 w-16" />
            <h4 className="mb-2 text-lg font-medium">
              {searchQuery ? "Không tìm thấy chương trình" : "Chưa có chương trình"}
            </h4>
            <p className="text-muted-foreground mb-4 text-sm">
              {searchQuery
                ? "Thử tìm kiếm với từ khóa khác"
                : "Tạo chương trình đào tạo đầu tiên cho đơn vị này"}
            </p>
            {!searchQuery && (
              <Button onClick={handleCreateProgram} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Tạo chương trình
              </Button>
            )}
          </div>
        ) : (
          // Programs table with status grouping
          <div className="p-6">
            {/* Active Programs Section */}
            {activePrograms.length > 0 && (
              <div className="mb-6">
                <div className="mb-3 flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-success-500" />
                  <h4 className="font-semibold text-success-700">
                    Đang hoạt động ({activePrograms.length})
                  </h4>
                </div>
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-muted/50">
                        <TableHead className="w-[40px]"></TableHead>
                        <TableHead>Tên chương trình</TableHead>
                        <TableHead className="w-[100px]">Mã</TableHead>
                        <TableHead className="w-[120px]">Trình độ</TableHead>
                        <TableHead className="w-[100px]">Loại hình</TableHead>
                        <TableHead className="w-[200px] text-right">Thao tác</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {activePrograms.map((program) => {
                        const isExpanded = expandedPrograms.has(program.id);
                        const hasOfferings = program.offerings && program.offerings.length > 0;

                        return (
                          <React.Fragment key={`active-${program.id}`}>
                            {/* Program Row */}
                            <TableRow className="hover:bg-muted/30">
                              <TableCell className="p-2">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => toggleProgramExpand(program.id)}
                                  className="h-9 w-9 md:h-7 md:w-7 p-0"
                                  disabled={!hasOfferings}
                                >
                                  {hasOfferings ? (
                                    isExpanded ? (
                                      <ChevronDown className="h-4 w-4" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4" />
                                    )
                                  ) : (
                                    <div className="h-4 w-4" />
                                  )}
                                </Button>
                              </TableCell>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  <GraduationCap className="text-primary h-4 w-4" />
                                  <span className="font-medium">{program.name}</span>
                                </div>
                              </TableCell>
                              <TableCell>
                                <code className="bg-muted rounded px-2 py-0.5 font-mono text-xs">
                                  {program.code}
                                </code>
                              </TableCell>
                              <TableCell>
                                <Badge variant="outline" className="text-xs">
                                  {program.degree_level}
                                </Badge>
                              </TableCell>
                              <TableCell>
                                <span className="text-muted-foreground text-sm">
                                  {hasOfferings ? program.offerings.length : 0}
                                </span>
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handleCreateOffering(program)}
                                  >
                                    <Plus className="mr-1 h-3 w-3" />
                                    Loại hình
                                  </Button>
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <Button variant="ghost" size="sm">
                                        <MoreVertical className="h-4 w-4" />
                                      </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      <DropdownMenuItem onClick={() => handleEditProgram(program)}>
                                        <Edit className="mr-2 h-4 w-4" />
                                        Chỉnh sửa
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        onClick={() => handleDeleteProgramClick(program)}
                                        className="text-error-600"
                                      >
                                        <Trash2 className="mr-2 h-4 w-4" />
                                        Xóa
                                      </DropdownMenuItem>
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                </div>
                              </TableCell>
                            </TableRow>

                            {/* Expanded Offerings */}
                            {isExpanded &&
                              hasOfferings &&
                              program.offerings.map((offering) => (
                                <TableRow key={`offering-${offering.id}`} className="bg-muted/20">
                                  <TableCell></TableCell>
                                  <TableCell colSpan={3}>
                                    <div className="flex items-center gap-2 pl-6">
                                      <Layers className="h-4 w-4 text-info-500" />
                                      <span className="text-sm">{offering.offering_type}</span>
                                      {!offering.is_active && (
                                        <Badge variant="destructive" className="text-xs">
                                          Ngưng
                                        </Badge>
                                      )}
                                      {offering.duration_semesters && (
                                        <span className="text-muted-foreground text-xs">
                                          • {offering.duration_semesters} kỳ
                                        </span>
                                      )}
                                      {offering.total_credits && (
                                        <span className="text-muted-foreground text-xs">
                                          • {offering.total_credits} TC
                                        </span>
                                      )}
                                    </div>
                                  </TableCell>
                                  <TableCell></TableCell>
                                  <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-1">
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleManageAcademicInfo(offering)}
                                      >
                                        <CalendarCheck className="mr-1 h-3 w-3" />
                                        Tuyển sinh
                                      </Button>
                                      <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                          <Button variant="ghost" size="sm">
                                            <MoreVertical className="h-4 w-4" />
                                          </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                          <DropdownMenuItem
                                            onClick={() => handleEditOffering(program, offering)}
                                          >
                                            <Edit className="mr-2 h-4 w-4" />
                                            Chỉnh sửa
                                          </DropdownMenuItem>
                                          <DropdownMenuItem
                                            onClick={() => handleDeleteOfferingClick(offering)}
                                            className="text-error-600"
                                          >
                                            <Trash2 className="mr-2 h-4 w-4" />
                                            Xóa
                                          </DropdownMenuItem>
                                        </DropdownMenuContent>
                                      </DropdownMenu>
                                    </div>
                                  </TableCell>
                                </TableRow>
                              ))}
                          </React.Fragment>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}

            {/* Inactive Programs Section */}
            {inactivePrograms.length > 0 && (
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <XCircle className="h-4 w-4 text-error-500" />
                  <h4 className="font-semibold text-error-700">
                    Ngưng hoạt động ({inactivePrograms.length})
                  </h4>
                </div>
                <div className="rounded-lg border border-error-200">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-error-50">
                        <TableHead className="w-[40px]"></TableHead>
                        <TableHead>Tên chương trình</TableHead>
                        <TableHead className="w-[100px]">Mã</TableHead>
                        <TableHead className="w-[120px]">Trình độ</TableHead>
                        <TableHead className="w-[100px]">Loại hình</TableHead>
                        <TableHead className="w-[200px] text-right">Thao tác</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {inactivePrograms.map((program) => {
                        const isExpanded = expandedPrograms.has(program.id);
                        const hasOfferings = program.offerings && program.offerings.length > 0;

                        return (
                          <React.Fragment key={`inactive-${program.id}`}>
                            {/* Program Row */}
                            <TableRow className="hover:bg-error-50/50">
                              <TableCell className="p-2">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => toggleProgramExpand(program.id)}
                                  className="h-9 w-9 md:h-7 md:w-7 p-0"
                                  disabled={!hasOfferings}
                                >
                                  {hasOfferings ? (
                                    isExpanded ? (
                                      <ChevronDown className="h-4 w-4" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4" />
                                    )
                                  ) : (
                                    <div className="h-4 w-4" />
                                  )}
                                </Button>
                              </TableCell>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  <GraduationCap className="h-4 w-4 text-error-400" />
                                  <span className="text-muted-foreground font-medium">
                                    {program.name}
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell>
                                <code className="bg-muted rounded px-2 py-0.5 font-mono text-xs">
                                  {program.code}
                                </code>
                              </TableCell>
                              <TableCell>
                                <Badge variant="outline" className="text-xs">
                                  {program.degree_level}
                                </Badge>
                              </TableCell>
                              <TableCell>
                                <span className="text-muted-foreground text-sm">
                                  {hasOfferings ? program.offerings.length : 0}
                                </span>
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-1">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => handleCreateOffering(program)}
                                  >
                                    <Plus className="mr-1 h-3 w-3" />
                                    Loại hình
                                  </Button>
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <Button variant="ghost" size="sm">
                                        <MoreVertical className="h-4 w-4" />
                                      </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      <DropdownMenuItem onClick={() => handleEditProgram(program)}>
                                        <Edit className="mr-2 h-4 w-4" />
                                        Chỉnh sửa
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        onClick={() => handleDeleteProgramClick(program)}
                                        className="text-error-600"
                                      >
                                        <Trash2 className="mr-2 h-4 w-4" />
                                        Xóa
                                      </DropdownMenuItem>
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                </div>
                              </TableCell>
                            </TableRow>

                            {/* Expanded Offerings */}
                            {isExpanded &&
                              hasOfferings &&
                              program.offerings.map((offering) => (
                                <TableRow key={`offering-${offering.id}`} className="bg-error-50/30">
                                  <TableCell></TableCell>
                                  <TableCell colSpan={3}>
                                    <div className="flex items-center gap-2 pl-6">
                                      <Layers className="h-4 w-4 text-info-500" />
                                      <span className="text-sm">{offering.offering_type}</span>
                                      {!offering.is_active && (
                                        <Badge variant="destructive" className="text-xs">
                                          Ngưng
                                        </Badge>
                                      )}
                                      {offering.duration_semesters && (
                                        <span className="text-muted-foreground text-xs">
                                          • {offering.duration_semesters} kỳ
                                        </span>
                                      )}
                                      {offering.total_credits && (
                                        <span className="text-muted-foreground text-xs">
                                          • {offering.total_credits} TC
                                        </span>
                                      )}
                                    </div>
                                  </TableCell>
                                  <TableCell></TableCell>
                                  <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-1">
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => handleManageAcademicInfo(offering)}
                                      >
                                        <CalendarCheck className="mr-1 h-3 w-3" />
                                        Tuyển sinh
                                      </Button>
                                      <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                          <Button variant="ghost" size="sm">
                                            <MoreVertical className="h-4 w-4" />
                                          </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                          <DropdownMenuItem
                                            onClick={() => handleEditOffering(program, offering)}
                                          >
                                            <Edit className="mr-2 h-4 w-4" />
                                            Chỉnh sửa
                                          </DropdownMenuItem>
                                          <DropdownMenuItem
                                            onClick={() => handleDeleteOfferingClick(offering)}
                                            className="text-error-600"
                                          >
                                            <Trash2 className="mr-2 h-4 w-4" />
                                            Xóa
                                          </DropdownMenuItem>
                                        </DropdownMenuContent>
                                      </DropdownMenu>
                                    </div>
                                  </TableCell>
                                </TableRow>
                              ))}
                          </React.Fragment>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
        )}
      </ScrollArea>

      {/* ================================================================= */}
      {/* DIALOGS */}
      {/* ================================================================= */}

      {/* Tier 1: MajorProgram Dialog */}
      <MajorProgramDialog
        open={programDialogOpen}
        onOpenChange={setProgramDialogOpen}
        majorProgram={selectedProgram}
        preselectedUnitId={unit.id}
      />

      {/* Tier 2: ProgramOffering Dialog */}
      {selectedProgramForOffering && (
        <ProgramOfferingDialog
          open={offeringDialogOpen}
          onOpenChange={setOfferingDialogOpen}
          majorProgram={selectedProgramForOffering}
          offering={selectedOffering}
        />
      )}

      {/* Tier 3: Academic Info Management */}
      {selectedOfferingForAcademicInfo && (
        <OfferingAcademicInfoManagement
          open={academicInfoManagementOpen}
          onOpenChange={setAcademicInfoManagementOpen}
          offering={selectedOfferingForAcademicInfo}
        />
      )}

      {/* Delete Program Confirmation */}
      <AlertDialog open={deleteProgramConfirmOpen} onOpenChange={setDeleteProgramConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa chương trình</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa chương trình{" "}
              <strong>&quot;{programToDelete?.name}&quot;</strong>?
              <br />
              <br />
              <span className="font-medium text-error-600">
                Cảnh báo: Tất cả loại hình đào tạo và thông tin tuyển sinh liên quan sẽ bị xóa theo!
              </span>
              <br />
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeleteProgram}
              className="bg-error-600 hover:bg-error-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Offering Confirmation */}
      <AlertDialog open={deleteOfferingConfirmOpen} onOpenChange={setDeleteOfferingConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa loại hình</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa loại hình{" "}
              <strong>&quot;{offeringToDelete?.offering_type}&quot;</strong>?
              <br />
              <br />
              <span className="font-medium text-error-600">
                Cảnh báo: Tất cả thông tin tuyển sinh liên quan sẽ bị xóa theo!
              </span>
              <br />
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeleteOffering}
              className="bg-error-600 hover:bg-error-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
