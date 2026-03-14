/**
 * ProgramOfferingPanel Component
 *
 * Phase 2.2: Program Offering Management
 * CRUD interface for program offerings (combinations of major + offering type)
 * Example: "IT Program - Full-time", "Business Program - Part-time"
 *
 * Architecture: FRONTEND_ARCHITECTURE_V3.md
 * - FE renders backend state, NO business logic decisions
 * - Uses typed payloads instead of `any` casts
 */

"use client";

import { BookOpen } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CRUDTable } from "../shared/CRUDTable";
import type { 
  ProgramOffering, 
  CRUDTableColumn, 
  ScoringRules,
  MajorProgram,
  OfferingType,
  ProgramOfferingCreate,
  ProgramOfferingUpdate,
  ProgramOfferingFormValues
} from "../shared/types";
import {
  useProgramOfferings,
  useCreateProgramOffering,
  useUpdateProgramOffering,
  useDeleteProgramOffering,
} from "@/hooks/admissions/useProgramData";
import { useMajorPrograms } from "@/hooks/admissions/useProgramData";
import { useOfferingTypes } from "@/hooks/admissions/useMasterData";

// ============================================
// TYPES
// ============================================

// Use ProgramOfferingFormValues directly

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<ProgramOffering>[] = [
  {
    key: "program_id",
    header: "Ngành đào tạo",
    width: "200px",
    render: (item) => {
      if (!item.program_id) return "—";
      return <span className="text-sm">Ngành #{item.program_id}</span>;
    },
  },
  {
    key: "offering_type",
    header: "Hệ đào tạo",
    width: "200px",
    render: (item) => {
      return <span className="text-sm">{item.offering_type || "—"}</span>;
    },
  },
  {
    key: "duration_semesters",
    header: "Thời gian (HK)",
    width: "120px",
    render: (item) => {
      return <span className="text-sm">{item.duration_semesters || "—"}</span>;
    },
  },
  {
    key: "total_credits",
    header: "Tổng tín chỉ",
    width: "120px",
    render: (item) => {
      return <span className="text-sm">{item.total_credits || "—"}</span>;
    },
  },
  { key: "is_active", header: "Trạng thái", width: "100px" },
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
    if (col.key === "program_id") {
      return {
        ...col,
        render: (item: ProgramOffering) => {
          const majorId = item.program_id;
          const major = majors.find((m: MajorProgram) => m.id === majorId);

          if (!major) {
            if (item.program?.name) return <span className="text-sm text-muted-foreground">{item.program.name}</span>;
            return <span className="text-muted-foreground">—</span>;
          }

          return (
            <span className="text-sm font-medium">
              {major.name}
              <span className="text-muted-foreground ml-1">({major.code})</span>
            </span>
          );
        },
      };
    }

    return col;
  });

  const handleCreate = async (formData: ProgramOfferingFormValues) => {
    const ofFormData = formData;

    if (!ofFormData.program_id) { toast.error("Vui lòng chọn ngành đào tạo"); return; }
    if (!ofFormData.offering_type_id) { toast.error("Vui lòng chọn hệ đào tạo"); return; }

    const offeringType = offeringTypes.find((t: OfferingType) => t.id === ofFormData.offering_type_id);
    if (!offeringType) {
      throw new Error("Please select a valid offering type");
    }

    const payload: ProgramOfferingCreate = {
      program_id: ofFormData.program_id || 0,
      offering_type_id: ofFormData.offering_type_id || 0,
      offering_type: offeringType.name,
      duration_semesters: ofFormData.duration_semesters,
      total_credits: ofFormData.total_credits,
      is_active: ofFormData.is_active !== undefined ? ofFormData.is_active : true,
      scoring_rules: ofFormData.scoring_rules,
    };

    await createMutation.mutateAsync(payload);
  };

  const handleUpdate = async (id: number, formData: ProgramOfferingFormValues) => {
    const ofFormData = formData;
    const payload: ProgramOfferingUpdate = {
      duration_semesters: ofFormData.duration_semesters,
      total_credits: ofFormData.total_credits,
      is_active: ofFormData.is_active,
      scoring_rules: ofFormData.scoring_rules,
    };

    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    _item: ProgramOffering | null,
    formData: ProgramOfferingFormValues,
    setFormData: (data: ProgramOfferingFormValues) => void,
    isEdit: boolean
  ) => {
    const ofFormData = formData;
    
    const updateForm = (updates: Partial<ProgramOfferingFormValues>) => {
      setFormData({ ...ofFormData, ...updates });
    };

    const updateScoringRules = (updates: Partial<ScoringRules>) => {
      const currentRules = ofFormData.scoring_rules || {};
      setFormData({ ...ofFormData, scoring_rules: { ...currentRules, ...updates } });
    };

    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="program_id">
            Ngành đào tạo <span className="text-destructive">*</span>
          </Label>
          <Select
            value={ofFormData.program_id?.toString() || ""}
            onValueChange={(value) => updateForm({ program_id: parseInt(value) })}
            disabled={isEdit}
          >
            <SelectTrigger id="program_id">
              <SelectValue placeholder="Chọn ngành đào tạo" />
            </SelectTrigger>
            <SelectContent>
              {majors.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  Chưa có ngành nào. Vui lòng tạo ngành đào tạo trước.
                </div>
              )}
              {majors.map((major: MajorProgram) => (
                <SelectItem key={major.id} value={major.id.toString()}>
                  {major.name} ({major.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Chương trình đào tạo (ví dụ: CNTT, Kinh tế)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offering_type_id">
            Hệ đào tạo <span className="text-destructive">*</span>
          </Label>
          <Select
            value={ofFormData.offering_type_id?.toString() || ""}
            onValueChange={(value) => updateForm({ offering_type_id: parseInt(value) })}
            disabled={isEdit}
          >
            <SelectTrigger id="offering_type_id">
              <SelectValue placeholder="Chọn hệ đào tạo" />
            </SelectTrigger>
            <SelectContent>
              {offeringTypes.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  Chưa có hệ đào tạo nào. Vui lòng tạo hệ đào tạo trước.
                </div>
              )}
              {offeringTypes.map((type: OfferingType) => (
                <SelectItem key={type.id} value={type.id.toString()}>
                  {type.name} ({type.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Hình thức đào tạo (Chính quy, Vừa làm vừa học...)
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="duration_semesters">Thời gian (Học kỳ)</Label>
            <Input
              id="duration_semesters"
              type="number"
              value={ofFormData.duration_semesters || ""}
              onChange={(e) => updateForm({ duration_semesters: e.target.value ? parseInt(e.target.value) : undefined })}
              placeholder="e.g., 6"
              min={1}
            />
            <p className="text-xs text-muted-foreground">
              Số học kỳ dự kiến để hoàn thành
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="total_credits">Tổng tín chỉ</Label>
            <Input
              id="total_credits"
              type="number"
              value={ofFormData.total_credits || ""}
              onChange={(e) => updateForm({ total_credits: e.target.value ? parseInt(e.target.value) : undefined })}
              placeholder="vd: 120"
              min={1}
            />
            <p className="text-xs text-muted-foreground">
              Tổng số tín chỉ tích lũy yêu cầu
            </p>
          </div>
        </div>

        <div className="border rounded-lg p-4 bg-muted space-y-4">
          <h3 className="font-medium flex items-center gap-2">
            Cấu hình Xét tuyển (Scoring Rules)
          </h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scoring_hot_level">Mức độ Hot</Label>
              <Select
                value={ofFormData.scoring_rules?.hot_level?.toString() || "0"}
                onValueChange={(value) => updateScoringRules({ hot_level: parseInt(value) })}
              >
                <SelectTrigger id="scoring_hot_level">
                  <SelectValue placeholder="Chọn mức độ Hot" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">Bình thường (0)</SelectItem>
                  <SelectItem value="1">Hot (1)</SelectItem>
                  <SelectItem value="2">Rất Hot (2)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="scoring_education">Trình độ văn hóa yêu cầu</Label>
              <Select
                value={ofFormData.scoring_rules?.required_education || "thpt"}
                onValueChange={(value) => updateScoringRules({ required_education: value })}
              >
                <SelectTrigger id="scoring_education">
                  <SelectValue placeholder="Chọn trình độ" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="thpt">Tốt nghiệp THPT</SelectItem>
                  <SelectItem value="cao_dang">Tốt nghiệp Cao đẳng</SelectItem>
                  <SelectItem value="dai_hoc">Tốt nghiệp Đại học</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scoring_age_min">Độ tuổi tối thiểu</Label>
              <Input
                id="scoring_age_min"
                type="number"
                value={ofFormData.scoring_rules?.target_age_min || ""}
                onChange={(e) => {
                  const val = e.target.value ? parseInt(e.target.value) : undefined;
                  updateScoringRules({ target_age_min: val });
                }}
                placeholder="vd: 18"
                min={16}
                max={100}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scoring_age_max">Độ tuổi tối đa</Label>
              <Input
                id="scoring_age_max"
                type="number"
                value={ofFormData.scoring_rules?.target_age_max || ""}
                onChange={(e) => {
                  const val = e.target.value ? parseInt(e.target.value) : undefined;
                  updateScoringRules({ target_age_max: val });
                }}
                placeholder="vd: 35"
                min={16}
                max={100}
              />
            </div>
          </div>
        </div>
      </div>
    );
  };

  const initialFormData = (): ProgramOfferingFormValues => ({
    program_id: null,
    offering_type_id: null,
    duration_semesters: 8,
    total_credits: 120,
    scoring_rules: {},
    is_active: true,
  });

  const mapItemToFormData = (item: ProgramOffering): ProgramOfferingFormValues => {
    const offeringType = offeringTypes.find((t: OfferingType) => t.name === item.offering_type);

    return {
      program_id: item.program_id,
      offering_type_id: offeringType?.id || null,
      is_active: item.is_active,
      duration_semesters: item.duration_semesters || 8,
      total_credits: item.total_credits || 120,
      scoring_rules: item.scoring_rules || {},
    };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold font-display">Chương trình Tuyển sinh</h1>
        <p className="text-muted-foreground mt-2">
          Quản lý các chương trình tuyển sinh (kết hợp giữa ngành và hệ đào tạo)
        </p>
      </div>

      {/* Warning if dependencies are missing */}
      {(majors.length === 0 || offeringTypes.length === 0) && (
        <div className="bg-warning-50 border border-warning-200 rounded-lg p-4">
          <p className="text-sm text-warning-800 font-medium">
            Yêu cầu dữ liệu
          </p>
          <p className="text-sm text-warning-700 mt-1">
            {majors.length === 0 && "Chưa có Ngành đào tạo. Vui lòng tạo Ngành trước tại Bước 2.1."}
            {majors.length === 0 && offeringTypes.length === 0 && " Đồng thời, "}
            {offeringTypes.length === 0 && "Chưa có Hệ đào tạo. Vui lòng tạo Hệ đào tạo trước tại Bước 1.2."}
          </p>
        </div>
      )}

      <CRUDTable<ProgramOffering, ProgramOfferingFormValues>
        title="Chương trình Tuyển sinh"
        description="Kết hợp giữa ngành và hệ đào tạo"
        icon={<BookOpen className="h-5 w-5 text-primary" />}
        columns={enhancedColumns}
        data={data}
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
