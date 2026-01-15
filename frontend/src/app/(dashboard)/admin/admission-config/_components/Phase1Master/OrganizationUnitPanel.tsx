/**
 * OrganizationUnitPanel Component
 *
 * Phase 1.1: Organization Unit Management
 * CRUD interface for organization units (Departments, Faculties, etc.)
 */

"use client";

import { useMemo } from "react";
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
import { SmartUnitSelector } from "@/components/common/selectors/SmartUnitSelector";
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
  { key: "name", header: "Tên đơn vị" },
  { key: "type", header: "Loại hình", width: "120px" },
  { key: "parent_id", header: "Đơn vị cấp trên", width: "150px" },
  { key: "description", header: "Mô tả" },
  { key: "is_active", header: "Trạng thái", width: "100px" },
];

// ============================================
// COMPONENT
// ============================================

export function OrganizationUnitPanel() {
  const { data = [], isLoading } = useOrganizationUnits();
  const createMutation = useCreateOrganizationUnit();
  const updateMutation = useUpdateOrganizationUnit();
  const deleteMutation = useDeleteOrganizationUnit();

  // ============================================
  // HIERARCHY HELPERS
  // ============================================

  // ============================================
  // HIERARCHY HELPERS
  // ============================================

  // Helper to flatten nested tree
  const flattenTree = (units: OrganizationUnit[]): (OrganizationUnit & { level: number })[] => {
    const result: (OrganizationUnit & { level: number })[] = [];

    // Sort by name for display consistency
    const sortedUnits = [...units].sort((a, b) => a.name.localeCompare(b.name));

    sortedUnits.forEach((unit) => {
      // Add current unit
      // Since backend returns nested structure, we calculate level during recursive flattening
      // But for the root call, we need a starting level (0)
      // Actually, flattening logic needs to carry level.
      
      const traverse = (node: OrganizationUnit, level: number) => {
        result.push({ ...node, level });
        
        if (node.children && node.children.length > 0) {
           // Sort children
           const sortedChildren = [...node.children].sort((a, b) => a.name.localeCompare(b.name));
           sortedChildren.forEach(child => traverse(child, level + 1));
        }
      };

      traverse(unit, 0);
    });

    return result;
  };

  // Memoize sorted data
  const sortedData = useMemo(() => flattenTree(data), [data]);

  // Create flat lookup for finding parents
  const allUnitsFlat = useMemo(() => {
    const flatten = (units: OrganizationUnit[]): OrganizationUnit[] => {
      let result: OrganizationUnit[] = [];
      units.forEach((unit) => {
        result.push(unit);
        if (unit.children && unit.children.length > 0) {
          result = result.concat(flatten(unit.children));
        }
      });
      return result;
    };
    return flatten(data);
  }, [data]);

  // Enhance columns to show parent unit name and indentation
  const enhancedColumns: CRUDTableColumn<OrganizationUnit & { level: number }>[] = [
    {
      key: "name",
      header: "Name",
      render: (item: OrganizationUnit) => {
        // Cast to any to access level added by buildHierarchy
        const level = (item as any).level || 0;
        return (
          <div style={{ paddingLeft: `${level * 24}px` }} className="flex items-center">
            {level > 0 && <span className="text-muted-foreground mr-2">└─</span>}
            <span className={level === 0 ? "font-medium" : ""}>{item.name}</span>
          </div>
        );
      },
    },
    { key: "type", header: "Type", width: "120px" },
    {
      key: "parent_id",
      header: "Parent Unit",
      width: "200px",
      render: (item: OrganizationUnit) => {
        if (!item.parent_id) return <span className="text-muted-foreground">—</span>;
        const parent = allUnitsFlat.find((u: OrganizationUnit) => u.id === item.parent_id);
        return parent ? (
          <span className="text-sm">{parent.name}</span>
        ) : (
          <span className="text-sm text-muted-foreground">Đơn vị #{item.parent_id}</span>
        );
      },
    },
    { key: "description", header: "Description" },
    { key: "is_active", header: "Status", width: "100px" },
  ];

  const mapItemToFormData = (item: OrganizationUnit): BaseFormData => {
    const formData: any = {
      name: item.name,
      description: item.description || "",
      is_active: item.is_active,
      type: item.type,
      parent_id: item.parent_id,
    };
    return formData;
  };

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
            Tên đơn vị <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="Ví dụ: Khoa Công nghệ Thông tin"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="type">
            Loại hình <span className="text-destructive">*</span>
          </Label>
          <Select
            value={(formData as any).type || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, type: value } as any)
            }
          >
            <SelectTrigger id="type">
              <SelectValue placeholder="Chọn loại đơn vị" />
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
            Loại hình tổ chức (ví dụ: Khoa, Phòng ban)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="parent_id">Đơn vị cấp trên (Tùy chọn)</Label>
          <SmartUnitSelector
            value={(formData as any).parent_id?.toString()}
            onChange={(value) =>
              setFormData({
                ...formData,
                parent_id: value ? parseInt(value) : null
              } as any)
            }
            placeholder="Không có (Đơn vị cấp cao nhất)"
            allowNone={true}
            noneLabel="Không có (Đơn vị cấp cao nhất)"
            excludeUnitId={item?.id} // Prevent self-parenting and circular dependencies
            variant="combobox"
            activeOnly={false} // Show inactive units for editing existing relationships
          />
          <p className="text-xs text-muted-foreground">
            Đơn vị cấp trên trực tiếp (để trống nếu là đơn vị cấp cao nhất)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Mô tả</Label>
          <Textarea
            id="description"
            value={formData.description || ""}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Mô tả tóm tắt về đơn vị"
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
        <h1 className="text-3xl font-bold">Quản lý Đơn vị Tổ chức</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý danh sách các khoa, phòng ban và đơn vị trực thuộc
        </p>
      </div>

      <CRUDTable<OrganizationUnit & { level: number }>
        title="Đơn vị"
        description="Khoa, phòng ban và các đơn vị khác"
        icon={<Building2 className="h-5 w-5 text-primary" />}
        columns={enhancedColumns}
        data={sortedData}
        isLoading={isLoading}
        onCreate={handleCreate}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        renderForm={renderForm}
        initialFormData={initialFormData}
        mapItemToFormData={mapItemToFormData}
      />
    </div>
  );
}
