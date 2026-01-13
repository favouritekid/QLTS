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

export function MajorProgramPanel() {
  const { data = [], isLoading } = useMajorPrograms();
  const { data: units = [] } = useOrganizationUnits();
  const createMutation = useCreateMajorProgram();
  const updateMutation = useUpdateMajorProgram();
  const deleteMutation = useDeleteMajorProgram();

  const COLUMNS: CRUDTableColumn<MajorProgram>[] = [
    { 
      key: "code", 
      header: "Mã ngành", 
      width: "120px" 
    },
    { key: "degree_level", header: "Trình độ", width: "120px" },
    { key: "name", header: "Tên chương trình" },
    {
      key: "is_heavy",
      header: "Nặng nhọc/Độc hại",
      width: "140px",
      render: (item) => (
        <span className={item.is_heavy ? "text-amber-600 font-medium" : "text-muted-foreground"}>
          {item.is_heavy ? "Có" : "Không"}
        </span>
      )
    },
    {
      key: "quota",
      header: "Tổng chỉ tiêu",
      width: "120px",
      render: (item) => {
        const total = item.offerings?.reduce((acc, off) => {
          const latestInfo = off.academic_info_history?.[0];
          return acc + (latestInfo?.annual_admission_quota || 0);
        }, 0) || 0;
        
        if (total === 0) return <span className="text-muted-foreground text-xs">—</span>;
        return <span className="font-medium">{total}</span>;
      }
    },
    {
      key: "unit_id",
      header: "Đơn vị quản lý",
      width: "200px",
      render: (item) => {
        const unit = units.find((u: any) => u.id === item.unit_id);
        if (!unit) return <span className="text-muted-foreground text-xs">—</span>;
        return <span className="text-sm">{unit.name}</span>;
      },
    },
    { key: "display_order", header: "STT", width: "80px" },
    { key: "is_active", header: "Trạng thái", width: "100px" },
  ];

  const handleCreate = async (formData: BaseFormData) => {
    // Ensure numeric types
    const payload = {
      ...formData,
      unit_id: parseInt(formData.unit_id?.toString() || "0"),
      display_order: parseInt(formData.display_order?.toString() || "1"),
      is_heavy: !!formData.is_heavy,
      code: formData.code || formData.major_code,
    };
    await createMutation.mutateAsync(payload as any);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    const payload = {
      ...formData,
      unit_id: parseInt(formData.unit_id?.toString() || "0"),
      display_order: parseInt(formData.display_order?.toString() || "1"),
      is_heavy: !!formData.is_heavy,
    };
    await updateMutation.mutateAsync({ id, data: payload as any });
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
          <Label htmlFor="code">
            Mã ngành <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={formData.code || formData.major_code || ""}
            onChange={(e) => setFormData({ ...formData, code: e.target.value, major_code: e.target.value })}
            placeholder="vd: 6480201, 7340101"
            disabled={isEdit}
            required
          />
          <p className="text-xs text-muted-foreground">
            Mã ngành chính thức theo Bộ GD&ĐT (không thể thay đổi sau khi tạo)
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="degree_level">
              Trình độ đào tạo <span className="text-destructive">*</span>
            </Label>
            <Select
              value={formData.degree_level?.toString() || "Cao đẳng"}
              onValueChange={(value) => setFormData({ ...formData, degree_level: value })}
            >
              <SelectTrigger id="degree_level">
                <SelectValue placeholder="Chọn trình độ" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Cao đẳng">Cao đẳng</SelectItem>
                <SelectItem value="Trung cấp">Trung cấp</SelectItem>
                <SelectItem value="Sơ cấp">Sơ cấp</SelectItem>
                <SelectItem value="Đại học">Đại học</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-end pb-2">
            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="is_heavy"
                checked={!!formData.is_heavy}
                onChange={(e) => setFormData({ ...formData, is_heavy: e.target.checked })}
                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <Label htmlFor="is_heavy" className="cursor-pointer">
                Ngành nặng nhọc, độc hại
              </Label>
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="name">
            Tên chương trình <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="vd: Cao đẳng Công nghệ Thông tin"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Mô tả</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Mô tả ngắn gọn về ngành học"
            rows={2}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="unit_id">Đơn vị quản lý <span className="text-destructive">*</span></Label>
          <Select
            value={formData.unit_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, unit_id: parseInt(value) })
            }
          >
            <SelectTrigger id="unit_id">
              <SelectValue placeholder="Chọn khoa/bộ môn quản lý" />
            </SelectTrigger>
            <SelectContent>
              {units.map((unit: { id: number; name: string; code: string }) => (
                <SelectItem key={unit.id} value={unit.id.toString()}>
                  {unit.name} ({unit.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Khoa hoặc bộ môn trực tiếp quản lý chuyên môn của ngành này
          </p>
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
      </div>
    );
  };

  const initialFormData = () => ({
    code: "",
    major_code: "",
    degree_level: "Cao đẳng",
    name: "",
    description: "",
    unit_id: null,
    is_heavy: false,
    display_order: data.length + 1,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Chương trình đào tạo</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý danh mục các ngành, nghề đào tạo (CNTT, Kinh tế, Kỹ thuật...)
        </p>
      </div>

      <CRUDTable
        title="Ngành đào tạo"
        description="Danh sách các ngành đào tạo của nhà trường"
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
