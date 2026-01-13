/**
 * ProgramOfferingPanel Component
 *
 * Phase 2.2: Program Offering Management
 * CRUD interface for program offerings (combinations of major + offering type)
 * Example: "IT Program - Full-time", "Business Program - Part-time"
 */

"use client";

import { BookOpen } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CRUDTable } from "../shared/CRUDTable";
import type { ProgramOffering, CRUDTableColumn, BaseFormData } from "../shared/types";
import {
  useProgramOfferings,
  useCreateProgramOffering,
  useUpdateProgramOffering,
  useDeleteProgramOffering,
} from "@/hooks/admissions/useProgramData";
import { useMajorPrograms } from "@/hooks/admissions/useProgramData";
import { useOfferingTypes } from "@/hooks/admissions/useMasterData";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<ProgramOffering>[] = [
  { key: "code", header: "Code", width: "150px" },
  { key: "name", header: "Offering Name" },
  {
    key: "major_program_id",
    header: "Major Program",
    width: "200px",
    render: (item) => {
      if (!item.major_program_id) return "—";
      return <span className="text-sm">Major #{item.major_program_id}</span>;
    },
  },
  {
    key: "offering_type_id",
    header: "Offering Type",
    width: "200px",
    render: (item) => {
      if (!item.offering_type_id) return "—";
      return <span className="text-sm">Type #{item.offering_type_id}</span>;
    },
  },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function ProgramOfferingPanel() {
  const { data = [], isLoading } = useProgramOfferings();
  const { data: majors = [] } = useMajorPrograms();
  const { data: offeringTypes = [] } = useOfferingTypes();
  const createMutation = useCreateProgramOffering();
  const updateMutation = useUpdateProgramOffering();
  const deleteMutation = useDeleteProgramOffering();

  // Enhance columns with actual names from loaded data
  const enhancedColumns: CRUDTableColumn<ProgramOffering>[] = COLUMNS.map((col) => {
    if (col.key === "major_program_id") {
      return {
        ...col,
        render: (item: ProgramOffering) => {
          const major = majors.find((m: { id: number; name: string; major_code: string }) => m.id === item.major_program_id);
          if (!major) return <span className="text-muted-foreground">—</span>;
          return (
            <span className="text-sm font-medium">
              {major.name}
              <span className="text-muted-foreground ml-1">({major.major_code})</span>
            </span>
          );
        },
      };
    }
    if (col.key === "offering_type_id") {
      return {
        ...col,
        render: (item: ProgramOffering) => {
          const type = offeringTypes.find((t: { id: number; name: string; code: string }) => t.id === item.offering_type_id);
          if (!type) return <span className="text-muted-foreground">—</span>;
          return (
            <span className="text-sm">
              {type.name}
              <span className="text-muted-foreground ml-1">({type.code})</span>
            </span>
          );
        },
      };
    }
    return col;
  });

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
    item: ProgramOffering | null,
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
            placeholder="e.g., IT_CHINH_QUY, BUS_LIEN_THONG"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Unique identifier for this offering (cannot be changed after creation)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="major_program_id">
            Major Program <span className="text-destructive">*</span>
          </Label>
          <Select
            value={formData.major_program_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, major_program_id: parseInt(value) })
            }
          >
            <SelectTrigger id="major_program_id">
              <SelectValue placeholder="Select major program" />
            </SelectTrigger>
            <SelectContent>
              {majors.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  No major programs available. Please create one first.
                </div>
              )}
              {majors.map((major: { id: number; name: string; major_code: string }) => (
                <SelectItem key={major.id} value={major.id.toString()}>
                  {major.name} ({major.major_code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The academic program (e.g., IT, Business, Engineering)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offering_type_id">
            Offering Type <span className="text-destructive">*</span>
          </Label>
          <Select
            value={formData.offering_type_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, offering_type_id: parseInt(value) })
            }
          >
            <SelectTrigger id="offering_type_id">
              <SelectValue placeholder="Select offering type" />
            </SelectTrigger>
            <SelectContent>
              {offeringTypes.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  No offering types available. Please create one first.
                </div>
              )}
              {offeringTypes.map((type: { id: number; name: string; code: string }) => (
                <SelectItem key={type.id} value={type.id.toString()}>
                  {type.name} ({type.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The study mode (e.g., Full-time, Part-time, Distance learning)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Offering Name <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g., Công nghệ Thông tin - Chính quy"
            required
          />
          <p className="text-xs text-muted-foreground">
            Display name for this offering (usually Major + Type combination)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description of this program offering"
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
        </div>
      </div>
    );
  };

  const initialFormData = () => ({
    code: "",
    name: "",
    description: "",
    major_program_id: null,
    offering_type_id: null,
    display_order: data.length + 1,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Program Offerings</h1>
        <p className="text-muted-foreground mt-2">
          Manage program offerings by combining major programs with offering types
        </p>
      </div>

      {/* Warning if dependencies are missing */}
      {(majors.length === 0 || offeringTypes.length === 0) && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800 font-medium">
            Prerequisites Required
          </p>
          <p className="text-sm text-yellow-700 mt-1">
            {majors.length === 0 && "No major programs found. Please create major programs first in Phase 2.1."}
            {majors.length === 0 && offeringTypes.length === 0 && " Also, "}
            {offeringTypes.length === 0 && "No offering types found. Please create offering types in Phase 1.2."}
          </p>
        </div>
      )}

      <CRUDTable
        title="Program Offering"
        description="Combinations of major programs and offering types"
        icon={<BookOpen className="h-5 w-5 text-primary" />}
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
