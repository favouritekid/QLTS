/**
 * PathWizard Component
 *
 * Phase 3: Admission Path Creation/Editing Wizard
 * Simplified form for creating and editing admission paths
 *
 * Future enhancement: Multi-step wizard with:
 * - Step 1: Basic info (method selection)
 * - Step 2: Criteria configuration
 * - Step 3: Document requirements
 * - Step 4: Review and activate
 */

"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ChevronLeft, Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import {
  useAdmissionPath,
  useCreateAdmissionPath,
  useUpdateAdmissionPath,
} from "@/hooks/admissions/useAdmissionPaths";
import { useAdmissionMethods } from "@/hooks/admissions/useMasterData";
import type { SelectionContext, Phase3View, AdmissionMethod } from "../shared/types";
import type { AxiosError } from "axios";

// ============================================
// TYPES
// ============================================

interface PathWizardProps {
  context: SelectionContext;
  pathId?: number;
  onNavigate: (view: Phase3View) => void;
}

// ============================================
// COMPONENT
// ============================================

export function PathWizard({ context, pathId, onNavigate }: PathWizardProps) {
  const isEditMode = !!pathId;

  // Fetch data
  const { data: path, isLoading: loadingPath } = useAdmissionPath(pathId);
  const { data: methods = [], isLoading: loadingMethods } = useAdmissionMethods();
  const createMutation = useCreateAdmissionPath();
  const updateMutation = useUpdateAdmissionPath();

  // Initialize form state
  const [displayName, setDisplayName] = useState("");
  const [selectedMethodId, setSelectedMethodId] = useState<number | null>(null);
  const [displayOrder, setDisplayOrder] = useState(1);

  // Sync form state when path data loads (edit mode)
  useEffect(() => {
    if (isEditMode && path) {
      setDisplayName(path.display_name || "");
      setSelectedMethodId(path.admission_method?.id || null);
      setDisplayOrder(path.display_order || 1);
    }
  }, [isEditMode, path]);

  // Handle save
  const handleSave = async () => {
    if (!selectedMethodId) {
      toast.error("Vui lòng chọn phương thức tuyển sinh");
      return;
    }

    try {
      if (isEditMode && pathId) {
        await updateMutation.mutateAsync({
          pathId,
          data: {
            display_name: displayName || undefined,
            display_order: displayOrder,
          },
        });
        toast.success("Cập nhật đợt tuyển sinh thành công");
      } else {
        await createMutation.mutateAsync({
          academic_info_id: context.academicInfoId,
          admission_method_id: selectedMethodId,
          display_name: displayName || undefined,
          display_order: displayOrder,
        });
        toast.success("Tạo đợt tuyển sinh thành công");
      }

      // Navigate back to list
      onNavigate({ type: "list" });
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      toast.error(axiosError.response?.data?.detail || "Lưu thất bại");
    }
  };

  // Handle back
  const handleBack = () => {
    onNavigate({ type: "list" });
  };

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const isLoading = (isEditMode && loadingPath) || loadingMethods;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Button variant="ghost" size="sm" onClick={handleBack}>
            <ChevronLeft className="h-4 w-4 mr-1" />
            Quay lại Danh sách
          </Button>
        </div>
        <h1 className="text-3xl font-bold">
          {isEditMode ? "Cập nhật Đợt Tuyển sinh" : "Thêm mới Đợt Tuyển sinh"}
        </h1>
        <p className="text-muted-foreground mt-2">
          Năm học {context.academicYear}
        </p>
      </div>

      {/* Form Card */}
      <Card>
        <CardHeader>
          <CardTitle>Thông tin Cơ bản</CardTitle>
          <CardDescription>
            Cấu hình phương thức và hiển thị
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : (
            <div className="space-y-6">
              {/* Admission Method */}
              <div className="space-y-2">
                <Label htmlFor="method">
                  Phương thức Tuyển sinh <span className="text-destructive">*</span>
                </Label>
                <Select
                  value={selectedMethodId?.toString() || ""}
                  onValueChange={(value) => setSelectedMethodId(parseInt(value))}
                  disabled={isEditMode} // Cannot change method in edit mode
                >
                  <SelectTrigger id="method">
                    <SelectValue placeholder="Chọn phương thức" />
                  </SelectTrigger>
                  <SelectContent>
                    {methods.map((method: AdmissionMethod) => (
                      <SelectItem key={method.id} value={method.id.toString()}>
                        {method.name}
                        <span className="text-muted-foreground ml-2">({method.code})</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {isEditMode && (
                  <p className="text-xs text-muted-foreground">
                    Không thể thay đổi phương thức sau khi tạo
                  </p>
                )}
              </div>

              {/* Display Name */}
              <div className="space-y-2">
                <Label htmlFor="displayName">Tên hiển thị (Tùy chọn)</Label>
                <Input
                  id="displayName"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Để trống để dùng tên phương thức mặc định"
                />
                <p className="text-xs text-muted-foreground">
                  Tên hiển thị riêng (vd: &quot;Xét học bạ THPT - Khối A&quot;)
                </p>
              </div>

              {/* Display Order */}
              <div className="space-y-2">
                <Label htmlFor="displayOrder">Thứ tự hiển thị</Label>
                <Input
                  id="displayOrder"
                  type="number"
                  value={displayOrder}
                  onChange={(e) => setDisplayOrder(parseInt(e.target.value) || 1)}
                  min={1}
                />
                <p className="text-xs text-muted-foreground">
                  Thứ tự hiển thị cho thí sinh
                </p>
              </div>

              {/* Info Box */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm text-blue-900 font-medium mb-2">
                  Sau khi tạo đợt tuyển sinh:
                </p>
                <ul className="text-sm text-blue-800 space-y-1">
                  <li>• Cấu hình tiêu chí xét tuyển (Điểm chuẩn, GPA)</li>
                  <li>• Cấu hình hồ sơ yêu cầu</li>
                  <li>• Kích hoạt để nhận hồ sơ</li>
                </ul>
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-4">
                <Button variant="outline" onClick={handleBack} disabled={isSaving}>
                  Hủy
                </Button>
                <Button onClick={handleSave} disabled={isSaving}>
                  {isSaving ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Đang lưu...
                    </>
                  ) : (
                    <>
                      <Save className="h-4 w-4 mr-2" />
                      {isEditMode ? "Cập nhật" : "Tạo Đợt"}
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Future Enhancement Note */}
      {isEditMode && path && (
        <Card className="border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle className="text-amber-900">Các bước tiếp theo</CardTitle>
            <CardDescription className="text-amber-800">
              Cần cấu hình thêm trước khi kích hoạt
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm text-amber-900">
              {!path.criteria && (
                <p>• Cấu hình tiêu chí xét tuyển (điểm chuẩn, điểm sàn)</p>
              )}
              <p>• Cấu hình danh mục hồ sơ</p>
              {path.validation_errors && path.validation_errors.length > 0 && (
                <div className="mt-4 space-y-1">
                  <p className="font-medium">Vấn đề hiện tại:</p>
                  {path.validation_errors.map((error, idx) => (
                    <p key={idx}>• {error}</p>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
