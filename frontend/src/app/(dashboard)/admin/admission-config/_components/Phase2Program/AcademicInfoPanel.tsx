/**
 * AcademicInfoPanel Component
 *
 * Phase 2.3: Offering Academic Info Management
 * Configure yearly academic details for program offerings:
 * - Academic year
 * - Tuition fees
 * - Admission quota
 * - Publication status
 */

"use client";

import { useState, useMemo, useCallback } from "react";
import { Calendar, Pencil, Trash2, Plus, Loader2, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  useOfferingAcademicInfos,
  useCreateOfferingAcademicInfo,
  useUpdateOfferingAcademicInfo,
  useDeleteOfferingAcademicInfo,
} from "@/hooks/admissions/useProgramData";
import { useProgramOfferings } from "@/hooks/admissions/useProgramData";
import { useAdmissionConfigState } from "@/hooks/admissions/useAdmissionConfigState";
import type {
  OfferingAcademicInfo,
  OfferingAcademicInfoCreate,
  OfferingAcademicInfoUpdate,
  ProgramOffering
} from "../shared/types";

// ============================================
// TYPES
// ============================================

interface AcademicInfoFormData {
  offering_id: number | null;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published: boolean;
}

// ============================================
// COMPONENT
// ============================================

export function AcademicInfoPanel() {
  const { data = [], isLoading } = useOfferingAcademicInfos();
  const { data: offerings = [] } = useProgramOfferings();
  const createMutation = useCreateOfferingAcademicInfo();
  const updateMutation = useUpdateOfferingAcademicInfo();
  const deleteMutation = useDeleteOfferingAcademicInfo();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [editingItem, setEditingItem] = useState<OfferingAcademicInfo | null>(null);
  const [formData, setFormData] = useState<AcademicInfoFormData>({
    offering_id: null,
    academic_year: new Date().getFullYear(),
    tuition_fee_per_year: 0,
    annual_admission_quota: 0,
    is_published: false,
  });

  const resetForm = () => {
    setFormData({
      offering_id: null,
      academic_year: new Date().getFullYear(),
      tuition_fee_per_year: 0,
      annual_admission_quota: 0,
      is_published: false,
    });
    setEditingItem(null);
  };

  const openCreateDialog = () => {
    resetForm();
    setIsDialogOpen(true);
  };

  const openEditDialog = (item: OfferingAcademicInfo) => {
    setEditingItem(item);
    setFormData({
      offering_id: item.offering_id,
      academic_year: item.academic_year,
      tuition_fee_per_year: item.tuition_fee_per_year || 0,
      annual_admission_quota: item.annual_admission_quota || 0,
      is_published: item.is_published,
    });
    setIsDialogOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.offering_id) {
      toast.error("Please select a program offering");
      return;
    }
    if (!formData.academic_year || formData.academic_year < 2000) {
      toast.error("Please enter a valid academic year");
      return;
    }
    if (formData.annual_admission_quota && formData.annual_admission_quota < 0) {
      toast.error("Admission quota cannot be negative");
      return;
    }

    // Check for duplicate year + offering combination (only on create)
    if (!editingItem) {
      const duplicate = data.find(
        (item: OfferingAcademicInfo) =>
          item.offering_id === formData.offering_id &&
          item.academic_year === formData.academic_year
      );
      if (duplicate) {
        toast.error(
          `Academic info for year ${formData.academic_year} already exists for this offering`
        );
        return;
      }
    }

    try {
      if (editingItem) {
        const updateData: OfferingAcademicInfoUpdate = {
          tuition_fee_per_year: formData.tuition_fee_per_year,
          annual_admission_quota: formData.annual_admission_quota,
          is_published: formData.is_published,
        };
        await updateMutation.mutateAsync({
          id: editingItem.id,
          data: updateData,
        });
      } else {
        // Validate required fields
        if (!formData.offering_id) {
          toast.error("Vui lòng chọn chương trình tuyển sinh");
          return;
        }

        const createData: OfferingAcademicInfoCreate = {
          offering_id: formData.offering_id,
          academic_year: formData.academic_year,
          tuition_fee_per_year: formData.tuition_fee_per_year,
          annual_admission_quota: formData.annual_admission_quota,
          is_published: formData.is_published,
        };
        await createMutation.mutateAsync(createData);
      }
      setIsDialogOpen(false);
      resetForm();
    } catch {
      // Error handling is done in the mutation hooks
    }
  };

  const handleDelete = (id: number) => {
    setPendingDeleteId(id);
    setDeleteConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (pendingDeleteId !== null) {
      try {
        await deleteMutation.mutateAsync(pendingDeleteId);
      } catch {
        // Error handling is done in the mutation hooks
      } finally {
        setDeleteConfirmOpen(false);
        setPendingDeleteId(null);
      }
    }
  };

  const getOfferingDisplay = useCallback((offeringId: number) => {
    const offering = offerings.find((o: ProgramOffering) => o.id === offeringId);

    if (!offering) {
      return {
        full: `Offering #${offeringId}`,
        programName: `Offering #${offeringId}`,
        programCode: undefined,
        offeringType: "Unknown",
        degreeLevel: undefined,
      };
    }

    const programName = offering.program?.name || `Program #${offering.program_id}`;
    const offeringType = offering.offering_type;
    const degreeLevel = offering.program?.degree_level;

    return {
      full: `${programName} - ${offeringType}`,
      programName,
      programCode: offering.program?.code,
      offeringType,
      degreeLevel,
    };
  }, [offerings]);

  const formatCurrency = (amount: number | undefined) => {
    if (amount == null) return "—";
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: "VND",
    }).format(amount);
  };

  // Sort data by program name, then by academic year (descending)
  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => {
      const displayA = getOfferingDisplay(a.offering_id);
      const displayB = getOfferingDisplay(b.offering_id);

      // First sort by program name
      const nameCompare = displayA.programName.localeCompare(displayB.programName);
      if (nameCompare !== 0) return nameCompare;

      // Then by offering type
      const typeCompare = displayA.offeringType.localeCompare(displayB.offeringType);
      if (typeCompare !== 0) return typeCompare;

      // Finally by academic year (descending - newest first)
      return b.academic_year - a.academic_year;
    });
  }, [data, getOfferingDisplay]);

  const { navigate } = useAdmissionConfigState();

  const handleNavigate = (item: OfferingAcademicInfo, action: 'view' | 'add') => {
    const offering = offerings.find((o: ProgramOffering) => o.id === item.offering_id);
    if (!offering) return;

    navigate({
      type: 'phase3',
      context: {
        academicYear: item.academic_year,
        majorProgramId: offering.program_id,
        offeringId: item.offering_id,
        academicInfoId: item.id
      },
      view: { type: action === 'view' ? 'list' : 'wizard' }
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold font-display">Thông tin Tuyển sinh chi tiết</h1>
        <p className="text-muted-foreground mt-2">
          Cấu hình chi tiết theo năm học (Học phí, Chỉ tiêu...)
        </p>
      </div>

      {/* Warning if no offerings */}
      {offerings.length === 0 && (
        <div className="bg-warning-50 border border-warning-200 rounded-lg p-4">
          <p className="text-sm text-warning-800 font-medium">
            Yêu cầu dữ liệu
          </p>
          <p className="text-sm text-warning-700 mt-1">
            Chưa có chương trình tuyển sinh nào. Vui lòng tạo chương trình trước tại Bước 2.2.
          </p>
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Calendar className="h-5 w-5 text-primary" />
              <div>
                <CardTitle>Thông tin chi tiết</CardTitle>
                <CardDescription>
                  Cấu hình theo năm học cho các chương trình
                </CardDescription>
              </div>
            </div>
            <Button onClick={openCreateDialog} disabled={offerings.length === 0}>
              <Plus className="h-4 w-4 mr-2" />
              Thêm mới
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : data.length === 0 ? (
            <div className="text-center py-12">
              <Calendar className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">
                Chưa có thông tin nào được cấu hình
              </p>
              <p className="text-sm text-muted-foreground mt-1">
                Nhấn &quot;Thêm mới&quot; để tạo cấu hình cho năm học
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-32">Mã ngành</TableHead>
                  <TableHead>Tên chương trình</TableHead>
                  <TableHead className="w-32">Trình độ</TableHead>
                  <TableHead className="w-32">Hệ</TableHead>
                  <TableHead className="w-28">Năm học</TableHead>
                  <TableHead className="w-36">Học phí</TableHead>
                  <TableHead className="w-24">Chỉ tiêu</TableHead>
                  <TableHead className="w-24">Trạng thái</TableHead>
                  <TableHead className="w-28 text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedData.map((item: OfferingAcademicInfo) => {
                  const display = getOfferingDisplay(item.offering_id);
                  return (
                    <TableRow key={item.id}>
                      <TableCell>
                        {display.programCode ? (
                          <code className="bg-muted rounded px-2 py-1 text-xs font-mono">
                            {display.programCode}
                          </code>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                      {getOfferingDisplay(item.offering_id).full}
                    </TableCell>
                      <TableCell>
                        <span className="text-sm">{display.degreeLevel || "—"}</span>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm">{display.offeringType}</span>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{item.academic_year}</Badge>
                      </TableCell>
                      <TableCell className="text-sm">
                        {formatCurrency(item.tuition_fee_per_year)}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm font-medium">
                          {item.annual_admission_quota ?? "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        {item.is_published ? (
                          <Badge className="bg-success-500">Đã công bố</Badge>
                        ) : (
                          <Badge variant="secondary">Nháp</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          {/* Phase 3 Navigation Actions */}
                          {item.admission_status === 'CONFIGURED' && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-info-600 hover:text-info-700 hover:bg-info-50"
                              onClick={() => handleNavigate(item, 'view')}
                              title="Xem cấu hình tuyển sinh"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                          )}
                          {item.admission_status === 'READY' && (
                             <Button
                              variant="ghost"
                              size="sm"
                              className="text-success-600 hover:text-success-700 hover:bg-success-50"
                              onClick={() => handleNavigate(item, 'add')}
                              title="Thêm cấu hình tuyển sinh"
                            >
                              <Plus className="h-4 w-4" />
                            </Button>
                          )}

                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEditDialog(item)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(item.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create/Edit Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {editingItem ? "Cập nhật Thông tin" : "Thêm mới Thông tin"}
            </DialogTitle>
            <DialogDescription>
              Cấu hình chi tiết cho năm học của chương trình tuyển sinh
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="offering_id">
                  Chương trình tuyển sinh <span className="text-destructive">*</span>
                </Label>
                <Select
                  value={formData.offering_id?.toString() || ""}
                  onValueChange={(value) =>
                    setFormData({ ...formData, offering_id: parseInt(value) })
                  }
                  disabled={!!editingItem}
                >
                  <SelectTrigger id="offering_id">
                    <SelectValue placeholder="Chọn chương trình tuyển sinh" />
                  </SelectTrigger>
                  <SelectContent>
                    {offerings.map((offering: ProgramOffering) => {
                      const programName = offering.program?.name || `Program #${offering.program_id}`;
                      const programCode = offering.program?.code || "";
                      const offeringType = offering.offering_type;
                      const degreeLevel = offering.program?.degree_level || "";

                      const displayText = `${programName} - ${offeringType}${programCode ? ` (${programCode})` : ""} • ${degreeLevel}`;

                      return (
                        <SelectItem key={offering.id} value={offering.id.toString()}>
                          {displayText}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {editingItem && (
                  <p className="text-xs text-muted-foreground">
                    Không thể thay đổi chương trình sau khi tạo
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="academic_year">
                  Năm học <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="academic_year"
                  type="number"
                  value={formData.academic_year || ""}
                  onChange={(e) =>
                    setFormData({ ...formData, academic_year: e.target.value ? parseInt(e.target.value) : 0 })
                  }
                  placeholder="vd: 2024"
                  min={2000}
                  max={2100}
                  disabled={!!editingItem}
                  required
                />
                {editingItem && (
                  <p className="text-xs text-muted-foreground">
                    Không thể thay đổi năm sau khi tạo
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="tuition_fee_per_year">
                  Học phí / Năm (VND)
                </Label>
                <Input
                  id="tuition_fee_per_year"
                  type="number"
                  value={formData.tuition_fee_per_year || ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      tuition_fee_per_year: e.target.value ? parseInt(e.target.value) : undefined,
                    })
                  }
                  placeholder="e.g., 25000000"
                  min={0}
                />
                <p className="text-xs text-muted-foreground">
                  Mức học phí niêm yết theo năm (VNĐ)
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="annual_admission_quota">
                  Chỉ tiêu tuyển sinh
                </Label>
                <Input
                  id="annual_admission_quota"
                  type="number"
                  value={formData.annual_admission_quota || ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      annual_admission_quota: e.target.value ? parseInt(e.target.value) : undefined,
                    })
                  }
                  placeholder="e.g., 100"
                  min={0}
                />
                <p className="text-xs text-muted-foreground">
                  Số lượng sinh viên tối đa cho năm học này
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="is_published"
                  checked={formData.is_published || false}
                  onCheckedChange={(checked) =>
                    setFormData({ ...formData, is_published: checked === true })
                  }
                />
                <Label
                  htmlFor="is_published"
                  className="text-sm font-normal cursor-pointer"
                >
                  Công khai thông tin này (Thí sinh có thể nhìn thấy)
                </Label>
              </div>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                Hủy
              </Button>
              <Button
                type="submit"
                disabled={
                  createMutation.isPending ||
                  updateMutation.isPending
                }
              >
                {(createMutation.isPending || updateMutation.isPending) && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                {editingItem ? "Cập nhật" : "Thêm mới"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa thông tin này? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleConfirmDelete}
            >
              Xóa
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
