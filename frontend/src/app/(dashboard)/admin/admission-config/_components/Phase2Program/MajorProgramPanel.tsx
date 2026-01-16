/**
 * MajorProgramPanel Component
 *
 * Phase 2.1: Major Program Management
 * CRUD interface for major programs (IT, Business, etc.)
 * With organization unit selection
 *
 * Architecture: FRONTEND_ARCHITECTURE_V3.md
 * - FE renders backend state, NO business logic decisions
 * - Uses typed payloads instead of `any` casts
 */

"use client";

import { useMemo } from "react";
import { GraduationCap } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SmartUnitSelector } from "@/components/common/selectors/SmartUnitSelector";
import { CRUDTable } from "../shared/CRUDTable";
import {
  useMajorPrograms,
  useCreateMajorProgram,
  useUpdateMajorProgram,
  useDeleteMajorProgram,
} from "@/hooks/admissions/useProgramData";
import { useOrganizationUnits } from "@/hooks/admissions/useMasterData";
import type { 
  MajorProgram, 
  CRUDTableColumn, 
  BaseFormData,
  MajorProgramCreate,
  MajorProgramUpdate,
  OrganizationUnit,
  ProgramOffering,
  OfferingAcademicInfo
} from "../shared/types";

// ============================================
// TYPES
// ============================================

// Extended MajorProgram for table display with group header support
interface DisplayMajorProgram extends MajorProgram {
  isGroupHeader?: boolean;
  groupLevel?: string;
}

// Extended form data type for major programs
interface MajorProgramFormData extends BaseFormData {
  code?: string;
  degree_level?: string;
  unit_id?: number | null;
  is_heavy?: boolean;
}

// ============================================
// COMPONENT
// ============================================

export function MajorProgramPanel() {
  const { data = [], isLoading } = useMajorPrograms();
  const { data: units = [] } = useOrganizationUnits();
  const createMutation = useCreateMajorProgram();
  const updateMutation = useUpdateMajorProgram();
  const deleteMutation = useDeleteMajorProgram();

  // Group and sort data by degree level
  const groupedData = useMemo(() => {
    const levelOrder = ["Đại học", "Cao đẳng", "Trung cấp", "Sơ cấp"];

    const grouped = data.reduce((acc: Record<string, MajorProgram[]>, program: MajorProgram) => {
      const level = program.degree_level || "Khác";
      if (!acc[level]) acc[level] = [];
      acc[level].push(program);
      return acc;
    }, {} as Record<string, MajorProgram[]>);

    Object.keys(grouped).forEach(level => {
      grouped[level].sort((a: MajorProgram, b: MajorProgram) => a.name.localeCompare(b.name));
    });

    return levelOrder
      .filter(level => grouped[level])
      .map(level => ({ level, programs: grouped[level] }))
      .concat(
        Object.keys(grouped)
          .filter(level => !levelOrder.includes(level))
          .map(level => ({ level, programs: grouped[level] }))
      );
  }, [data]);

  // Flatten grouped data for table display with level markers
  const flattenedData = useMemo((): DisplayMajorProgram[] => {
    const result: DisplayMajorProgram[] = [];

    groupedData.forEach((group, groupIndex) => {
      // Add group header marker with unique ID
      result.push({
        id: -1000 - groupIndex, // Negative ID to avoid conflicts with real IDs
        code: group.level,
        name: group.level,
        degree_level: group.level,
        unit_id: 0,
        is_active: true,
        is_heavy: false,
        isGroupHeader: true,
        groupLevel: group.level,
      });

      // Add programs in this group
      group.programs.forEach((program: MajorProgram) => {
        result.push(program);
      });
    });

    return result;
  }, [groupedData]);

  // Helper to find unit by ID
  const findUnit = (unitId: number): OrganizationUnit | undefined => {
    // Flatten units tree for lookup
    const flattenUnits = (items: OrganizationUnit[]): OrganizationUnit[] => {
      let result: OrganizationUnit[] = [];
      items.forEach(item => {
        result.push(item);
        if (item.children?.length) {
          result = result.concat(flattenUnits(item.children));
        }
      });
      return result;
    };
    return flattenUnits(units).find(u => u.id === unitId);
  };

  // Calculate total quota from offerings
  const calculateTotalQuota = (offerings?: ProgramOffering[]): number => {
    if (!offerings) return 0;
    return offerings.reduce((acc: number, off: ProgramOffering) => {
      const latestInfo: OfferingAcademicInfo | undefined = off.academic_info_history?.[0];
      return acc + (latestInfo?.annual_admission_quota || 0);
    }, 0);
  };

  const COLUMNS: CRUDTableColumn<DisplayMajorProgram>[] = [
    {
      key: "code",
      header: "Mã ngành",
      width: "120px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) {
          return (
            <div className="font-bold text-base text-primary py-1 col-span-full">
              {item.groupLevel}
            </div>
          );
        }
        return (
          <code className="bg-muted rounded px-2 py-1 text-xs font-mono">
            {item.code}
          </code>
        );
      }
    },
    {
      key: "degree_level",
      header: "Trình độ",
      width: "120px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        return item.degree_level;
      }
    },
    {
      key: "name",
      header: "Tên chương trình",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        return item.name;
      }
    },
    {
      key: "is_heavy",
      header: "Nặng nhọc/Độc hại",
      width: "140px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        return (
          <span className={item.is_heavy ? "text-amber-600 font-medium" : "text-muted-foreground"}>
            {item.is_heavy ? "Có" : "Không"}
          </span>
        );
      }
    },
    {
      key: "quota",
      header: "Tổng chỉ tiêu",
      width: "120px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        const total = calculateTotalQuota(item.offerings);
        if (total === 0) return <span className="text-muted-foreground text-xs">—</span>;
        return <span className="font-medium">{total}</span>;
      }
    },
    {
      key: "unit_id",
      header: "Đơn vị quản lý",
      width: "200px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        const unit = findUnit(item.unit_id);
        if (!unit) return <span className="text-muted-foreground text-xs">—</span>;
        return <span className="text-sm">{unit.name}</span>;
      },
    },
    {
      key: "is_active",
      header: "Trạng thái",
      width: "100px",
      render: (item: DisplayMajorProgram) => {
        if (item.isGroupHeader) return null;
        return item.is_active;
      }
    },
  ];

  const handleCreate = async (formData: BaseFormData) => {
    const mpFormData = formData as MajorProgramFormData;
    const payload: MajorProgramCreate = {
      code: mpFormData.code || "",
      name: mpFormData.name || "",
      degree_level: mpFormData.degree_level || "Cao đẳng",
      unit_id: mpFormData.unit_id || 0,
      is_heavy: !!mpFormData.is_heavy,
      is_active: mpFormData.is_active !== undefined ? mpFormData.is_active : true,
    };
    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    const mpFormData = formData as MajorProgramFormData;
    const payload: MajorProgramUpdate = {
      name: mpFormData.name,
      degree_level: mpFormData.degree_level,
      unit_id: mpFormData.unit_id ?? undefined,
      is_heavy: mpFormData.is_heavy,
      is_active: mpFormData.is_active,
    };
    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    _item: MajorProgram | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    const mpFormData = formData as MajorProgramFormData;
    
    const updateForm = (updates: Partial<MajorProgramFormData>) => {
      setFormData({ ...mpFormData, ...updates });
    };

    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="code">
            Mã ngành <span className="text-destructive">*</span>
          </Label>
          <Input
            id="code"
            value={mpFormData.code || ""}
            onChange={(e) => updateForm({ code: e.target.value })}
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
              value={mpFormData.degree_level || "Cao đẳng"}
              onValueChange={(value) => updateForm({ degree_level: value })}
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
                checked={!!mpFormData.is_heavy}
                onChange={(e) => updateForm({ is_heavy: e.target.checked })}
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
            value={mpFormData.name || ""}
            onChange={(e) => updateForm({ name: e.target.value })}
            placeholder="vd: Cao đẳng Công nghệ Thông tin"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="unit_id">Đơn vị quản lý <span className="text-destructive">*</span></Label>
          <SmartUnitSelector
            value={mpFormData.unit_id?.toString()}
            onChange={(value) => updateForm({ unit_id: value ? parseInt(value) : null })}
            placeholder="Chọn khoa/bộ môn quản lý"
            variant="combobox"
            filterTypes={["Khoa", "Bộ môn", "Trung tâm"]}
            activeOnly={true}
          />
          <p className="text-xs text-muted-foreground">
            Khoa hoặc bộ môn trực tiếp quản lý chuyên môn của ngành này
          </p>
        </div>
      </div>
    );
  };

  const initialFormData = (): MajorProgramFormData => ({
    code: "",
    degree_level: "Cao đẳng",
    name: "",
    unit_id: null,
    is_heavy: false,
  });

  const mapItemToFormData = (item: MajorProgram): MajorProgramFormData => {
    return {
      code: item.code,
      degree_level: item.degree_level,
      name: item.name,
      unit_id: item.unit_id,
      is_heavy: item.is_heavy,
      is_active: item.is_active,
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Chương trình đào tạo</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý danh mục các ngành, nghề đào tạo (CNTT, Kinh tế, Kỹ thuật...)
        </p>
      </div>

      <CRUDTable<DisplayMajorProgram>
        title="Ngành đào tạo"
        description="Danh sách các ngành đào tạo của nhà trường"
        icon={<GraduationCap className="h-5 w-5 text-primary" />}
        columns={COLUMNS}
        data={flattenedData}
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
