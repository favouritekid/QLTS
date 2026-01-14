/**
 * AdmissionMethodPanel Component
 *
 * Phase 1.3: Admission Method Management
 * CRUD interface for admission methods (High school GPA, National exam, etc.)
 */

"use client";

import { GraduationCap } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useAdmissionMethods,
  useCreateAdmissionMethod,
  useUpdateAdmissionMethod,
  useDeleteAdmissionMethod,
} from "@/hooks/admissions/useMasterData";
import type { AdmissionMethod, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<AdmissionMethod>[] = [
  { key: "code", header: "Mã", width: "150px" },
  { key: "name", header: "Tên phương thức" },
  {
    key: "requires_gpa",
    header: "Xét GPA",
    width: "120px",
    render: (item) => (item.requires_gpa ? "✓ Có" : "✗ Không"),
  },
  {
    key: "requires_subject_scores",
    header: "Xét điểm môn",
    width: "140px",
    render: (item) => (item.requires_subject_scores ? "✓ Có" : "✗ Không"),
  },
  { key: "display_order", header: "Thứ tự", width: "80px" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function AdmissionMethodPanel() {
  const { data = [], isLoading } = useAdmissionMethods();
  const createMutation = useCreateAdmissionMethod();
  const updateMutation = useUpdateAdmissionMethod();
  const deleteMutation = useDeleteAdmissionMethod();

  const handleCreate = async (formData: BaseFormData) => {
    await createMutation.mutateAsync(formData as unknown as Parameters<typeof createMutation.mutateAsync>[0]);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    await updateMutation.mutateAsync({ id, data: formData as unknown as Parameters<typeof updateMutation.mutateAsync>[0]["data"] });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: AdmissionMethod | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã phương thức <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="ví dụ: hoc_ba, thpt_qg, dgnl"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Mã định danh duy nhất (không thể thay đổi sau khi tạo)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Tên phương thức <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="ví dụ: Xét học bạ THPT, Xét điểm thi THPT QG"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Mô tả</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Mô tả tóm tắt về phương thức tuyển sinh này"
            rows={3}
          />
        </div>

        <div className="space-y-4 border-t pt-4">
          <Label className="text-base font-semibold">Cấu hình Yêu cầu</Label>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="requires_gpa"
              checked={formData.requires_gpa || false}
              onCheckedChange={(checked) =>
                setFormData({ ...formData, requires_gpa: checked === true })
              }
            />
            <div className="grid gap-1.5 leading-none">
              <Label
                htmlFor="requires_gpa"
                className="text-sm font-normal cursor-pointer"
              >
                Yêu cầu điểm trung bình (GPA)
              </Label>
              <p className="text-xs text-muted-foreground">
                Chọn nếu phương thức này cần xét điểm GPA học bạ
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="requires_subject_scores"
              checked={formData.requires_subject_scores || false}
              onCheckedChange={(checked) =>
                setFormData({ ...formData, requires_subject_scores: checked === true })
              }
            />
            <div className="grid gap-1.5 leading-none">
              <Label
                htmlFor="requires_subject_scores"
                className="text-sm font-normal cursor-pointer"
              >
                Yêu cầu điểm môn học thành phần
              </Label>
              <p className="text-xs text-muted-foreground">
                Chọn nếu phương thức này cần xét điểm các môn học cụ thể
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="display_order">Thứ tự hiển thị</Label>
          <Input
            id="display_order"
            type="number"
            value={formData.display_order || 1}
            onChange={(e) =>
              setFormData({ ...formData, display_order: parseInt(e.target.value) })
            }
            min={1}
          />
        </div>
      </div>
    );
  };

  const initialFormData = () => ({
    code: "",
    name: "",
    description: "",
    requires_gpa: false,
    requires_subject_scores: false,
    display_order: data.length + 1,
  });

  const mapItemToFormData = (item: AdmissionMethod): BaseFormData => {
    return {
      code: item.code,
      name: item.name,
      description: item.description || "",
      display_order: item.display_order,
      is_active: item.is_active,
      requires_gpa: item.requires_gpa,
      requires_subject_scores: item.requires_subject_scores,
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Phương thức Tuyển sinh</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý các phương thức xét tuyển (Xét học bạ, Điểm thi THPT, Đánh giá năng lực...)
        </p>
      </div>

      <CRUDTable<AdmissionMethod>
        title="Phương thức"
        description="Các hình thức xét tuyển của nhà trường"
        icon={<GraduationCap className="h-5 w-5 text-primary" />}
        columns={COLUMNS}
        data={data}
        isLoading={isLoading}
        onCreate={handleCreate}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        renderForm={renderForm}
        initialFormData={initialFormData}
        mapItemToFormData={mapItemToFormData}
      />
    </div>
  );
}
