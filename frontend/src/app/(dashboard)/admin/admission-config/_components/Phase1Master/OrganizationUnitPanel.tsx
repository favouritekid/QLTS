/**
 * OrganizationUnitPanel Component
 *
 * Phase 1.1: Organization Unit Management
 * CRUD interface for organization units (Departments, Faculties, etc.)
 */

"use client";

import { Building2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useOrganizationUnits,
  useCreateOrganizationUnit,
  useUpdateOrganizationUnit,
  useDeleteOrganizationUnit,
} from "@/hooks/admissions/useMasterData";
import type { OrganizationUnit, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

// Valid organization unit types from backend
const ORGANIZATION_UNIT_TYPES = [
  "Trường",
  "Phòng ban",
  "Trung tâm",
  "Khoa",
  "Tổ",
  "Bộ môn",
];

const COLUMNS: CRUDTableColumn<OrganizationUnit>[] = [
  { key: "name", header: "Name" },
  { key: "type", header: "Type", width: "120px" },
  { key: "parent_id", header: "Parent Unit", width: "150px" },
  { key: "description", header: "Description" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function OrganizationUnitPanel() {
  const { data = [], isLoading } = useOrganizationUnits();
  const createMutation = useCreateOrganizationUnit();
  const updateMutation = useUpdateOrganizationUnit();
  const deleteMutation = useDeleteOrganizationUnit();

  // Enhance columns to show parent unit name
  const enhancedColumns: CRUDTableColumn<OrganizationUnit>[] = COLUMNS.map((col) => {
    if (col.key === "parent_id") {
      return {
        ...col,
        render: (item: OrganizationUnit) => {
          if (!item.parent_id) return <span className="text-muted-foreground">—</span>;
          const parent = data.find((u) => u.id === item.parent_id);
          return parent ? (
            <span className="text-sm">{parent.name}</span>
          ) : (
            <span className="text-sm text-muted-foreground">Unit #{item.parent_id}</span>
          );
        },
      };
    }
    return col;
  });

  const handleCreate = async (formData: BaseFormData) => {
    // Transform formData to match backend OrganizationUnitCreate schema
    const payload = {
      name: formData.name,
      type: (formData as any).type, // Required by backend
      description: formData.description || null,
      parent_id: (formData as any).parent_id || null,
    };
    await createMutation.mutateAsync(payload as any);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    // Transform formData to match backend OrganizationUnitUpdate schema
    const payload = {
      name: formData.name,
      type: (formData as any).type,
      description: formData.description || null,
      parent_id: (formData as any).parent_id || null,
    };
    await updateMutation.mutateAsync({ id, data: payload as any });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: OrganizationUnit | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">
            Name <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g., Faculty of Information Technology"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="type">
            Unit Type <span className="text-destructive">*</span>
          </Label>
          <Select
            value={(formData as any).type || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, type: value } as any)
            }
          >
            <SelectTrigger id="type">
              <SelectValue placeholder="Select unit type" />
            </SelectTrigger>
            <SelectContent>
              {ORGANIZATION_UNIT_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The type of organizational unit (e.g., Faculty, Department)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="parent_id">Parent Unit (Optional)</Label>
          <Select
            value={(formData as any).parent_id?.toString() || "__none__"}
            onValueChange={(value) =>
              setFormData({
                ...formData,
                parent_id: value === "__none__" ? null : parseInt(value)
              } as any)
            }
          >
            <SelectTrigger id="parent_id">
              <SelectValue placeholder="None (top-level unit)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">None (top-level unit)</SelectItem>
              {data
                .filter((unit) => unit.id !== item?.id) // Prevent self-parenting
                .map((unit) => (
                  <SelectItem key={unit.id} value={unit.id.toString()}>
                    {unit.name} ({unit.type})
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The parent organizational unit (leave empty for top-level units)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description"
            rows={3}
          />
        </div>
      </div>
    );
  };

  const initialFormData = (): any => ({
    name: "",
    type: "", // Required by backend
    description: "",
    parent_id: null,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Organization Units</h1>
        <p className="text-muted-foreground mt-2">
          Manage departments, faculties, and other organizational units
        </p>
      </div>

      <CRUDTable
        title="Organization Unit"
        description="Departments, faculties, and other organizational units"
        icon={<Building2 className="h-5 w-5 text-primary" />}
        columns={enhancedColumns}
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
