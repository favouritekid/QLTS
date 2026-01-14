/**
 * PhaseNavigator Component
 *
 * Sidebar navigator showing phase progress and allowing navigation
 * Displays completion status for Phase 1, 2, and 3
 */

"use client";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

import {
  Circle,
  ChevronRight,
  BarChart3,
} from "lucide-react";
import type {
  AdmissionConfigState,
  Phase1Step,
  Phase2Step,
} from "./shared/types";

// ============================================
// TYPES
// ============================================

interface PhaseNavigatorProps {
  currentState: AdmissionConfigState;
  onNavigate: (state: AdmissionConfigState) => void;
  className?: string;
}

interface StepConfig {
  id: string;
  label: string;
}

// ============================================
// CONSTANTS
// ============================================

const PHASE1_STEPS: StepConfig[] = [
  { id: "units", label: "Đơn vị Tổ chức" },
  { id: "offering-types", label: "Hệ Đào tạo" },
  { id: "methods", label: "Phương thức Tuyển sinh" },
  { id: "document-types", label: "Loại Giấy tờ" },
  { id: "subject-groups", label: "Tổ hợp môn" },
];

const PHASE2_STEPS: StepConfig[] = [
  { id: "majors", label: "Ngành Đào tạo" },
  { id: "offerings", label: "Chương trình Tuyển sinh" },
  { id: "academic-info", label: "Thông tin chi tiết" },
];

// ============================================
// COMPONENT
// ============================================

export function PhaseNavigator({
  currentState,
  onNavigate,
  className,
}: PhaseNavigatorProps) {
  const isPhase1Active = currentState.type === "phase1";
  const isPhase2Active = currentState.type === "phase2";
  const isPhase3Active = currentState.type === "phase3" || currentState.type === "select-context";

  const currentPhase1Step = isPhase1Active ? currentState.step : null;
  const currentPhase2Step = isPhase2Active ? currentState.step : null;

  // Helper to determine if a step is active
  const isStepActive = (phaseType: "phase1" | "phase2", stepId: string) => {
    if (phaseType === "phase1") {
      return isPhase1Active && currentPhase1Step === stepId;
    }
    return isPhase2Active && currentPhase2Step === stepId;
  };

  // Navigate to a step
  const handleStepClick = (phaseType: "phase1" | "phase2", stepId: string) => {
    if (phaseType === "phase1") {
      onNavigate({ type: "phase1", step: stepId as Phase1Step });
    } else {
      onNavigate({ type: "phase2", step: stepId as Phase2Step });
    }
  };

  // Navigate to Phase 3
  const handlePhase3Click = () => {
    onNavigate({ type: "select-context" });
  };

  return (
    <div className={cn("w-64 border-r bg-muted/10 p-4 space-y-4", className)}>
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold">Cấu hình Tuyển sinh</h2>
        <p className="text-sm text-muted-foreground">Trình hướng dẫn thiết lập</p>
      </div>

      {/* Phase 1 */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Giai đoạn 1: Dữ liệu Danh mục</h3>

        </div>
        <div className="space-y-1">
          {PHASE1_STEPS.map((step) => {
            const active = isStepActive("phase1", step.id);
            return (
              <button
                key={step.id}
                onClick={() => handleStepClick("phase1", step.id)}
                className={cn(
                  "w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded-md transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted text-muted-foreground hover:text-foreground"
                )}
              >
                {active ? (
                  <ChevronRight className="h-4 w-4 flex-shrink-0" />
                ) : (
                  <Circle className="h-3 w-3 flex-shrink-0" />
                )}
                <span className="truncate">{step.label}</span>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Phase 2 */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Giai đoạn 2: Chương trình</h3>

        </div>
        <div className="space-y-1">
          {PHASE2_STEPS.map((step) => {
            const active = isStepActive("phase2", step.id);
            return (
              <button
                key={step.id}
                onClick={() => handleStepClick("phase2", step.id)}
                className={cn(
                  "w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded-md transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted text-muted-foreground hover:text-foreground"
                )}
              >
                {active ? (
                  <ChevronRight className="h-4 w-4 flex-shrink-0" />
                ) : (
                  <Circle className="h-3 w-3 flex-shrink-0" />
                )}
                <span className="truncate">{step.label}</span>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Phase 3 */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Giai đoạn 3: Cấu hình</h3>

        </div>
        <Button
          variant={isPhase3Active ? "default" : "outline"}
          size="sm"
          className="w-full justify-start"
          onClick={handlePhase3Click}
        >
          <BarChart3 className="h-4 w-4 mr-2" />
          Đợt Tuyển sinh
        </Button>
      </Card>

      {/* Help Text */}
      <div className="text-xs text-muted-foreground px-2">
        <p>Hoàn thành Giai đoạn 1 và 2 trước khi cấu hình đợt tuyển sinh.</p>
      </div>
    </div>
  );
}
