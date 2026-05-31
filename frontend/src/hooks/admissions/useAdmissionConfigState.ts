/**
 * useAdmissionConfigState Hook
 *
 * State machine for Admission Config navigation
 * Manages transitions between Welcome -> Phase1 -> Phase2 -> Phase3
 */

"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type {
  AdmissionConfigState,
  Phase1Step,
  Phase2Step,
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

  if (state.type === "quota-matrix-overview") {
    const params = new URLSearchParams({
      view: "quota-matrix",
      year: state.academicYear.toString(),
    });
    if (state.academicInfoId) {
      params.set("academicInfo", state.academicInfoId.toString());
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

    // Quota Matrix overview (Phase 2 v8.2 PR-2D.1 v2 — global view, no context)
    const viewParam = searchParams.get("view");
    if (viewParam === "quota-matrix") {
      const yearStr = searchParams.get("year");
      const year = yearStr ? parseInt(yearStr, 10) : new Date().getFullYear();
      const academicInfoStr = searchParams.get("academicInfo");
      const academicInfoId = academicInfoStr ? parseInt(academicInfoStr, 10) : undefined;
      return {
        type: "quota-matrix-overview",
        academicYear: year,
        academicInfoId: academicInfoId && academicInfoId > 0 ? academicInfoId : undefined,
      };
    }

    // Legacy Phase 3 URLs now land on the unified quota matrix instead of the
    // removed context/wizard route. A useEffect below replaces the URL.
    if (phase === "3") {
      const yearStr = searchParams.get("year");
      const academicInfoStr = searchParams.get("academicInfo");
      const year = yearStr ? parseInt(yearStr, 10) : new Date().getFullYear();
      const academicInfoId = academicInfoStr ? parseInt(academicInfoStr, 10) : undefined;
      return {
        type: "quota-matrix-overview",
        academicYear: year,
        academicInfoId: academicInfoId && academicInfoId > 0 ? academicInfoId : undefined,
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
  }, [searchParams, hasPhase1Data, checkingPhase1, checkingPhase2]);

  useEffect(() => {
    if (searchParams.get("phase") !== "3") return;
    if (checkingPhase1 || checkingPhase2) return;
    router.replace(stateToUrl(currentState));
  }, [checkingPhase1, checkingPhase2, currentState, router, searchParams]);

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
