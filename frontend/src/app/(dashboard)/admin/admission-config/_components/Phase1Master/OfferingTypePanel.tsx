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
  { key: "description", header: "Description" },
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
    await createMutation.mutateAsync(formData as unknown as Parameters<typeof createMutation.mutateAsync>[0]);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    await updateMutation.mutateAsync({ id, data: formData as unknown as Parameters<typeof updateMutation.mutateAsync>[0]["data"] });
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
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description of this offering type"
            rows={3}
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
    description: "",
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
