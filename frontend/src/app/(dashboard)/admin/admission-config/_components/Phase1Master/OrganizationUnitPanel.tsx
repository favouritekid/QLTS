/**
 * OrganizationUnitPanel Component
 *
 * Phase 1.1: Organization Unit Management
 * CRUD interface for organization units (Departments, Faculties, etc.)
 * 
 * Architecture: FRONTEND_ARCHITECTURE_V3.md
 * - FE renders backend state, NO business logic decisions
 * - Uses typed payloads instead of `any` casts
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
import type { 
  OrganizationUnit, 
  CRUDTableColumn, 
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
  OrganizationUnitFormValues
} from "../shared/types";

// ============================================
// TYPES
// ============================================

// Extended OrganizationUnit with level for tree rendering
type FlattenedOrgUnit = OrganizationUnit & { level: number };

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

  // Helper to flatten nested tree
  const flattenTree = (units: OrganizationUnit[]): FlattenedOrgUnit[] => {
    const result: FlattenedOrgUnit[] = [];

    // Sort by name for display consistency
    const sortedUnits = [...units].sort((a, b) => a.name.localeCompare(b.name));

    sortedUnits.forEach((unit) => {
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
  const enhancedColumns: CRUDTableColumn<FlattenedOrgUnit>[] = [
    {
      key: "name",
      header: "Name",
      render: (item: FlattenedOrgUnit) => {
        const level = item.level;
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
      render: (item: FlattenedOrgUnit) => {
        if (!item.parent_id) return <span className="text-muted-foreground">—</span>;
        const parent = allUnitsFlat.find((u) => u.id === item.parent_id);
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

  const mapItemToFormData = (item: OrganizationUnit): OrganizationUnitFormValues => {
    return {
      name: item.name,
      description: item.description || "",
      is_active: item.is_active,
      type: item.type,
      parent_id: item.parent_id || null,
    };
  };

  const handleCreate = async (formData: OrganizationUnitFormValues) => {
    const payload: OrganizationUnitCreate = {
      name: formData.name,
      type: formData.type,
      description: formData.description || null,
      parent_id: formData.parent_id || null,
    };
    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: OrganizationUnitFormValues) => {
    const payload: OrganizationUnitUpdate = {
      name: formData.name,
      type: formData.type,
      description: formData.description || null,
      parent_id: formData.parent_id ?? null,
      is_active: formData.is_active,
    };
    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: OrganizationUnit | null,
    formData: OrganizationUnitFormValues,
    setFormData: (data: OrganizationUnitFormValues) => void,
    _isEdit: boolean
  ) => {
    const updateForm = (updates: Partial<OrganizationUnitFormValues>) => {
      setFormData({ ...formData, ...updates });
    };

    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">
            Tên đơn vị <span className="text-destructive">*</span>
          </Label>
          <Input
            id="name"
            value={formData.name || ""}
            onChange={(e) => updateForm({ name: e.target.value })}
            placeholder="Ví dụ: Khoa Công nghệ Thông tin"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="type">
            Loại hình <span className="text-destructive">*</span>
          </Label>
          <Select
            value={formData.type || ""}
            onValueChange={(value) => updateForm({ type: value })}
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
            value={formData.parent_id?.toString()}
            onChange={(value) => updateForm({ parent_id: value ? parseInt(value) : null })}
            placeholder="Không có (Đơn vị cấp cao nhất)"
            allowNone={true}
            noneLabel="Không có (Đơn vị cấp cao nhất)"
            excludeUnitId={item?.id}
            variant="combobox"
            activeOnly={false}
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
            onChange={(e) => updateForm({ description: e.target.value })}
            placeholder="Mô tả tóm tắt về đơn vị"
            rows={3}
          />
        </div>
      </div>
    );
  };

  const initialFormData = (): OrganizationUnitFormValues => ({
    name: "",
    type: "",
    description: "",
    parent_id: null,
    is_active: true,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Quản lý Đơn vị Tổ chức</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý danh sách các khoa, phòng ban và đơn vị trực thuộc
        </p>
      </div>

      <CRUDTable<FlattenedOrgUnit, OrganizationUnitFormValues>
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
