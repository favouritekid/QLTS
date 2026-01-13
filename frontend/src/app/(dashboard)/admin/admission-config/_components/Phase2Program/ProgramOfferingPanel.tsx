/**
 * ProgramOfferingPanel Component
 *
 * Phase 2.2: Program Offering Management
 * CRUD interface for program offerings (combinations of major + offering type)
 * Example: "IT Program - Full-time", "Business Program - Part-time"
 */

"use client";

import { BookOpen } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { CRUDTable } from "../shared/CRUDTable";
import type { ProgramOffering, CRUDTableColumn, BaseFormData } from "../shared/types";
import {
  useProgramOfferings,
  useCreateProgramOffering,
  useUpdateProgramOffering,
  useDeleteProgramOffering,
} from "@/hooks/admissions/useProgramData";
import { useMajorPrograms } from "@/hooks/admissions/useProgramData";
import { useOfferingTypes } from "@/hooks/admissions/useMasterData";

// ============================================
// CONSTANTS
// ============================================

const COLUMNS: CRUDTableColumn<ProgramOffering>[] = [
  {
    key: "program_id",
    header: "Major Program",
    width: "200px",
    render: (item) => {
      if (!item.program_id) return "—";
      return <span className="text-sm">Major #{item.program_id}</span>;
    },
  },
  {
    key: "offering_type",
    header: "Offering Type",
    width: "200px",
    render: (item) => {
      return <span className="text-sm">{item.offering_type || "—"}</span>;
    },
  },
  {
    key: "duration_semesters",
    header: "Duration (Semesters)",
    width: "120px",
    render: (item) => {
      return <span className="text-sm">{item.duration_semesters || "—"}</span>;
    },
  },
  {
    key: "total_credits",
    header: "Total Credits",
    width: "120px",
    render: (item) => {
      return <span className="text-sm">{item.total_credits || "—"}</span>;
    },
  },
  { key: "is_active", header: "Status", width: "100px" },
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
    // Handle Major Program (ID Map)
    if (col.key === "program_id") {
      return {
        ...col,
        render: (item: any) => {
          // Use program_id from backend
          const majorId = item.program_id;
          const major = majors.find((m: { id: number; name: string; code: string }) => m.id === majorId);

          if (!major) {
             // Try to use nested program name if available
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

  const handleCreate = async (formData: BaseFormData) => {
    // Transform to match backend ProgramOfferingCreate schema
    const offeringType = offeringTypes.find((t: { id: number; name: string }) => t.id === formData.offering_type_id);
    if (!offeringType) {
      throw new Error("Please select a valid offering type");
    }

    const payload = {
      program_id: parseInt(formData.program_id?.toString() || "0"),
      offering_type: offeringType.name, // Backend expects string name, not ID
      duration_semesters: (formData as any).duration_semesters || undefined,
      total_credits: (formData as any).total_credits || undefined,
      is_active: formData.is_active !== undefined ? formData.is_active : true,
      scoring_rules: (formData as any).scoring_rules || undefined,
    };

    await createMutation.mutateAsync(payload as any);
  };

  const handleUpdate = async (id: number, formData: BaseFormData) => {
    // Transform to match backend ProgramOfferingUpdate schema
    const payload: any = {
      duration_semesters: (formData as any).duration_semesters || undefined,
      total_credits: (formData as any).total_credits || undefined,
      is_active: formData.is_active,
      scoring_rules: (formData as any).scoring_rules || undefined,
    };

    // If offering_type_id is provided, convert it to offering_type (string)
    if (formData.offering_type_id) {
      const offeringType = offeringTypes.find((t: { id: number; name: string }) => t.id === formData.offering_type_id);
      if (offeringType) {
        payload.offering_type = offeringType.name;
      }
    }

    await updateMutation.mutateAsync({ id, data: payload });
  };

  const handleDelete = async (id: number) => {
    await deleteMutation.mutateAsync(id);
  };

  const renderForm = (
    item: ProgramOffering | null,
    formData: BaseFormData,
    setFormData: (data: BaseFormData) => void,
    isEdit: boolean
  ) => {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="program_id">
            Major Program <span className="text-destructive">*</span>
          </Label>
          <Select
            value={formData.program_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, program_id: parseInt(value) })
            }
          >
            <SelectTrigger id="program_id">
              <SelectValue placeholder="Select major program" />
            </SelectTrigger>
            <SelectContent>
              {majors.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  No major programs available. Please create one first.
                </div>
              )}
              {majors.map((major: { id: number; name: string; code: string }) => (
                <SelectItem key={major.id} value={major.id.toString()}>
                  {major.name} ({major.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The academic program (e.g., IT, Business, Engineering)
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offering_type_id">
            Offering Type <span className="text-destructive">*</span>
          </Label>
          <Select
            value={formData.offering_type_id?.toString() || ""}
            onValueChange={(value) =>
              setFormData({ ...formData, offering_type_id: parseInt(value) })
            }
          >
            <SelectTrigger id="offering_type_id">
              <SelectValue placeholder="Select offering type" />
            </SelectTrigger>
            <SelectContent>
              {offeringTypes.length === 0 && (
                <div className="p-2 text-sm text-muted-foreground">
                  No offering types available. Please create one first.
                </div>
              )}
              {offeringTypes.map((type: { id: number; name: string; code: string }) => (
                <SelectItem key={type.id} value={type.id.toString()}>
                  {type.name} ({type.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The study mode (e.g., Full-time, Part-time, Distance learning)
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="duration_semesters">Duration (Semesters)</Label>
            <Input
              id="duration_semesters"
              type="number"
              value={(formData as any).duration_semesters || ""}
              onChange={(e) =>
                setFormData({ ...formData, duration_semesters: e.target.value ? parseInt(e.target.value) : undefined } as any)
              }
              placeholder="e.g., 6"
              min={1}
            />
            <p className="text-xs text-muted-foreground">
              Number of semesters for this program
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="total_credits">Total Credits</Label>
            <Input
              id="total_credits"
              type="number"
              value={(formData as any).total_credits || ""}
              onChange={(e) =>
                setFormData({ ...formData, total_credits: e.target.value ? parseInt(e.target.value) : undefined } as any)
              }
              placeholder="e.g., 120"
              min={1}
            />
            <p className="text-xs text-muted-foreground">
              Total credit hours required
            </p>
          </div>
        </div>

        <div className="border rounded-lg p-4 bg-slate-50 space-y-4">
          <h3 className="font-medium flex items-center gap-2">
            Fit Score Configuration (Scoring Rules)
          </h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scoring_hot_level">Hot Level</Label>
              <Select
                value={(formData as any).scoring_rules?.hot_level?.toString() || "0"}
                onValueChange={(value) => {
                  const currentRules = (formData as any).scoring_rules || {};
                  setFormData({
                    ...formData,
                    scoring_rules: { ...currentRules, hot_level: parseInt(value) }
                  } as any);
                }}
              >
                <SelectTrigger id="scoring_hot_level">
                  <SelectValue placeholder="Select Hot Level" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">Normal (0)</SelectItem>
                  <SelectItem value="1">Hot (1)</SelectItem>
                  <SelectItem value="2">Very Hot (2)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="scoring_education">Required Education</Label>
              <Select
                value={(formData as any).scoring_rules?.required_education || "thpt"}
                onValueChange={(value) => {
                  const currentRules = (formData as any).scoring_rules || {};
                  setFormData({
                    ...formData,
                    scoring_rules: { ...currentRules, required_education: value }
                  } as any);
                }}
              >
                <SelectTrigger id="scoring_education">
                  <SelectValue placeholder="Select Education" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="thpt">High School (THPT)</SelectItem>
                  <SelectItem value="cao_dang">College (Cao đẳng)</SelectItem>
                  <SelectItem value="dai_hoc">University (Đại học)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scoring_age_min">Min Target Age</Label>
              <Input
                id="scoring_age_min"
                type="number"
                value={(formData as any).scoring_rules?.target_age_min || ""}
                onChange={(e) => {
                   const val = e.target.value ? parseInt(e.target.value) : undefined;
                   const currentRules = (formData as any).scoring_rules || {};
                   setFormData({
                    ...formData,
                    scoring_rules: { ...currentRules, target_age_min: val }
                  } as any);
                }}
                placeholder="e.g. 18"
                min={16}
                max={100}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scoring_age_max">Max Target Age</Label>
              <Input
                id="scoring_age_max"
                type="number"
                value={(formData as any).scoring_rules?.target_age_max || ""}
                onChange={(e) => {
                   const val = e.target.value ? parseInt(e.target.value) : undefined;
                   const currentRules = (formData as any).scoring_rules || {};
                   setFormData({
                    ...formData,
                    scoring_rules: { ...currentRules, target_age_max: val }
                  } as any);
                }}
                placeholder="e.g. 35"
                min={16}
                max={100}
              />
            </div>
          </div>
        </div>
      </div>
    );
  };

  const initialFormData = () => ({
    program_id: null,
    offering_type_id: null,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Program Offerings</h1>
        <p className="text-muted-foreground mt-2">
          Manage program offerings by combining major programs with offering types
        </p>
      </div>

      {/* Warning if dependencies are missing */}
      {(majors.length === 0 || offeringTypes.length === 0) && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-sm text-yellow-800 font-medium">
            Prerequisites Required
          </p>
          <p className="text-sm text-yellow-700 mt-1">
            {majors.length === 0 && "No major programs found. Please create major programs first in Phase 2.1."}
            {majors.length === 0 && offeringTypes.length === 0 && " Also, "}
            {offeringTypes.length === 0 && "No offering types found. Please create offering types in Phase 1.2."}
          </p>
        </div>
      )}

      <CRUDTable
        title="Program Offering"
        description="Combinations of major programs and offering types"
        icon={<BookOpen className="h-5 w-5 text-primary" />}
        columns={enhancedColumns}
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
