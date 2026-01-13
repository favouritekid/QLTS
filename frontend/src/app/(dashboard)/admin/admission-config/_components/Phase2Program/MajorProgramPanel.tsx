/**
 * MajorProgramPanel Component
 *
 * Phase 2.1: Major Program Management
 * CRUD interface for major programs (IT, Business, etc.)
 * With organization unit selection
 */

"use client";

import { GraduationCap } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useMajorPrograms,
  useCreateMajorProgram,
  useUpdateMajorProgram,
  useDeleteMajorProgram,
} from "@/hooks/admissions/useProgramData";
import { useOrganizationUnits } from "@/hooks/admissions/useMasterData";
import type { MajorProgram, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<MajorProgram>[] = [
  { key: "major_code", header: "Major Code", width: "150px" },
  { key: "name", header: "Program Name" },
  {
    key: "organization_unit_id",
    header: "Unit",
    width: "200px",
    render: (item) => {
      if (!item.organization_unit_id) return "—";
      return <span className="text-sm">Unit #{item.organization_unit_id}</span>;
    },
  },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function MajorProgramPanel() {
  const { data = [], isLoading } = useMajorPrograms();
  const { data: units = [] } = useOrganizationUnits();
  const createMutation = useCreateMajorProgram();
  const updateMutation = useUpdateMajorProgram();
  const deleteMutation = useDeleteMajorProgram();

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
    item: MajorProgram | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="major_code">
            Major Code <span className="text-destructive">*</span>
          </Label>
          <Input
            id="major_code"
            value={formData.major_code || formData.code || ""}
            onChange={(e) => setFormData({ ...formData, major_code: e.target.value, code: e.target.value })}
            placeholder="e.g., 6480201, 7340101"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Official major code from Ministry of Education (cannot be changed after creation)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Program Name <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g., Cao đẳng Công nghệ Thông tin, Cử nhân Kinh doanh"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description of this major program"
            rows={3}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="organization_unit_id">Organization Unit</Label>
          <Select
            value={formData.organization_unit_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, organization_unit_id: parseInt(value) })
            }
          >
            <SelectTrigger id="organization_unit_id">
              <SelectValue placeholder="Select unit (optional)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">None</SelectItem>
              {units.map((unit: { id: number; name: string; code: string }) => (
                <SelectItem key={unit.id} value={unit.id.toString()}>
                  {unit.name} ({unit.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The department or faculty that manages this program
          </p>
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
    major_code: "",
    code: "",
    name: "",
    description: "",
    organization_unit_id: null,
    display_order: data.length + 1,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Major Programs</h1>
        <p className="text-muted-foreground mt-2">
          Manage academic programs and majors (IT, Business, Engineering, etc.)
        </p>
      </div>

      <CRUDTable
        title="Major Program"
        description="Academic programs offered by your institution"
        icon={<GraduationCap className="h-5 w-5 text-primary" />}
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
