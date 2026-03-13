// src/app/(dashboard)/dashboard/officer/_components/OfficerDashboardClient.tsx
"use client";

import { useState, useRef, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, Info, BarChart3, Table2 } from "lucide-react";
import { WorkloadCard } from "@/components/officer/WorkloadCard";

// Dynamic imports for heavy chart components
const FunnelChart = dynamic(
  () => import("@/components/officer/FunnelChart").then((m) => m.FunnelChart),
  {
    ssr: false,
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
  }
);

const FunnelTable = dynamic(
  () => import("@/components/officer/FunnelTable").then((m) => m.FunnelTable),
  {
    ssr: false,
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
  }
);

const PerformanceChart = dynamic(
  () => import("@/components/officer/PerformanceChart").then((m) => m.PerformanceChart),
  {
    ssr: false,
    loading: () => <Skeleton className="h-80 w-full rounded-lg" />,
  }
);
import { TodaySchedule } from "@/components/officer/TodaySchedule";
import {
  KPICardsGrid,
  ActionInsightsPanel,
  WeeklyLeaderboard,
  SmartHeader,
  AnnualProgressCard,
  MonthlyBreakdownCard,
} from "@/components/officer/dashboard";
import { DashboardDateProvider } from "@/contexts/DashboardDateContext";
import { useDashboardStats, useOfficerKpiPlan, type DashboardScope, type EnhancedOfficerStats } from "@/hooks/useDashboardStats";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "sonner";

// =============================================================================
// INNER CONTENT (must be inside DashboardDateProvider to use useDashboardDate)
// =============================================================================

function DashboardContent({ initialStats }: { initialStats?: EnhancedOfficerStats }) {
  // Get user to determine default scope
  const { user } = useAuth();

  // Resolve scope from user role (null if user not yet hydrated)
  const resolvedScope: DashboardScope | null = user
    ? (
      user.role === "admin"
        ? "organization"
        : user.role === "manager"
          ? "team"
          : user.role === "officer"
            ? "personal"
            : null
    )
    : null;

  const [scope, setScope] = useState<DashboardScope | null>(null);
  const prevResolvedRef = useRef<DashboardScope | null>(null);

  // Sync scope from role during render (no useEffect needed)
  if (resolvedScope !== prevResolvedRef.current) {
    prevResolvedRef.current = resolvedScope;
    setScope(resolvedScope);
  }

  // Secondary filter states
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(null);
  const [selectedOfficerId, setSelectedOfficerId] = useState<number | null>(null);

  // Funnel view mode: "chart" (visual) or "table" (tabular)
  const [funnelViewMode, setFunnelViewMode] = useState<"chart" | "table">("chart");

  // Pass scope and filter options to useDashboardStats hook
  const { stats, teamStats, isLoading, error, refetch } = useDashboardStats({
    scope: scope ?? "personal",
    officerId: selectedOfficerId ?? undefined,
    unitId: selectedUnitId ?? undefined,
    initialData: scope === "personal" ? initialStats : undefined,
    enabled: !!scope,
  });

  // === Gap 2: Monthly KPI Plan ===
  // personal → always fetch; team/org → only when drilled down to a specific officer
  const currentFiscalYear = new Date().getFullYear();
  const shouldFetchKpiPlan = scope === "personal" || (!!scope && !!selectedOfficerId);
  const kpiPlanQuery = useOfficerKpiPlan({
    fiscalYear: currentFiscalYear,
    officerId: selectedOfficerId ?? undefined,
    enabled: shouldFetchKpiPlan,
  });

  // === HOOKS (must be before any early returns — Rules of Hooks) ===
  const router = useRouter();
  const handleQuickAction = useCallback((action: "new_lead" | "log_call" | "schedule") => {
    switch (action) {
      case "new_lead":
        router.push("/leads?action=create");
        break;
      case "log_call":
        toast.info("Tính năng đang phát triển");
        break;
      case "schedule":
        toast.info("Tính năng đang phát triển");
        break;
    }
  }, [router]);

  // === DATA TRANSFORMERS ===
  const performanceTrends = useMemo(() => (stats?.performance_trends ?? []).map((t) => ({
    date: t.date,
    leads_assigned: t.assigned,
    consultations: t.consultations,
    converted: t.converted,
    enrolled: t.enrolled ?? 0,
    lost: t.lost ?? 0,
  })), [stats?.performance_trends]);

  const salesFunnel = useMemo(() => (stats?.sales_funnel ?? []).map((s) => ({
    stage_id: s.stage_id,
    stage_name: s.stage_name,
    stage_order: s.stage_order,
    lead_count: s.lead_count,
    is_final_stage: s.is_final_stage,
    conversion_rate: s.conversion_rate,
    outcome_breakdown: s.outcome_breakdown,
    early_exit_count: s.early_exit_count,
    move_forward: s.move_forward,
    loss_breakdown: s.loss_breakdown,
    velocity: s.velocity,
    estimated_lost_revenue: s.estimated_lost_revenue,
  })), [stats?.sales_funnel]);

  const isUnsupportedRole = !!user && resolvedScope === null;

  if (isUnsupportedRole) {
    return (
      <div className="container mx-auto px-4 py-4 md:p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Không có quyền truy cập</AlertTitle>
          <AlertDescription>
            Vai trò của bạn không được phép truy cập Performance Dashboard.
          </AlertDescription>
        </Alert>
      </div>
    );
  }
  // Guard: show skeleton until scope is determined
  if (!scope) {
    return (
      <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <Skeleton className="h-10 w-full sm:w-64" />
          <Skeleton className="h-10 w-full sm:w-80" />
        </div>
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

  // Phase 2: Funnel suggestions
  const funnelSuggestions = stats.funnel_suggestions ?? [];
  const funnelNetConversionTrend = stats.funnel_net_conversion_trend ?? null;

  // Calculate if daily goal is met for sparkle icon
  const isGoalMet = stats.kpis.consultations_target > 0 &&
    stats.kpis.consultations_today >= stats.kpis.consultations_target;

  return (
    <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
      {/* Header with Date Range Filter, Scope Filter, and Secondary Filters */}
      <SmartHeader
        isGoalMet={isGoalMet}
        onQuickAction={handleQuickAction}
        scope={scope!}
        onScopeChange={(s) => setScope(s)}
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

      {/* Row 1: Charts + Compact Info Cards */}
      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1fr_350px]">
        {/* Left — Analytics charts */}
        <div className="grid gap-4 md:gap-6 md:grid-cols-2">
          <PerformanceChart
            trends={performanceTrends}
            dailyGoal={stats.kpis.consultations_target}
            teamAverage={scope === "personal" ? teamStats?.team_avg_consultations : undefined}
          />
          {/* Funnel Visualization with View Toggle */}
          <div className="space-y-2">
            {/* View Mode Toggle */}
            <div className="flex justify-end">
              <div className="inline-flex items-center rounded-lg border bg-muted p-1 text-muted-foreground">
                <button
                  onClick={() => setFunnelViewMode("chart")}
                  className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    funnelViewMode === "chart"
                      ? "bg-background text-foreground shadow-sm"
                      : "hover:bg-background/50"
                  }`}
                >
                  <BarChart3 className="h-4 w-4" />
                  <span className="hidden sm:inline">Biểu đồ</span>
                </button>
                <button
                  onClick={() => setFunnelViewMode("table")}
                  className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    funnelViewMode === "table"
                      ? "bg-background text-foreground shadow-sm"
                      : "hover:bg-background/50"
                  }`}
                >
                  <Table2 className="h-4 w-4" />
                  <span className="hidden sm:inline">Bảng</span>
                </button>
              </div>
            </div>

            {/* Funnel View */}
            {funnelViewMode === "chart" ? (
              <FunnelChart
                funnel={salesFunnel}
                netConversionTrend={funnelNetConversionTrend}
                scope={scope}
                unitId={selectedUnitId}
                officerId={selectedOfficerId}
                suggestions={funnelSuggestions}
              />
            ) : (
              <FunnelTable
                funnel={salesFunnel}
                scope={scope}
                unitId={selectedUnitId}
                officerId={selectedOfficerId}
                suggestions={funnelSuggestions}
              />
            )}
          </div>
        </div>

        {/* Right — Compact info cards */}
        <div className="space-y-4 md:space-y-6">
          {(scope === "personal" || stats.annual_progress) && (
            <AnnualProgressCard progress={stats.annual_progress} />
          )}
          <WorkloadCard statusOverview={stats.status_overview} scope={scope} />
          <TodaySchedule scope={scope} unitId={selectedUnitId} officerId={selectedOfficerId} />
        </div>
      </div>

      {/* Gap 2: Monthly KPI Plan Breakdown (full-width, collapsed default) */}
      {shouldFetchKpiPlan && (
        <>
          {kpiPlanQuery.error && !kpiPlanQuery.isLoading && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Không thể tải kế hoạch KPI tháng.
                <button onClick={() => kpiPlanQuery.refetch()} className="ml-4 underline">
                  Thử lại
                </button>
              </AlertDescription>
            </Alert>
          )}
          <MonthlyBreakdownCard
            plan={kpiPlanQuery.data}
            isLoading={kpiPlanQuery.isLoading}
          />
        </>
      )}

      {/* Row 2: Action Panels */}
      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1fr_350px]">
        {/* Left — Action Insights (wider, more room for cards) */}
        <ActionInsightsPanel actions={stats.priority_actions} scope={scope ?? undefined} officerId={selectedOfficerId} />
        {/* Right — Leaderboard */}
        <WeeklyLeaderboard scope={scope} unitId={selectedUnitId} officerId={selectedOfficerId} />
      </div>
    </div>
  );
}

// =============================================================================
// EXPORT (wraps content with DashboardDateProvider)
// =============================================================================

interface OfficerDashboardClientProps {
  initialStats?: EnhancedOfficerStats;
}

export function OfficerDashboardClient({ initialStats }: OfficerDashboardClientProps) {
  return (
    <DashboardDateProvider defaultPreset="7d">
      <DashboardContent initialStats={initialStats} />
    </DashboardDateProvider>
  );
}
