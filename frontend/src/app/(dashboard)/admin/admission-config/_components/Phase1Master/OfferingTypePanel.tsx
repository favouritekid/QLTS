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
import { Textarea } from "@/components/ui/textarea";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useOfferingTypes,
  useCreateOfferingType,
  useUpdateOfferingType,
  useDeleteOfferingType,
} from "@/hooks/admissions/useMasterData";
import type { OfferingType, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<OfferingType>[] = [
  { key: "code", header: "Code", width: "150px" },
  { key: "name", header: "Name" },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function OfferingTypePanel() {
  const { data = [], isLoading } = useOfferingTypes();
  const createMutation = useCreateOfferingType();
  const updateMutation = useUpdateOfferingType();
  const deleteMutation = useDeleteOfferingType();

  const handleCreate = async (formData: BaseFormData) => {
    // Transform to match backend ConfigOfferingTypeCreate schema
    const payload = {
      code: formData.code,
      name: formData.name,
      display_order: formData.display_order || 0,
      is_active: formData.is_active !== undefined ? formData.is_active : true,
    };
    await createMutation.mutateAsync(payload as any);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    // Transform to match backend ConfigOfferingTypeUpdate schema
    const payload = {
      code: formData.code,
      name: formData.name,
      display_order: formData.display_order,
      is_active: formData.is_active,
    };
    await updateMutation.mutateAsync({ id, data: payload as any });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: OfferingType | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Code <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="e.g., chinh_quy, lien_thong, vlvh"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Unique identifier (cannot be changed after creation)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Name <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g., Chính quy, Liên thông, Vừa làm vừa học"
            required
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
          <p className="text-xs text-muted-foreground">
            Controls the order in dropdowns and listings
          </p>
        </div>
      </div>
    );
  };

  const initialFormData = () => ({
    code: "",
    name: "",
    display_order: data.length + 1,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Offering Types</h1>
        <p className="text-muted-foreground mt-2">
          Define the types of program offerings (Regular, Part-time, etc.)
        </p>
      </div>

      <CRUDTable
        title="Offering Type"
        description="Types of program offerings (Regular, Part-time, Distance learning)"
        icon={<Layers className="h-5 w-5 text-primary" />}
        columns={COLUMNS}
        data={data}
        isLoading={isLoading}
        onCreate={handleCreate}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        renderForm={renderForm}
        initialFormData={initialFormData}
      />
    </div>
  );
}
