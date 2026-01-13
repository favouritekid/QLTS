/**
 * useAdmissionConfigState Hook
 *
 * State machine for Admission Config navigation
 * Manages transitions between Welcome -> Phase1 -> Phase2 -> Phase3
 */

"use client";

import { useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type {
  AdmissionConfigState,
  Phase1Step,
  Phase2Step,
  SelectionContext,
  Phase3View,
} from "@/app/(dashboard)/admin/admission-config/_components/shared/types";

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Check if Phase 1 master data is complete
 */
async function checkPhase1Complete(): Promise<boolean> {
  try {
    // Check if all Phase 1 entities have at least one record
    // This is a simple check - can be enhanced with more robust validation
    const response = await fetch("/api/admin/offering-types?active_only=false");
    const data = await response.json();
    return data && data.length > 0;
  } catch {
    return false;
  }
}

/**
 * Check if Phase 2 program data exists
 */
async function checkPhase2Complete(): Promise<boolean> {
  try {
    const response = await fetch("/api/programs");
    const data = await response.json();
    return data && data.length > 0;
  } catch {
    return false;
  }
}

/**
 * Parse selection context from URL params
 */
function getContextFromParams(params: URLSearchParams): SelectionContext | null {
  const year = params.get("year");
  const major = params.get("major");
  const offering = params.get("offering");
  const academicInfo = params.get("academicInfo");

  if (!year || !major || !offering || !academicInfo) {
    return null;
  }

  return {
    academicYear: parseInt(year),
    majorProgramId: parseInt(major),
    offeringId: parseInt(offering),
    academicInfoId: parseInt(academicInfo),
  };
}

/**
 * Parse Phase 3 view from URL params
 */
function parsePhase3View(view: string | null, params: URLSearchParams): Phase3View {
  if (view === "matrix") {
    return { type: "matrix" };
  }

  if (view === "wizard") {
    const pathId = params.get("pathId");
    const wizardStep = params.get("wizardStep");

    return {
      type: "wizard",
      pathId: pathId ? parseInt(pathId) : undefined,
      wizardStep: wizardStep ? parseInt(wizardStep) : undefined,
    };
  }

  // Default to list view
  return { type: "list" };
}

/**
 * Convert state to URL string
 */
function stateToUrl(state: AdmissionConfigState): string {
  const base = "/admin/admission-config";

  if (state.type === "welcome") {
    return base;
  }

  if (state.type === "phase1") {
    return `${base}?phase=1&step=${state.step}`;
  }

  if (state.type === "phase2") {
    return `${base}?phase=2&step=${state.step}`;
  }

  if (state.type === "select-context") {
    return `${base}?phase=3`;
  }

  if (state.type === "phase3") {
    const ctx = state.context;
    const params = new URLSearchParams({
      phase: "3",
      year: ctx.academicYear.toString(),
      major: ctx.majorProgramId.toString(),
      offering: ctx.offeringId.toString(),
      academicInfo: ctx.academicInfoId.toString(),
      view: state.view.type,
    });

    if (state.view.type === "wizard") {
      if (state.view.pathId) {
        params.set("pathId", state.view.pathId.toString());
      }
      if (state.view.wizardStep !== undefined) {
        params.set("wizardStep", state.view.wizardStep.toString());
      }
    }

    return `${base}?${params.toString()}`;
  }

  return base;
}

// ============================================
// HOOK
// ============================================

export function useAdmissionConfigState() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // Check Phase 1 completion
  const { data: hasPhase1Data, isLoading: checkingPhase1 } = useQuery({
    queryKey: ["phase1-check"],
    queryFn: checkPhase1Complete,
    staleTime: 30000, // 30 seconds
  });

  // Check Phase 2 completion
  const { data: hasPhase2Data, isLoading: checkingPhase2 } = useQuery({
    queryKey: ["phase2-check"],
    queryFn: checkPhase2Complete,
    staleTime: 30000,
    enabled: hasPhase1Data === true,
  });

  // Derive current state from URL params + data availability
  const currentState: AdmissionConfigState = useMemo(() => {
    const phase = searchParams.get("phase");
    const step = searchParams.get("step");
    const view = searchParams.get("view");

    // If checking data, stay in welcome state
    if (checkingPhase1 || checkingPhase2) {
      return { type: "welcome" };
    }

    // If Phase 1 URL param, show Phase 1
    if (phase === "1" && step) {
      return { type: "phase1", step: step as Phase1Step };
    }

    // If Phase 2 URL param, show Phase 2
    if (phase === "2" && step) {
      return { type: "phase2", step: step as Phase2Step };
    }

    // If Phase 3 URL param
    if (phase === "3") {
      const context = getContextFromParams(searchParams);
      if (!context) {
        return { type: "select-context" };
      }
      return {
        type: "phase3",
        context,
        view: parsePhase3View(view, searchParams),
      };
    }

    // If no phase param and no Phase 1 data, show welcome screen
    if (!phase && !hasPhase1Data) {
      return { type: "welcome" };
    }

    // If no phase param but has Phase 1 data, go to Phase 1
    if (!phase && hasPhase1Data) {
      return { type: "phase1", step: "units" };
    }

    // Default to welcome
    return { type: "welcome" };
  }, [searchParams, hasPhase1Data, hasPhase2Data, checkingPhase1, checkingPhase2]);

  // Navigate to a new state
  const navigate = (state: AdmissionConfigState, replace = false) => {
    const url = stateToUrl(state);
    if (replace) {
      router.replace(url);
    } else {
      router.push(url);
    }
  };

  return {
    currentState,
    navigate,
    isLoading: checkingPhase1 || checkingPhase2,
    hasPhase1Data: hasPhase1Data || false,
    hasPhase2Data: hasPhase2Data || false,
  };
}
