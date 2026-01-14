/**
 * DocumentTypePanel Component
 *
 * Phase 1.4: Document Type Management
 * CRUD interface for document types (Transcripts, ID cards, etc.)
 */

"use client";

import { FileText } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useDocumentTypes,
  useCreateDocumentType,
  useUpdateDocumentType,
  useDeleteDocumentType,
} from "@/hooks/admissions/useMasterData";
import type { DocumentType, CRUDTableColumn, BaseFormData } from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<DocumentType>[] = [
  { key: "code", header: "Code", width: "150px" },
  { key: "name", header: "Name" },
  { key: "description", header: "Description" },
  { key: "display_order", header: "Order", width: "80px" },
  { key: "is_active", header: "Status", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function DocumentTypePanel() {
  const { data = [], isLoading } = useDocumentTypes();
  const createMutation = useCreateDocumentType();
  const updateMutation = useUpdateDocumentType();
  const deleteMutation = useDeleteDocumentType();

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
    item: DocumentType | null,
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
            placeholder="e.g., hoc_ba_thpt, bang_tn, cccd"
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
            placeholder="e.g., Học bạ THPT, Bằng tốt nghiệp, CCCD/CMND"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Optional description (e.g., Bản sao học bạ 3 năm THPT)"
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
            Controls the order in document checklists
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
        <h1 className="text-3xl font-bold">Document Types</h1>
        <p className="text-muted-foreground mt-2">
          Define the types of documents students must submit (Transcripts, ID cards, etc.)
        </p>
      </div>

      <CRUDTable<DocumentType>
        title="Document Type"
        description="Types of documents required for admission applications"
        icon={<FileText className="h-5 w-5 text-primary" />}
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
