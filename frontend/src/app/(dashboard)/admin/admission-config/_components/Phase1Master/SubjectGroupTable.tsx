/**
 * SubjectGroupTable Component
 *
 * CRUD table for subject groups (A00, A01, D01, etc.)
 */

"use client";

import { Users } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useSubjectGroups,
  useCreateSubjectGroup,
  useUpdateSubjectGroup,
  useDeleteSubjectGroup,
} from "@/hooks/admissions/useMasterData";
import type { SubjectGroup, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<SubjectGroup>[] = [
  { key: "code", header: "Code", width: "120px" },
  { key: "name", header: "Name" },
  {
    key: "subjects",
    header: "Subjects",
    render: (item) => {
      if (!item.subjects || item.subjects.length === 0) {
        return <span className="text-muted-foreground text-sm">No subjects assigned</span>;
      }
      return (
        <div className="flex flex-wrap gap-1">
          {item.subjects.slice(0, 3).map((subject) => (
            <Badge key={subject.code} variant="secondary" className="text-xs">
              {subject.code}
            </Badge>
          ))}
          {item.subjects.length > 3 && (
            <Badge variant="outline" className="text-xs">
              +{item.subjects.length - 3} more
            </Badge>
          )}
        </div>
      );
    },
  },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function SubjectGroupTable() {
  const { data = [], isLoading } = useSubjectGroups();
  const createMutation = useCreateSubjectGroup();
  const updateMutation = useUpdateSubjectGroup();
  const deleteMutation = useDeleteSubjectGroup();

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
    item: SubjectGroup | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Group Code <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="e.g., A00, A01, D01, D07"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Unique identifier like A00, A01 (cannot be changed after creation)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Group Name <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g., Toán-Lý-Hóa, Toán-Văn-Anh"
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
        </div>

        {isEdit && item && item.subjects && item.subjects.length > 0 && (
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <Label className="text-sm font-semibold mb-2 block">Current Subjects:</Label>
            <div className="flex flex-wrap gap-2">
              {item.subjects.map((subject) => (
                <Badge key={subject.code} variant="secondary">
                  {subject.position}. {subject.name_vi}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Use the &quot;Group Assignment&quot; tab to add or remove subjects
            </p>
          </div>
        )}
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
    <CRUDTable
      title="Subject Group"
      description="Groups of subjects like A00 (Math-Physics-Chemistry), D01 (Math-Literature-English)"
      icon={<Users className="h-5 w-5 text-primary" />}
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
