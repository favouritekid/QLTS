// src/components/leads/AdmissionReadinessChecklist.tsx
/**
 * AdmissionReadinessChecklist - Shows admission progress checklist
 *
 * Phase 1: Derived from existing data (readonly)
 * Phase 2 (future): Database-backed configurable checklist
 *
 * Shows what steps are completed in the admission journey:
 * - Has offering selected
 * - Has admission profile created
 * - Profile submitted
 * - Profile approved
 */
"use client";

import { useMemo } from "react";
import { Check, Circle, ArrowRight, ClipboardCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Lead } from "@/types/lead.types";

interface AdmissionReadinessChecklistProps {
  lead: Lead;
  onCreateProfile?: () => void;
  onViewProfile?: () => void;
  className?: string;
}

interface ChecklistItem {
  id: string;
  label: string;
  completed: boolean;
  required: boolean;
  description?: string;
}

// Phase 1: Derive checklist from existing lead data
function deriveAdmissionChecklist(lead: Lead): ChecklistItem[] {
  const profile = lead.admission_profile;
  const profileStatus = profile?.status;

  return [
    {
      id: "has_offering",
      label: "Đã chọn ngành học",
      completed: !!lead.offering_id,
      required: true,
      description: lead.offering?.program?.name || lead.offering?.offering_type,
    },
    {
      id: "has_profile",
      label: "Đã tạo hồ sơ tuyển sinh",
      completed: !!profile,
      required: true,
    },
    {
      id: "profile_submitted",
      label: "Đã nộp hồ sơ",
      completed:
        profileStatus === "submitted" ||
        profileStatus === "approved" ||
        profileStatus === "confirmed" ||
        profileStatus === "enrolled" ||
        profileStatus === "overridden" ||
        profileStatus === "resubmitted" ||
        profileStatus === "rejected",
      required: true,
    },
    {
      id: "profile_approved",
      label: "Hồ sơ đã duyệt",
      completed:
        profileStatus === "approved" ||
        profileStatus === "confirmed" ||
        profileStatus === "enrolled" ||
        profileStatus === "overridden",
      required: true,
    },
  ];
}

export function AdmissionReadinessChecklist({
  lead,
  onCreateProfile,
  onViewProfile,
  className,
}: AdmissionReadinessChecklistProps) {
  const checklist = useMemo(() => deriveAdmissionChecklist(lead), [lead]);

  const completedCount = checklist.filter((item) => item.completed).length;
  const totalCount = checklist.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);

  // Find next incomplete step
  const nextStep = checklist.find((item) => !item.completed);

  const hasProfile = !!lead.admission_profile;
  const hasOffering = !!lead.offering_id;

  return (
    <div className={cn("border rounded-lg bg-card", className)}>
      {/* Header with progress */}
      <div className="px-3 py-2.5 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ClipboardCheck aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">Tiến độ tuyển sinh</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {completedCount}/{totalCount}
          </span>
          <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full transition-[width] duration-300",
                progressPercent === 100 ? "bg-success-500" : "bg-info-500"
              )}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      </div>

      {/* Checklist items */}
      <div className="p-3 space-y-2">
        {checklist.map((item, index) => (
          <div
            key={item.id}
            className={cn(
              "flex items-start gap-2.5 text-sm",
              !item.completed && "opacity-60"
            )}
          >
            {/* Status icon */}
            <div className="mt-0.5 shrink-0">
              {item.completed ? (
                <div className="h-4 w-4 rounded-full bg-success-100 flex items-center justify-center">
                  <Check aria-hidden="true" className="h-2.5 w-2.5 text-success-600" />
                </div>
              ) : (
                <Circle aria-hidden="true" className="h-4 w-4 text-muted-foreground/50" />
              )}
            </div>

            {/* Label and description */}
            <div className="flex-1 min-w-0">
              <p
                className={cn(
                  "text-sm",
                  item.completed
                    ? "text-foreground"
                    : "text-muted-foreground"
                )}
              >
                {item.label}
              </p>
              {item.description && item.completed && (
                <p className="text-xs text-muted-foreground truncate">
                  {item.description}
                </p>
              )}
            </div>

            {/* Step number */}
            <span className="text-xs text-muted-foreground/50 shrink-0">
              {index + 1}
            </span>
          </div>
        ))}
      </div>

      {/* Action area */}
      {nextStep && hasOffering && (
        <div className="px-3 pb-3 pt-1">
          <div className="p-2.5 rounded-lg bg-muted/50 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
              <span>Bước tiếp theo: {nextStep.label}</span>
            </div>

            {/* CTA Button based on current state */}
            {!hasProfile && (
              <Button
                size="sm"
                variant="default"
                className="h-7 text-xs"
                onClick={onCreateProfile}
              >
                Tạo hồ sơ
              </Button>
            )}
            {hasProfile && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={onViewProfile}
              >
                Xem hồ sơ
              </Button>
            )}
          </div>
        </div>
      )}

      {/* No offering warning */}
      {!hasOffering && (
        <div className="px-3 pb-3">
          <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700">
            Cần chọn ngành học trước khi tạo hồ sơ tuyển sinh
          </div>
        </div>
      )}
    </div>
  );
}

export default AdmissionReadinessChecklist;
