// src/components/admin/organization/MajorListTab.tsx
"use client";

import { useState } from "react";
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
  Plus,
  Search,
  MoreVertical,
  Edit,
  Trash2,
  BookOpen,
  GraduationCap,
  ChevronRight,
  ChevronDown,
  Layers,
  CalendarCheck,
} from "lucide-react";
import {
  useOrganizationUnits,
  useDeleteMajorProgram,
  useDeleteProgramOffering,
} from "@/hooks/useOrganization";
import { MajorProgramDialog } from "./MajorProgramDialog";
import { ProgramOfferingDialog } from "./ProgramOfferingDialog";
import { OfferingAcademicInfoManagement } from "./OfferingAcademicInfoManagement";
import type {
  OrganizationUnit,
  MajorProgram,
  ProgramOffering,
} from "@/types/organization.types";

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
  const [selectedProgramForOffering, setSelectedProgramForOffering] =
    useState<MajorProgram | null>(null);
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
  const { data: allUnits = [], isLoading } = useOrganizationUnits();

  // Get programs to display
  const isRootUnit = unit.parent_id === null;
  const allPrograms = isRootUnit
    ? collectAllMajorPrograms(unit)
    : unit.major_programs || [];

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
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold">Chương trình đào tạo</h3>
            <p className="text-sm text-muted-foreground">
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
            <Plus className="h-4 w-4 mr-2" />
            Tạo chương trình
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
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
          <div className="p-6 space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : filteredPrograms.length === 0 ? (
          // Empty state
          <div className="p-12 text-center">
            <GraduationCap className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" />
            <h4 className="text-lg font-medium mb-2">
              {searchQuery ? "Không tìm thấy chương trình" : "Chưa có chương trình"}
            </h4>
            <p className="text-sm text-muted-foreground mb-4">
              {searchQuery
                ? "Thử tìm kiếm với từ khóa khác"
                : "Tạo chương trình đào tạo đầu tiên cho đơn vị này"}
            </p>
            {!searchQuery && (
              <Button onClick={handleCreateProgram} size="sm">
                <Plus className="h-4 w-4 mr-2" />
                Tạo chương trình
              </Button>
            )}
          </div>
        ) : (
          // Programs list (3-tier tree)
          <div className="p-6 space-y-3">
            {filteredPrograms.map((program) => {
              const isExpanded = expandedPrograms.has(program.id);
              const hasOfferings = program.offerings && program.offerings.length > 0;

              return (
                <div
                  key={program.id}
                  className="border rounded-lg overflow-hidden bg-card"
                >
                  {/* TIER 1: MajorProgram Header */}
                  <div className="p-4 bg-muted/30">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3 flex-1">
                        {/* Expand/Collapse button */}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleProgramExpand(program.id)}
                          className="h-8 w-8 p-0"
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

                        <GraduationCap className="h-5 w-5 text-primary" />

                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <h4 className="font-semibold">{program.name}</h4>
                            <Badge variant="outline" className="text-xs">
                              {program.degree_level}
                            </Badge>
                            {!program.is_active && (
                              <Badge variant="destructive" className="text-xs">
                                Ngưng hoạt động
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-4 mt-1">
                            <code className="text-xs bg-muted px-2 py-0.5 rounded font-mono">
                              {program.code}
                            </code>
                            <span className="text-xs text-muted-foreground">
                              {hasOfferings
                                ? `${program.offerings.length} loại hình`
                                : "Chưa có loại hình"}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Actions for Tier 1 */}
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleCreateOffering(program)}
                        >
                          <Plus className="h-4 w-4 mr-1" />
                          Thêm loại hình
                        </Button>

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm">
                              <MoreVertical className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => handleEditProgram(program)}>
                              <Edit className="h-4 w-4 mr-2" />
                              Chỉnh sửa
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => handleDeleteProgramClick(program)}
                              className="text-red-600"
                            >
                              <Trash2 className="h-4 w-4 mr-2" />
                              Xóa
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  </div>

                  {/* TIER 2: ProgramOffering List (Expandable) */}
                  {isExpanded && hasOfferings && (
                    <div className="border-t">
                      {program.offerings.map((offering) => (
                        <div
                          key={offering.id}
                          className="p-4 border-b last:border-b-0 hover:bg-muted/20 transition-colors"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3 flex-1">
                              <div className="ml-10" /> {/* Indent */}
                              <Layers className="h-4 w-4 text-blue-500" />

                              <div className="flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium text-sm">
                                    {offering.offering_type}
                                  </span>
                                  {!offering.is_active && (
                                    <Badge variant="destructive" className="text-xs">
                                      Ngưng hoạt động
                                    </Badge>
                                  )}
                                </div>
                                <div className="flex items-center gap-4 mt-1">
                                  {offering.duration_semesters && (
                                    <span className="text-xs text-muted-foreground">
                                      {offering.duration_semesters} kỳ
                                    </span>
                                  )}
                                  {offering.total_credits && (
                                    <span className="text-xs text-muted-foreground">
                                      {offering.total_credits} tín chỉ
                                    </span>
                                  )}
                                  {offering.academic_info_history?.length > 0 && (
                                    <span className="text-xs text-muted-foreground">
                                      {offering.academic_info_history.length} năm học
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>

                            {/* Actions for Tier 2 */}
                            <div className="flex items-center gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleManageAcademicInfo(offering)}
                              >
                                <CalendarCheck className="h-4 w-4 mr-1" />
                                Thông tin tuyển sinh
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
                                    <Edit className="h-4 w-4 mr-2" />
                                    Chỉnh sửa
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onClick={() => handleDeleteOfferingClick(offering)}
                                    className="text-red-600"
                                  >
                                    <Trash2 className="h-4 w-4 mr-2" />
                                    Xóa
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
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
      <AlertDialog
        open={deleteProgramConfirmOpen}
        onOpenChange={setDeleteProgramConfirmOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa chương trình</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa chương trình{" "}
              <strong>&quot;{programToDelete?.name}&quot;</strong>?
              <br />
              <br />
              <span className="text-red-600 font-medium">
                Cảnh báo: Tất cả loại hình đào tạo và thông tin tuyển sinh liên quan sẽ
                bị xóa theo!
              </span>
              <br />
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeleteProgram}
              className="bg-red-600 hover:bg-red-700"
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Offering Confirmation */}
      <AlertDialog
        open={deleteOfferingConfirmOpen}
        onOpenChange={setDeleteOfferingConfirmOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa loại hình</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa loại hình{" "}
              <strong>&quot;{offeringToDelete?.offering_type}&quot;</strong>?
              <br />
              <br />
              <span className="text-red-600 font-medium">
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
