"use client";

import { Bell, Users, MessageSquare, Check, AlertCircle } from "lucide-react";
import type { StepErrors } from "./wizard-utils";

interface StepIndicatorProps {
  currentStep: number;
  onStepClick: (step: number) => void;
  stepErrors: StepErrors;
  highestStepVisited: number;
}

const STEPS = [
  { number: 1, label: "Sự kiện & Điều kiện", icon: Bell },
  { number: 2, label: "Soạn nội dung", icon: MessageSquare },
  { number: 3, label: "Người nhận & Kênh gửi", icon: Users },
  { number: 4, label: "Kiểm tra & Lưu", icon: Check },
];

function getStepErrorCount(stepNumber: number, errors: StepErrors): number {
  const key = `step${stepNumber}` as keyof StepErrors;
  return errors[key]?.length ?? 0;
}

function allPriorStepsValid(target: number, errors: StepErrors): boolean {
  for (let s = 1; s < target; s++) {
    if (getStepErrorCount(s, errors) > 0) return false;
  }
  return true;
}

export default function StepIndicator({
  currentStep,
  onStepClick,
  stepErrors,
  highestStepVisited,
}: StepIndicatorProps) {
  return (
    <div className="flex items-center justify-between mb-8">
      {STEPS.map((step, index) => {
        const Icon = step.icon;
        const isActive = currentStep === step.number;
        const isVisited = step.number <= highestStepVisited;

        // Forward nav: only accessible if all prior steps are valid
        const isAccessible = isVisited ||
          (step.number === highestStepVisited + 1 && allPriorStepsValid(step.number, stepErrors));
        const canClick = isAccessible && !isActive;

        // Error state: only for visited, non-active steps with validation
        const errorCount = getStepErrorCount(step.number, stepErrors);
        const hasError = !isActive && isVisited && errorCount > 0;
        const isCompleted = isVisited && !isActive && !hasError;

        // Circle style
        let circleClass = "border-muted-foreground/30 text-muted-foreground";
        if (isActive) circleClass = "border-primary bg-primary text-primary-foreground";
        else if (hasError) circleClass = "border-amber-500 bg-amber-500 text-white";
        else if (isCompleted) circleClass = "border-success-500 bg-success-500 text-white";

        // Label style
        let labelClass = "text-muted-foreground";
        if (isActive) labelClass = "text-primary";
        else if (hasError) labelClass = "text-amber-600";
        else if (isCompleted) labelClass = "text-success-600";

        // Connector: reflects state of the current step (connector comes AFTER step)
        const connectorActive = step.number < highestStepVisited;
        const connectorHasError = connectorActive && errorCount > 0;

        return (
          <div key={step.number} className="flex items-center flex-1">
            <div className="flex flex-col items-center flex-1">
              <button
                type="button"
                onClick={() => canClick && onStepClick(step.number)}
                disabled={!isAccessible}
                className={`
                  flex items-center justify-center w-10 h-10 rounded-full border-2 transition-colors
                  ${circleClass}
                  ${canClick ? "cursor-pointer hover:opacity-80" : ""}
                  ${!isAccessible ? "cursor-not-allowed opacity-60" : ""}
                `}
                title={
                  hasError
                    ? `${step.label}: ${errorCount} lỗi cần sửa`
                    : !isAccessible
                      ? "Hoàn thành bước trước để tiếp tục"
                      : step.label
                }
              >
                {hasError ? (
                  <AlertCircle className="h-5 w-5" />
                ) : (
                  <Icon className="h-5 w-5" />
                )}
              </button>
              <span className={`text-xs mt-1 font-medium ${labelClass}`}>
                {step.label}
              </span>
            </div>
            {index < STEPS.length - 1 && (
              <div
                className={`
                  h-0.5 flex-1 mx-2 mb-6 transition-colors
                  ${connectorActive && !connectorHasError ? "bg-success-500" : ""}
                  ${connectorActive && connectorHasError ? "bg-amber-400" : ""}
                  ${!connectorActive ? "bg-muted-foreground/20" : ""}
                `}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
