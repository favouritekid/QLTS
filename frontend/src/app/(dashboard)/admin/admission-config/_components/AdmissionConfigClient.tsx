/**
 * AdmissionConfigClient Component
 *
 * Main client component orchestrating the admission config state machine
 * Renders appropriate content based on current state:
 * - WelcomeScreen: First-time setup
 * - Phase1Content: Master data management
 * - Phase2Content: Program management
 * - QuotaMatrixOverview: unified Phase 3 admission path configuration
 *
 * Mobile Responsive:
 * - Desktop (lg+): Sidebar always visible
 * - Mobile (<lg): Sidebar hidden, accessible via Sheet drawer
 */

"use client";

import { useState } from "react";
import { useAdmissionConfigState } from "@/hooks/admissions/useAdmissionConfigState";
import { PhaseNavigator } from "./PhaseNavigator";
import { WelcomeScreen } from "./WelcomeScreen";
import { OrganizationUnitPanel } from "./Phase1Master/OrganizationUnitPanel";
import { OfferingTypePanel } from "./Phase1Master/OfferingTypePanel";
import { AdmissionMethodPanel } from "./Phase1Master/AdmissionMethodPanel";
import { DocumentTypePanel } from "./Phase1Master/DocumentTypePanel";
import { SubjectGroupPanel } from "./Phase1Master/SubjectGroupPanel";
import { RoundsManagementTab } from "./Phase1Master/RoundsManagementTab";  // Phase 2 v8.2 PR-2A v2
import { MajorProgramPanel } from "./Phase2Program/MajorProgramPanel";
import { ProgramOfferingPanel } from "./Phase2Program/ProgramOfferingPanel";
import { AcademicInfoPanel } from "./Phase2Program/AcademicInfoPanel";
import { QuotaMatrixOverview } from "./Phase3Config/QuotaMatrixOverview";  // Phase 2 v8.2 PR-2D.1 v2
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Loader2, Menu } from "lucide-react";

// ============================================
// COMPONENT
// ============================================

export function AdmissionConfigClient() {
  const { currentState, navigate, isLoading } = useAdmissionConfigState();
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

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
    <div className="flex flex-col lg:flex-row min-h-screen">
      {/* Mobile Header with Menu Button */}
      <div className="lg:hidden sticky top-0 z-40 flex items-center gap-3 border-b bg-background px-4 py-3">
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9"
          onClick={() => setIsMobileNavOpen(true)}
          aria-label="Mở menu điều hướng"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold font-display">Cấu hình Tuyển sinh</h1>
          <p className="text-xs text-muted-foreground">
            {currentState.type === "phase1" && "Giai đoạn 1: Dữ liệu Danh mục"}
            {currentState.type === "phase2" && "Giai đoạn 2: Chương trình"}
            {currentState.type === "quota-matrix-overview" && "Giai đoạn 3: Cấu hình"}
          </p>
        </div>
      </div>

      {/* Mobile Navigation Sheet */}
      <Sheet open={isMobileNavOpen} onOpenChange={setIsMobileNavOpen}>
        <SheetContent side="left" className="w-[85vw] max-w-[300px] p-0">
          <SheetHeader className="sr-only">
            <SheetTitle>Menu điều hướng</SheetTitle>
          </SheetHeader>
          <PhaseNavigator
            currentState={currentState}
            onNavigate={navigate}
            onClose={() => setIsMobileNavOpen(false)}
            className="w-full border-r-0 h-full"
          />
        </SheetContent>
      </Sheet>

      {/* Desktop Sidebar Navigator - Hidden on mobile */}
      <div className="hidden lg:block">
        <PhaseNavigator
          currentState={currentState}
          onNavigate={navigate}
        />
      </div>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto">
        <div className="p-4 md:p-6 lg:p-8">
          {/* Phase 1: Master Data */}
          {currentState.type === "phase1" && (
            <Phase1Content step={currentState.step} />
          )}

          {/* Phase 2: Programs */}
          {currentState.type === "phase2" && (
            <Phase2Content step={currentState.step} />
          )}

          {/* Phase 2 v8.2 PR-2D.1 v2 — Quota Matrix overview (no context) */}
          {currentState.type === "quota-matrix-overview" && (
            <QuotaMatrixOverview
              academicYear={currentState.academicYear}
              onYearChange={(year) =>
                navigate({
                  type: "quota-matrix-overview",
                  academicYear: year,
                  academicInfoId: currentState.academicInfoId,
                })
              }
              onBack={() => navigate({ type: "welcome" })}
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
    case "rounds":
      return <RoundsManagementTab />;
    default:
      return (
        <div className="space-y-6">
          <div>
            <h1 className="text-3xl font-bold font-display">Giai đoạn 1: Dữ liệu Danh mục</h1>
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
            <h1 className="text-3xl font-bold font-display">Giai đoạn 2: Chương trình Đào tạo</h1>
            <p className="text-muted-foreground mt-2">
              Unknown step: {step}
            </p>
          </div>
        </div>
      );
  }
}
