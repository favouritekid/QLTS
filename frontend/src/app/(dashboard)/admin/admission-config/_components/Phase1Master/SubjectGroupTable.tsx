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
import type { 
  SubjectGroup, 
  CRUDTableColumn, 
  SubjectGroupCreate,
  SubjectGroupUpdate,
  SubjectGroupFormValues 
} from "../shared/types";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<SubjectGroup>[] = [
  { key: "code", header: "Mã tổ hợp", width: "120px" },
  { key: "name", header: "Tên tổ hợp" },
  {
    key: "subjects",
    header: "Môn học",
    render: (item) => {
      if (!item.subjects || item.subjects.length === 0) {
        return <span className="text-muted-foreground text-sm">Chưa có môn học</span>;
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
              +{item.subjects.length - 3} môn khác
            </Badge>
          )}
        </div>
      );
    },
  },
  { key: "display_order", header: "Thứ tự", width: "80px" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function SubjectGroupTable() {
  const { data = [], isLoading } = useSubjectGroups();
  const createMutation = useCreateSubjectGroup();
  const updateMutation = useUpdateSubjectGroup();
  const deleteMutation = useDeleteSubjectGroup();

  const handleCreate = async (formData: SubjectGroupFormValues) => {
    const payload: SubjectGroupCreate = {
      code: formData.code,
      name: formData.name,
      description: formData.description,
      display_order: formData.display_order,
      is_active: formData.is_active,
    };
    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: SubjectGroupFormValues) => {
    const payload: SubjectGroupUpdate = {
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
    item: SubjectGroup | null,
    formData: SubjectGroupFormValues,
    setFormData: (data: SubjectGroupFormValues) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã tổ hợp <span className="text-destructive">*</span>
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
            Mã định danh duy nhất (ví dụ: A00, A01) - không thể thay đổi sau khi tạo
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Tên tổ hợp <span className="text-destructive">*</span>
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
        </div>

        {isEdit && item && item.subjects && item.subjects.length > 0 && (
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <Label className="text-sm font-semibold mb-2 block">Các môn trong tổ hợp:</Label>
            <div className="flex flex-wrap gap-2">
              {item.subjects.map((subject) => (
                <Badge key={subject.code} variant="secondary">
                  {subject.position}. {subject.name_vi}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Sử dụng tab &quot;Phân môn vào tổ hợp&quot; để thêm hoặc bớt môn học
            </p>
          </div>
        )}
      </div>
    );
  };

  const initialFormData = (): SubjectGroupFormValues => ({
    code: "",
    name: "",
    description: "",
    display_order: data.length + 1,
    is_active: true,
  });

  const mapItemToFormData = (item: SubjectGroup): SubjectGroupFormValues => {
    return {
      code: item.code,
      name: item.name,
      description: item.description || "",
      display_order: item.display_order,
      is_active: item.is_active,
    };
  };

  return (
    <CRUDTable<SubjectGroup, SubjectGroupFormValues>
      title="Tổ hợp môn"
      description="Các tổ hợp môn xét tuyển (A00, A01, D01...)"
      icon={<Users className="h-5 w-5 text-primary" />}
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
  );
}
