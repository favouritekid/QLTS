/**
 * OfferingTypePanel Component
 *
 * Phase 1.2: Offering Type Management
 * CRUD interface for offering types (Regular, Part-time, etc.)
 */

"use client";

import { Layers } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useOfferingTypes,
  useCreateOfferingType,
  useUpdateOfferingType,
  useDeleteOfferingType,
} from "@/hooks/admissions/useMasterData";
import type { 
  OfferingType, 
  CRUDTableColumn, 
  OfferingTypeCreate,
  OfferingTypeUpdate,
  OfferingTypeFormValues 
} from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<OfferingType>[] = [
  { key: "code", header: "Mã", width: "150px" },
  { key: "name", header: "Tên loại hình" },
  { key: "display_order", header: "Thứ tự", width: "80px" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function OfferingTypePanel() {
  const { data = [], isLoading } = useOfferingTypes();
  const createMutation = useCreateOfferingType();
  const updateMutation = useUpdateOfferingType();
  const deleteMutation = useDeleteOfferingType();

  const handleCreate = async (formData: OfferingTypeFormValues) => {
    // Transform to match backend ConfigOfferingTypeCreate schema
    const payload: OfferingTypeCreate = {
      code: formData.code,
      name: formData.name,
      display_order: formData.display_order || 0,
      is_active: formData.is_active,
    };
    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: OfferingTypeFormValues) => {
    // Transform to match backend ConfigOfferingTypeUpdate schema
    const payload: OfferingTypeUpdate = {
      name: formData.name,
      display_order: formData.display_order,
      is_active: formData.is_active,
    };
    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: OfferingType | null,
    formData: OfferingTypeFormValues,
    setFormData: (data: OfferingTypeFormValues) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã loại hình <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="ví dụ: chinh_quy, lien_thong, vlvh"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Mã định danh duy nhất (không thể thay đổi sau khi tạo)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Tên loại hình <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="ví dụ: Chính quy, Liên thông, Vừa làm vừa học"
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
          <p className="text-xs text-muted-foreground">
            Quy định thứ tự hiển thị trong danh sách và dropdown
          </p>
        </div>
      </div>
    );
  };

  const initialFormData = (): OfferingTypeFormValues => ({
    code: "",
    name: "",
    display_order: data.length + 1,
    is_active: true,
  });

  const mapItemToFormData = (item: OfferingType): OfferingTypeFormValues => {
    return {
      code: item.code,
      name: item.name,
      display_order: item.display_order,
      is_active: item.is_active,
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Loại hình Đào tạo</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý các loại hình đào tạo (Chính quy, Vừa làm vừa học, Liên thông...)
        </p>
      </div>

      <CRUDTable<OfferingType, OfferingTypeFormValues>
        title="Loại hình"
        description="Các hình thức đào tạo của nhà trường"
        icon={<Layers className="h-5 w-5 text-primary" />}
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
