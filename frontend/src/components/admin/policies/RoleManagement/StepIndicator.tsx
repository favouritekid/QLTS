// src/components/admin/policies/RoleManagement/StepIndicator.tsx
"use client";

import { CheckCircle2, Circle, ChevronRight } from "lucide-react";
import { StepIndicatorProps } from "./types";

/**
 * StepIndicator - Visual indicator for the 3-step workflow
 *
 * Shows the current progress through:
 * 1. SELECT_ROLE - Choose or create a role
 * 2. VIEW_DETAILS - View permission breakdown
 * 3. MANAGE_FEATURES - Enable/disable features
 */
export function StepIndicator({ currentStep }: StepIndicatorProps) {
  const steps = [
    { id: "SELECT_ROLE", label: "Chọn Vai trò" },
    { id: "VIEW_DETAILS", label: "Xem Chi tiết" },
    { id: "MANAGE_FEATURES", label: "Quản lý Tính năng" },
  ];

  const currentIndex = steps.findIndex((s) => s.id === currentStep);

  return (
    <div className="flex items-center gap-2 mb-6">
      {steps.map((step, index) => (
        <div key={step.id} className="flex items-center">
          <div className="flex items-center gap-2">
            {index < currentIndex ? (
              <CheckCircle2 className="h-5 w-5 text-primary" />
            ) : index === currentIndex ? (
              <Circle className="h-5 w-5 fill-primary text-primary" />
            ) : (
              <Circle className="h-5 w-5 text-muted-foreground" />
            )}
            <span
              className={
                index === currentIndex
                  ? "font-semibold text-foreground"
                  : index < currentIndex
                    ? "text-primary"
                    : "text-muted-foreground"
              }
            >
              {step.label}
            </span>
          </div>
          {index < steps.length - 1 && (
            <ChevronRight className="mx-2 h-4 w-4 text-muted-foreground" />
          )}
        </div>
      ))}
    </div>
  );
}
