/**
 * PathWizard Component
 *
 * Phase 3: Admission Path Creation/Editing Wizard
 * Multi-step wizard for complete admission path configuration:
 * - Step 1: Basic info (method selection)
 * - Step 2: Criteria configuration
 * - Step 3: Document requirements
 */

"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ChevronLeft, Loader2, ArrowRight, CheckCircle2, Circle } from "lucide-react";
import { toast } from "sonner";
import {
  useAdmissionPath,
  useCreateAdmissionPath,
  useUpdateAdmissionPath,
} from "@/hooks/admissions/useAdmissionPaths";
import { useQueryClient } from "@tanstack/react-query";
import { admissionPathKeys } from "@/hooks/admissions/useAdmissionPaths";
import { useAdmissionMethods } from "@/hooks/admissions/useMasterData";
import { ConfigCriteria } from "./ConfigCriteria";
import { ConfigDocuments } from "./ConfigDocuments";
import { ConfigReview } from "./ConfigReview";
import type { SelectionContext, Phase3View, AdmissionMethod } from "../shared/types";
import type { AxiosError } from "axios";

// ============================================
// TYPES
// ============================================

interface PathWizardProps {
  context: SelectionContext;
  pathId?: number;
  onNavigate: (view: Phase3View) => void;
  initialStep?: 1 | 2 | 3;
}

// ============================================
// COMPONENTS
// ============================================

function StepIndicator({ currentStep, step, title }: { currentStep: number; step: number; title: string }) {
  const isCompleted = currentStep > step;
  const isCurrent = currentStep === step;

  return (
    <div className={`flex items-center gap-2 ${isCurrent ? "text-primary font-medium" : "text-muted-foreground"}`}>
      {isCompleted ? (
        <CheckCircle2 className="h-5 w-5 text-green-600" />
      ) : isCurrent ? (
        <div className="h-5 w-5 rounded-full border-2 border-primary flex items-center justify-center text-xs">
          {step}
        </div>
      ) : (
        <Circle className="h-5 w-5" />
      )}
      <span className={isCurrent ? "text-foreground" : ""}>{title}</span>
      {step < 4 && <div className="w-8 h-[1px] bg-border mx-2" />}
    </div>
  );
}

export function PathWizard({ context, pathId, onNavigate, initialStep = 1 }: PathWizardProps) {
  // Wizard State
  const [step, setStep] = useState<number>(initialStep);
  const [activePathId, setActivePathId] = useState<number | undefined>(pathId);

  // Router and params for URL synchronization
  const router = useRouter();
  const searchParams = useSearchParams();

  // Query Client for manual refetching
  const queryClient = useQueryClient();

  // Update URL when step changes
  useEffect(() => {
    const currentStep = searchParams.get('wizardStep');
    if (currentStep !== step.toString()) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('wizardStep', step.toString());
      router.replace(`?${params.toString()}`, { scroll: false });
    }
  }, [step, searchParams, router]);

  // Fetch data
  const { data: path, isLoading: loadingPath } = useAdmissionPath(activePathId);
  const { data: methods = [], isLoading: loadingMethods } = useAdmissionMethods();
  const createMutation = useCreateAdmissionPath();
  const updateMutation = useUpdateAdmissionPath();

  // Form State (Step 1)
  const [displayName, setDisplayName] = useState("");
  const [selectedMethodId, setSelectedMethodId] = useState<number | null>(null);
  const [displayOrder, setDisplayOrder] = useState(1);
  const [visibility, setVisibility] = useState<"public" | "internal">("internal");

  // Sync form state when path data loads
  useEffect(() => {
    if (path) {
      setDisplayName(path.display_name || "");
      setSelectedMethodId(path.admission_method?.id || null);
      setDisplayOrder(path.display_order || 1);
      setVisibility(path.visibility || "internal");
      setActivePathId(path.id);
    }
  }, [path]);

  // Step 1 Handler: Create/Update Basic Info
  const handleSaveBasic = async () => {
    if (!selectedMethodId) {
      toast.error("Vui lòng chọn phương thức tuyển sinh");
      return;
    }

    try {
      let savedId = activePathId;

      if (activePathId) {
        // Update existing
        await updateMutation.mutateAsync({
          pathId: activePathId,
          data: {
            display_name: displayName || undefined,
            display_order: displayOrder,
            visibility: visibility,
          },
        });
        toast.success("Cập nhật thông tin cơ bản thành công");
      } else {
        // Create new
        const newPath = await createMutation.mutateAsync({
          academic_info_id: context.academicInfoId,
          admission_method_id: selectedMethodId,
          display_name: displayName || undefined,
          display_order: displayOrder,
          visibility: visibility,
        });
        savedId = newPath.id;
        setActivePathId(savedId);
        toast.success("Tạo đợt tuyển sinh thành công");
      }

      // Refetch path data to get updated information
      if (savedId) {
        await queryClient.invalidateQueries({
          queryKey: admissionPathKeys.detail(savedId)
        });
      }

      // Move to Step 2
      setStep(2);
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      toast.error(axiosError.response?.data?.detail || "Lưu thất bại");
    }
  };

  const handleBackToList = () => {
    onNavigate({ type: "list" });
  };

  const isSavingBasic = createMutation.isPending || updateMutation.isPending;
  const isLoading = (!!activePathId && loadingPath) || loadingMethods;

  // ... (previous code)

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header & Stepper */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Button variant="ghost" size="sm" onClick={handleBackToList}>
            <ChevronLeft className="h-4 w-4 mr-1" />
            Quay lại Danh sách
          </Button>
        </div>
        
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">
            {activePathId ? "Cấu hình Đợt Tuyển sinh" : "Thêm mới Đợt Tuyển sinh"}
          </h1>
          {/* Stepper */}
          <div className="flex items-center">
            <StepIndicator currentStep={step} step={1} title="Cơ bản" />
            <StepIndicator currentStep={step} step={2} title="Tiêu chí" />
            <StepIndicator currentStep={step} step={3} title="Hồ sơ" />
            <StepIndicator currentStep={step} step={4} title="Hoàn tất" />
          </div>
        </div>
      </div>

      {/* Logic for Steps */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Bước 1: Thông tin Cơ bản</CardTitle>
            <CardDescription>
              Chọn phương thức tuyển sinh và tên hiển thị
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : (
              <div className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="method">
                    Phương thức Tuyển sinh <span className="text-destructive">*</span>
                  </Label>
                  <Select
                    value={selectedMethodId?.toString() || ""}
                    onValueChange={(value) => setSelectedMethodId(parseInt(value))}
                    disabled={!!activePathId} // Cannot change method after creation
                  >
                    <SelectTrigger id="method">
                      <SelectValue placeholder="Chọn phương thức" />
                    </SelectTrigger>
                    <SelectContent>
                      {methods.map((method: AdmissionMethod) => (
                        <SelectItem key={method.id} value={method.id.toString()}>
                          {method.name}
                          <span className="text-muted-foreground ml-2">({method.code})</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {activePathId && (
                    <p className="text-xs text-muted-foreground">
                      Không thể thay đổi phương thức sau khi tạo
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="displayName">Tên hiển thị (Tùy chọn)</Label>
                  <Input
                    id="displayName"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Để trống để dùng tên phương thức mặc định"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="displayOrder">Thứ tự hiển thị</Label>
                  <Input
                    id="displayOrder"
                    type="number"
                    value={displayOrder}
                    onChange={(e) => setDisplayOrder(parseInt(e.target.value) || 1)}
                    min={1}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="visibility">Hiển thị</Label>
                  <Select
                    value={visibility}
                    onValueChange={(val: "public" | "internal") => setVisibility(val)}
                  >
                    <SelectTrigger id="visibility">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="public">Công khai</SelectItem>
                      <SelectItem value="internal">Nội bộ</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Công khai: Hiển thị cho thí sinh. Nội bộ: Chỉ admin/manager thấy.
                  </p>
                </div>

                <div className="flex justify-end pt-4">
                  <Button onClick={handleSaveBasic} disabled={isSavingBasic}>
                    {isSavingBasic ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <ArrowRight className="h-4 w-4 mr-2" />
                    )}
                    {activePathId ? "Cập nhật & Tiếp tục" : "Tạo & Tiếp tục"}
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {step === 2 && path && (
        <ConfigCriteria
          // FIX: Add key to force re-mount when path/criteria changes
          key={`step2-${path.updated_at}-${path.criteria?.id || 'no-criteria'}`}
          path={path}
          onNext={() => setStep(3)}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && path && (
        <ConfigDocuments 
          // FIX: Add key to force re-mount
          key={`step3-${path.updated_at}`}
          path={path} 
          onFinish={() => setStep(4)} 
          onBack={() => setStep(2)} 
        />
      )}

      {step === 4 && path && (
        // NEW: Review Step
        <div className="animate-in fade-in slide-in-from-right-4 duration-300">
          <ConfigReview 
            key={`step4-${path.updated_at}`}
            path={path}
            onBack={() => setStep(3)}
            onFinish={handleBackToList}
          />
        </div>
      )}

      {/* Loading State for Steps 2/3/4 if path missing */}
      {step > 1 && !path && (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )}
    </div>
  );
}
