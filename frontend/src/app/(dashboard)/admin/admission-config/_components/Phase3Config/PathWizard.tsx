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
import { useAdmissionMethods } from "@/hooks/admissions/useMasterData";
import { ConfigCriteria } from "./ConfigCriteria";
import { ConfigDocuments } from "./ConfigDocuments";
import { ConfigReview } from "./ConfigReview";
import { PathBasicInfo } from "./PathBasicInfo";
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
        <CheckCircle2 className="h-5 w-5 text-success-600" />
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

  // REMOVED: Local Form State and Effects (delegated to PathBasicInfo)

  const handleBackToList = () => {
    onNavigate({ type: "list" });
  };
  
  const handleBasicInfoFinish = (savedPathId: number) => {
    // If created new, set ID to switch to edit mode
    if (!activePathId) {
      setActivePathId(savedPathId);
    }
    setStep(2);
  };

  const isLoading = (!!activePathId && loadingPath) || loadingMethods;

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
          <h1 className="text-2xl font-bold font-display">
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
        isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : (
          <PathBasicInfo
            key={activePathId ? `edit-${activePathId}-${path?.updated_at}` : "create-new"}
            path={path}
            methods={methods}
            academicInfoId={context.academicInfoId}
            onFinish={handleBasicInfoFinish}
          />
        )
      )}

      {step === 2 && path && (
        <ConfigCriteria
          // Force re-mount when path/criteria changes with granular dependencies
          key={`step2-${path.id}-${path.criteria?.id || 'no-criteria'}-${path.criteria?.subject_groups?.length || 0}`}
          path={path}
          onNext={() => setStep(3)}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && path && (
        <ConfigDocuments
          // Force re-mount when path changes
          key={`step3-${path.id}-${path.validation_errors?.length || 0}`}
          path={path}
          onFinish={() => setStep(4)}
          onBack={() => setStep(2)}
        />
      )}

      {step === 4 && path && (
        // NEW: Review Step
        <div className="animate-in fade-in slide-in-from-right-4 duration-300">
          <ConfigReview
            key={`step4-${path.id}-${path.status}-${path.validation_errors?.length || 0}`}
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
