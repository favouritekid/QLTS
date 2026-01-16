/**
 * DocumentTypePanel Component
 *
 * Phase 1.4: Document Type Management
 * CRUD interface for document types (Transcripts, ID cards, etc.)
 */

"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SharedDocumentConfigPanel } from "./SharedDocumentConfigPanel";
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
import type { 
  DocumentType, 
  CRUDTableColumn, 
  DocumentTypeCreate,
  DocumentTypeUpdate,
  DocumentTypeFormValues 
} from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<DocumentType>[] = [
  { key: "code", header: "Mã", width: "150px" },
  { key: "name", header: "Tên loại giấy tờ" },
  { key: "description", header: "Mô tả" },
  { key: "display_order", header: "Thứ tự", width: "80px" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

export function DocumentTypePanel() {
  const { data = [], isLoading } = useDocumentTypes();
  const createMutation = useCreateDocumentType();
  const updateMutation = useUpdateDocumentType();
  const deleteMutation = useDeleteDocumentType();

  const handleCreate = async (formData: DocumentTypeFormValues) => {
    const payload: DocumentTypeCreate = {
      code: formData.code,
      name: formData.name,
      description: formData.description,
      display_order: formData.display_order,
      is_active: formData.is_active,
    };
    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: DocumentTypeFormValues) => {
    const payload: DocumentTypeUpdate = {
      name: formData.name,
      description: formData.description,
      display_order: formData.display_order,
      is_active: formData.is_active,
    };
    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: DocumentType | null,
    formData: DocumentTypeFormValues,
    setFormData: (data: DocumentTypeFormValues) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã loại giấy tờ <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value })}
            placeholder="ví dụ: hoc_ba_thpt, bang_tn, cccd"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Mã định danh duy nhất (không thể thay đổi sau khi tạo)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Tên loại giấy tờ <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="ví dụ: Học bạ THPT, Bằng tốt nghiệp, CCCD/CMND"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Mô tả</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Mô tả tóm tắt (ví dụ: Bản sao học bạ 3 năm THPT)"
            rows={3}
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
            Quy định thứ tự hiển thị trong danh sách hồ sơ
          </p>
        </div>
      </div>
    );
  };

  const initialFormData = (): DocumentTypeFormValues => ({
    code: "",
    name: "",
    description: "",
    display_order: data.length + 1,
    is_active: true,
  });

  const mapItemToFormData = (item: DocumentType): DocumentTypeFormValues => {
    return {
      code: item.code,
      name: item.name,
      description: item.description || "",
      display_order: item.display_order,
      is_active: item.is_active,
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Quản lý Hồ sơ</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý danh mục loại giấy tờ và cấu hình hồ sơ dùng chung
        </p>
      </div>

      <Tabs defaultValue="types" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="types">Danh mục Loại giấy tờ</TabsTrigger>
          <TabsTrigger value="shared">Cấu hình Hồ sơ chung</TabsTrigger>
        </TabsList>
        
        <TabsContent value="types">
          <CRUDTable<DocumentType, DocumentTypeFormValues>
            title="Loại Giấy tờ"
            description="Các loại giấy tờ cần thiết cho hồ sơ xét tuyển"
            icon={<FileText className="h-5 w-5 text-primary" />}
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
        </TabsContent>
        
        <TabsContent value="shared">
          <SharedDocumentConfigPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
