// src/app/(dashboard)/dashboard/officer/page.tsx
"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, Info } from "lucide-react";
import { WorkloadCard } from "@/components/officer/WorkloadCard";

// ✅ PERFORMANCE: Dynamic import for FunnelChart with complex SVG rendering (~30KB)
// This defers loading until the component is actually rendered
const FunnelChart = dynamic(
  () => import("@/components/officer/FunnelChart").then((m) => m.FunnelChart),
  {
    ssr: false,
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
  }
);

// ✅ PERFORMANCE: Dynamic import for heavy recharts component (~150KB)
// This defers loading until the component is actually rendered
const PerformanceChart = dynamic(
  () => import("@/components/officer/PerformanceChart").then((m) => m.PerformanceChart),
  {
    ssr: false, // recharts doesn't support SSR well
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
  }
);
import { TodaySchedule } from "@/components/officer/TodaySchedule";
import { 
  KPICardsGrid, 
  PriorityActionsPanel, 
  WeeklyLeaderboard, 
  SmartHeader,
  RecommendationsPanel,
  AnnualProgressCard
} from "@/components/officer/dashboard";
import { DashboardDateProvider } from "@/contexts/DashboardDateContext";
import { useDashboardStats, type DashboardScope } from "@/hooks/useDashboardStats";
import { api } from "@/lib/api/client";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "sonner";

/**
 * Officer Command Center - Enhanced Dashboard for officers
 *
 * Features:
 * - Date Range Filter for all dashboard data
 * - KPI Cards with trends
 * - Priority Actions
 * - Real-time stats with Socket.IO updates
 * - Performance trends
 * - Sales funnel visualization
 * - Scope filter for manager/admin (Phase 3)
 */

// =============================================================================
// INNER CONTENT (must be inside DashboardDateProvider to use useDashboardDate)
// =============================================================================

function DashboardContent() {
  // Get user to determine default scope
  const { user } = useAuth();

  // Default scope based on role: admin/manager see "organization"/"team", officers see "personal"
  const getDefaultScope = (): DashboardScope => {
    if (user?.role === "admin") return "organization";
    if (user?.role === "manager") return "team";
    return "personal";
  };

  // Scope state for manager/admin view switching
  const [scope, setScope] = useState<DashboardScope>(getDefaultScope);

  // Secondary filter states
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [selectedOfficerId, setSelectedOfficerId] = useState<number | null>(null);

  // Pass scope and filter options to useDashboardStats hook
  const { stats, teamStats, isLoading, error, refetch } = useDashboardStats({
    scope,
    officerId: selectedOfficerId ?? undefined,
    unitId: selectedUnitId ?? undefined,
  });

  // === LOADING STATE ===
  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <Skeleton className="h-10 w-full sm:w-64" />
          <Skeleton className="h-10 w-full sm:w-80" />
        </div>

        {/* KPI Cards Skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  // === ERROR STATE ===
  if (error) {
    return (
      <div className="container mx-auto px-4 py-4 md:p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Không thể tải thống kê dashboard. Vui lòng thử lại.
            <button
              onClick={() => refetch()}
              className="ml-4 underline"
            >
              Thử lại
            </button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  // === CHECK FOR EMPTY DATA (unit with no officers/leads) ===
  const isEmptyData =
    stats.kpis.active_leads === 0 &&
    stats.kpis.consultations_today === 0 &&
    (stats.sales_funnel ?? []).length === 0 &&
    (stats.performance_trends ?? []).length === 0;

  // === DATA TRANSFORMERS ===
  const performanceTrends = (stats.performance_trends ?? []).map((t) => ({
    date: t.date,
    leads_assigned: t.assigned,
    consultations: t.consultations,
    converted: t.converted,
  }));

  const salesFunnel = (stats.sales_funnel ?? []).map((s) => ({
    stage_id: s.stage_id,
    stage_name: s.stage_name,
    stage_order: s.stage_order,
    lead_count: s.lead_count,
    is_final_stage: s.is_final_stage,
    conversion_rate: s.conversion_rate,
    outcome_breakdown: s.outcome_breakdown,
    // SPEC 2026-02-04: Early Exit metrics
    early_exit_count: s.early_exit_count,
    move_forward: s.move_forward,
  }));

  // Quick action handler
  const handleQuickAction = (action: "new_lead" | "log_call" | "schedule") => {
    switch (action) {
      case "new_lead":
        window.location.href = "/leads?action=create";
        break;
      case "log_call":
        toast.info("Tính năng đang phát triển");
        break;
      case "schedule":
        toast.info("Tính năng đang phát triển");
        break;
    }
  };

  // Calculate if daily goal is met for sparkle icon
  const isGoalMet = stats.kpis.consultations_target > 0 && 
    stats.kpis.consultations_today >= stats.kpis.consultations_target;

  return (
    <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
      {/* Header with Date Range Filter, Scope Filter, and Secondary Filters */}
      <SmartHeader
        isGoalMet={isGoalMet}
        onQuickAction={handleQuickAction}
        scope={scope}
        onScopeChange={setScope}
        selectedOfficerId={selectedOfficerId}
        onOfficerChange={setSelectedOfficerId}
        selectedUnitId={selectedUnitId}
        onUnitChange={setSelectedUnitId}
      />

      {/* KPI Cards Row */}
      <KPICardsGrid kpis={stats.kpis} />

      {/* Empty Data Message */}
      {isEmptyData && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>Không có dữ liệu</AlertTitle>
          <AlertDescription>
            {scope === "organization" && selectedUnitId
              ? "Đơn vị được chọn chưa có nhân viên hoặc chưa có lead nào được phân công."
              : scope === "team"
                ? "Đội nhóm của bạn chưa có nhân viên hoặc chưa có lead nào."
                : "Chưa có dữ liệu trong khoảng thời gian được chọn."}
          </AlertDescription>
        </Alert>
      )}

      {/* Main Content: Bento Grid 75/25 */}
      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1fr_350px]">
        {/* Left Column - Charts + Recommendations */}
        <div className="space-y-4 md:space-y-6">
          <div className="grid gap-4 md:gap-6 md:grid-cols-2">
            <PerformanceChart 
              trends={performanceTrends} 
              dailyGoal={stats.kpis.consultations_target}
              teamAverage={teamStats?.team_avg_consultations}
            />
            <FunnelChart
              funnel={salesFunnel}
              scope={scope}
              unitId={selectedUnitId}
              officerId={selectedOfficerId}
            />
          </div>
          {/* Phase 7: Recommendations Panel */}
          <RecommendationsPanel />
        </div>

        {/* Right Column - Action Center */}
        <div className="space-y-4 md:space-y-6">
          {/* Phase 6: Annual Progress */}
          <AnnualProgressCard progress={stats.annual_progress} />
          <WorkloadCard statusOverview={stats.status_overview} />
          <TodaySchedule />
          <PriorityActionsPanel actions={stats.priority_actions} />
          <WeeklyLeaderboard scope={scope} unitId={selectedUnitId} />
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// PAGE EXPORT (wraps content with DashboardDateProvider)
// =============================================================================

export default function OfficerDashboardPage() {
  return (
    <DashboardDateProvider defaultPreset="7d">
      <DashboardContent />
    </DashboardDateProvider>
  );
}
