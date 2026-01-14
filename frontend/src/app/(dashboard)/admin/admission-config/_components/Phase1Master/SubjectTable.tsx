/**
 * SubjectTable Component
 *
 * CRUD table for subjects (Math, Physics, Chemistry, etc.)
 */

"use client";

import { BookOpen } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useSubjects,
  useCreateSubject,
  useUpdateSubject,
  useDeleteSubject,
} from "@/hooks/admissions/useMasterData";
import type { Subject, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<Subject>[] = [
  { key: "code", header: "Mã môn", width: "120px" },
  { key: "name_vi", header: "Tên môn (Tiếng Việt)" },
  { key: "display_order", header: "Thứ tự", width: "80px" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function SubjectTable() {
  const { data = [], isLoading } = useSubjects();
  const createMutation = useCreateSubject();
  const updateMutation = useUpdateSubject();
  const deleteMutation = useDeleteSubject();

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
    item: Subject | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã môn <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="e.g., TOAN, VAT_LY, HOA_HOC"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Mã định danh duy nhất (không thể thay đổi sau khi tạo)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name_vi">
            Tên môn (Tiếng Việt) <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name_vi"
            value={formData.name_vi || ""}
            onChange={(e) => setFormData({ ...formData, name_vi: e.target.value })}
            placeholder="e.g., Toán, Vật lý, Hóa học"
            required
          />
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
    name_vi: "",
    name_en: "",
    display_order: data.length + 1,
  });

  const mapItemToFormData = (item: Subject) => ({
    code: item.code,
    name_vi: item.name_vi,
    name_en: item.name_en || "",
    display_order: item.display_order,
    is_active: item.is_active,
  });

  return (
    <CRUDTable
      title="Môn học"
      description="Danh sách các môn học (Toán, Lý, Hóa...)"
      icon={<BookOpen className="h-5 w-5 text-primary" />}
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
  );
}
