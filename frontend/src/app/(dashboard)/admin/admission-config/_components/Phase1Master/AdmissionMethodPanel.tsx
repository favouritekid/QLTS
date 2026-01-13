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
  { key: "code", header: "Code", width: "150px" },
  { key: "name", header: "Name" },
  {
    key: "requires_gpa",
    header: "Requires GPA",
    width: "120px",
    render: (item) => (item.requires_gpa ? "✓ Yes" : "✗ No"),
  },
  {
    key: "requires_subject_scores",
    header: "Requires Scores",
    width: "140px",
    render: (item) => (item.requires_subject_scores ? "✓ Yes" : "✗ No"),
  },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
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
            Code <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="e.g., hoc_ba, thpt_qg, dgnl"
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
            placeholder="e.g., Xét học bạ THPT, Xét điểm thi THPT QG"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description of this admission method"
            rows={3}
          />
        </div>

        <div className="space-y-4 border-t pt-4">
          <Label className="text-base font-semibold">Requirements</Label>

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
                Requires GPA (Grade Point Average)
              </Label>
              <p className="text-xs text-muted-foreground">
                Check if this method requires high school GPA scores
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
                Requires Subject Scores
              </Label>
              <p className="text-xs text-muted-foreground">
                Check if this method requires specific subject scores (Math, Physics, etc.)
              </p>
            </div>
          </div>
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
    requires_gpa: false,
    requires_subject_scores: false,
    display_order: data.length + 1,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Admission Methods</h1>
        <p className="text-muted-foreground mt-2">
          Define the methods students can use to apply (High school GPA, National exam, etc.)
        </p>
      </div>

      <CRUDTable
        title="Admission Method"
        description="Ways students can apply for admission"
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
