/**
 * AdmissionConfigClient Component
 *
 * Main client component orchestrating the admission config state machine
 * Renders appropriate content based on current state:
 * - WelcomeScreen: First-time setup
 * - Phase1Content: Master data management
 * - Phase2Content: Program management
 * - ContextSelector: Context selection for Phase 3
 * - Phase3Content: Admission path configuration
 */

"use client";

import { useAdmissionConfigState } from "@/hooks/admissions/useAdmissionConfigState";
import { PhaseNavigator } from "./PhaseNavigator";
import { WelcomeScreen } from "./WelcomeScreen";
import { OrganizationUnitPanel } from "./Phase1Master/OrganizationUnitPanel";
import { OfferingTypePanel } from "./Phase1Master/OfferingTypePanel";
import { AdmissionMethodPanel } from "./Phase1Master/AdmissionMethodPanel";
import { DocumentTypePanel } from "./Phase1Master/DocumentTypePanel";
import { SubjectGroupPanel } from "./Phase1Master/SubjectGroupPanel";
import { MajorProgramPanel } from "./Phase2Program/MajorProgramPanel";
import { ProgramOfferingPanel } from "./Phase2Program/ProgramOfferingPanel";
import { AcademicInfoPanel } from "./Phase2Program/AcademicInfoPanel";
import { ContextSelector } from "./Phase3Config/ContextSelector";
import { PathsList } from "./Phase3Config/PathsList";
import { CoverageMatrix } from "./Phase3Config/CoverageMatrix";
import { PathWizard } from "./Phase3Config/PathWizard";
import { Loader2 } from "lucide-react";
import type { SelectionContext, Phase3View, AdmissionConfigState } from "./shared/types";

// ============================================
// COMPONENT
// ============================================

export function AdmissionConfigClient() {
  const { currentState, navigate, isLoading } = useAdmissionConfigState();

  // Show loading state while checking data availability
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4 text-primary" />
          <p className="text-muted-foreground">Đang tải cấu hình tuyển sinh...</p>
        </div>
      </div>
    );
  }

  // Welcome screen (no Phase 1 data)
  if (currentState.type === "welcome") {
    return (
      <WelcomeScreen
        onStart={() => navigate({ type: "phase1", step: "units" })}
      />
    );
  }

  // Main layout with sidebar
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar Navigator */}
      <PhaseNavigator
        currentState={currentState}
        onNavigate={navigate}
      />

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto">
        <div className="p-8">
          {/* Phase 1: Master Data */}
          {currentState.type === "phase1" && (
            <Phase1Content step={currentState.step} />
          )}

          {/* Phase 2: Programs */}
          {currentState.type === "phase2" && (
            <Phase2Content step={currentState.step} />
          )}

          {/* Phase 3: Context Selection */}
          {currentState.type === "select-context" && (
            <ContextSelector
              onContextSelected={(context) =>
                navigate({
                  type: "phase3",
                  context,
                  view: { type: "list" },
                })
              }
            />
          )}

          {/* Phase 3: Configuration */}
          {currentState.type === "phase3" && (
            <Phase3Content
              context={currentState.context}
              view={currentState.view}
              navigate={navigate}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// ============================================
// PLACEHOLDER COMPONENTS
// ============================================

function Phase1Content({ step }: { step: string }) {
  switch (step) {
    case "units":
      return <OrganizationUnitPanel />;
    case "offering-types":
      return <OfferingTypePanel />;
    case "methods":
      return <AdmissionMethodPanel />;
    case "document-types":
      return <DocumentTypePanel />;
    case "subject-groups":
      return <SubjectGroupPanel />;
    default:
      return (
        <div className="space-y-6">
          <div>
            <h1 className="text-3xl font-bold">Giai đoạn 1: Dữ liệu Danh mục</h1>
            <p className="text-muted-foreground mt-2">
              Unknown step: {step}
            </p>
          </div>
        </div>
      );
  }
}

function Phase2Content({ step }: { step: string }) {
  switch (step) {
    case "majors":
      return <MajorProgramPanel />;
    case "offerings":
      return <ProgramOfferingPanel />;
    case "academic-info":
      return <AcademicInfoPanel />;
    default:
      return (
        <div className="space-y-6">
          <div>
            <h1 className="text-3xl font-bold">Giai đoạn 2: Chương trình Đào tạo</h1>
            <p className="text-muted-foreground mt-2">
              Unknown step: {step}
            </p>
          </div>
        </div>
      );
  }
}

function Phase3Content({
  context,
  view,
  navigate,
}: {
  context: SelectionContext;
  view: Phase3View;
  navigate: (state: AdmissionConfigState) => void;
}) {
  const handleNavigateView = (newView: Phase3View) => {
    navigate({ type: "phase3", context, view: newView });
  };

  const handleBackToContextSelector = () => {
    navigate({ type: "select-context" });
  };

  if (view.type === "list") {
    return (
      <PathsList
        context={context}
        onNavigate={handleNavigateView}
        onBack={handleBackToContextSelector}
      />
    );
  }

  if (view.type === "matrix") {
    return (
      <CoverageMatrix context={context} onNavigate={handleNavigateView} />
    );
  }

  if (view.type === "wizard") {
    return (
      <PathWizard
        key={view.pathId || "create"} // Remount when switching between paths or create/edit
        context={context}
        pathId={view.pathId}
        onNavigate={handleNavigateView}
      />
    );
  }

  return null;
}
