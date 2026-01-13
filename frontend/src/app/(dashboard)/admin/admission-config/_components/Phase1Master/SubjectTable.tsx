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
  { key: "code", header: "Code", width: "120px" },
  { key: "name_vi", header: "Name (Vietnamese)" },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
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
            Subject Code <span className="text-destructive">*</span>
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
            Unique identifier (cannot be changed after creation)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name_vi">
            Subject Name (Vietnamese) <span className="text-destructive">*</span>
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
          <Label htmlFor="name_en">Subject Name (English)</Label>
          <Input
            id="name_en"
            value={formData.name_en || ""}
            onChange={(e) => setFormData({ ...formData, name_en: e.target.value })}
            placeholder="e.g., Mathematics, Physics, Chemistry"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="display_order">Display Order</Label>
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

  return (
    <CRUDTable
      title="Subject"
      description="Individual subjects like Math, Physics, Chemistry, etc."
      icon={<BookOpen className="h-5 w-5 text-primary" />}
      columns={COLUMNS}
      data={data}
      isLoading={isLoading}
      onCreate={handleCreate}
      onUpdate={handleUpdate}
      onDelete={handleDelete}
      renderForm={renderForm}
      initialFormData={initialFormData}
    />
  );
}
