// src/app/(dashboard)/dashboard/officer/_components/OfficerDashboardClient.tsx
"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
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
  CurrentMonthSnapshot,
  KpiSummaryBanner,
} from "@/components/officer/dashboard";
import { DashboardDateProvider, useDashboardDate } from "@/contexts/DashboardDateContext";
import { useDashboardStats, useOfficerKpiPlan, type DashboardScope, type EnhancedOfficerStats } from "@/hooks/useDashboardStats";
import { useAuth } from "@/hooks/useAuth";
import { useHasMounted } from "@/hooks/useHasMounted";

// =============================================================================
// INNER CONTENT (must be inside DashboardDateProvider to use useDashboardDate)
// =============================================================================

/** Read a URL search param from the current browser URL (SSR-safe) */
function getUrlParam(key: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(key);
}

const VALID_SCOPES: DashboardScope[] = ["personal", "unit", "organization"];

function DashboardContent({ initialStats }: { initialStats?: EnhancedOfficerStats }) {
  const navRouter = useRouter();

  // Helper to update search params via pushState for back/forward support.
  const updateSearchParams = useCallback((updates: Record<string, string | null>) => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") {
        params.delete(key);
      } else {
        params.set(key, value);
      }
    }
    const qs = params.toString();
    const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.pushState({ _dashboardFilters: true }, "", newUrl);
  }, []);

  // Get user to determine default scope.
  // hasMounted gates role-aware branches so first client render aligns
  // with SSR (both render `!user || !hasMounted` skeleton path), even
  // when `useAuth().user` returns a persisted accountant/user/other
  // unsupported role on the client. Anchor: `useHasMounted.ts` JSDoc
  // + PR #324 Commit 1 Known Limitation closed by PR #325.
  const { user } = useAuth();
  const hasMounted = useHasMounted();

  // Resolve scope from user role (null if user not yet hydrated)
  const resolvedScope: DashboardScope | null = user
    ? (
      user.role === "admin"
        ? "organization"
        : user.role === "manager"
          ? "unit"
          : user.role === "officer"
            ? "personal"
            : null
    )
    : null;

  // Read initial filter state from URL (lazy init, only runs on mount)
  const initialUrlScope = useMemo<DashboardScope | null>(() => {
    let urlScope = getUrlParam("scope");
    if (urlScope === "team") urlScope = "unit";
    return urlScope && VALID_SCOPES.includes(urlScope as DashboardScope)
      ? (urlScope as DashboardScope)
      : null;
  }, []);

  // ⚠ HYDRATION-CRITICAL: useState init MUST be `null` (neutral default),
  // not derived from Zustand persist store. Reading `resolvedScope` (which
  // reads `useAuth().user.role`) at init time causes mismatch:
  //   - SSR: localStorage undefined → user=null → resolvedScope=null → scope=null
  //   - Client first render: Zustand persist rehydrate sync BEFORE React render
  //     → user=persisted → resolvedScope="organization"/"unit"/"personal"
  //     → scope=resolved → renders different element tree vs SSR
  // The !scope skeleton guard below + useEffect resolution (rAF) below keep
  // first client render identical to SSR; scope settles post-mount.
  // Anchor: `auth.store.ts:79-87` onRehydrateStorage sync.
  const [scope, setScope] = useState<DashboardScope | null>(null);

  // Secondary filter states — initialized from URL.
  // NOTE: getUrlParam() returns null on SSR (no window). Safe because the
  // `!scope` skeleton guard below blocks rendering until useEffect resolves
  // scope, and on SSR scope is also null. If that guard is removed, move
  // these initializers to useEffect to avoid hydration mismatch.
  const [selectedUnitId, setSelectedUnitId] = useState<number | null>(() => {
    const raw = getUrlParam("unit");
    if (!raw) return null;
    const parsed = parseInt(raw, 10);
    return isNaN(parsed) ? null : parsed;
  });
  const [selectedOfficerId, setSelectedOfficerId] = useState<number | null>(() => {
    const raw = getUrlParam("officer");
    if (!raw) return null;
    const parsed = parseInt(raw, 10);
    return isNaN(parsed) ? null : parsed;
  });

  // Funnel view mode: "chart" (visual) or "table" (tabular)
  const [funnelViewMode, setFunnelViewMode] = useState<"chart" | "table">(
    () => getUrlParam("funnel") === "table" ? "table" : "chart"
  );

  // Monthly breakdown expanded state — synced to URL
  const [monthlyExpanded, setMonthlyExpanded] = useState<boolean>(
    () => getUrlParam("monthly") === "expanded"
  );

  // Restore filter state on browser back/forward.
  // URL is the source of truth: if a param is absent, reset to default.
  useEffect(() => {
    const handlePopState = () => {
      let urlScope = getUrlParam("scope");
      // Normalize legacy "team" → "unit"
      if (urlScope === "team") urlScope = "unit";
      if (urlScope && VALID_SCOPES.includes(urlScope as DashboardScope)) {
        setScope(urlScope as DashboardScope);
      } else {
        // No scope in URL → reset to role-derived default
        setScope(resolvedScope);
      }
      const rawUnit = getUrlParam("unit");
      setSelectedUnitId(rawUnit ? parseInt(rawUnit, 10) || null : null);
      const rawOfficer = getUrlParam("officer");
      setSelectedOfficerId(rawOfficer ? parseInt(rawOfficer, 10) || null : null);
      setFunnelViewMode(getUrlParam("funnel") === "table" ? "table" : "chart");
      setMonthlyExpanded(getUrlParam("monthly") === "expanded");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [resolvedScope]); // re-bind when role changes

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("scope") !== "team") return;

    params.set("scope", "unit");
    const qs = params.toString();
    const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState({ ...window.history.state, _dashboardFilters: true }, "", newUrl);
  }, []);

  // Post-mount scope resolution: URL param wins; fall back to role-derived
  // default. Defers from useState init to keep first client render identical
  // to SSR (skeleton). rAF schedules the state set after paint so React
  // can finish hydrating before the dashboard tree mounts.
  useEffect(() => {
    if (scope !== null) return;
    const next = initialUrlScope ?? resolvedScope;
    if (next === null) return;
    const frame = window.requestAnimationFrame(() => {
      setScope(next);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initialUrlScope, resolvedScope, scope]);

  const effectiveUnitId = scope === "unit"
    ? (user?.unit_id ?? null)
    : scope === "organization"
      ? selectedUnitId
      : null;
  const includeDescendants = scope === "unit" || (scope === "organization" && effectiveUnitId != null);

  // Pass scope and filter options to useDashboardStats hook
  const { stats, teamStats, isLoading, error, refetch } = useDashboardStats({
    scope: scope ?? "personal",
    officerId: selectedOfficerId ?? undefined,
    unitId: effectiveUnitId ?? undefined,
    initialData: scope === "personal" ? initialStats : undefined,
    enabled: !!scope,
  });

  // === Gap 2: Monthly KPI Plan ===
  // personal → always fetch; team/org → only when drilled down to a specific officer
  // Derive fiscal year from dashboard date range end (not client clock)
  // so that historical range views show the correct plan
  const { endDate: dashEndDate, dateRange: dashDateRange } = useDashboardDate();
  const fiscalYear = dashEndDate ? parseInt(dashEndDate.slice(0, 4), 10) : new Date().getFullYear();
  // Anchor month derived from dashboard end date (for KpiSummaryBanner + CurrentMonthSnapshot)
  const anchorMonth = dashEndDate ? parseInt(dashEndDate.slice(5, 7), 10) : undefined;
  const shouldFetchKpiPlan = scope === "personal" || (!!scope && !!selectedOfficerId);
  const kpiPlanQuery = useOfficerKpiPlan({
    fiscalYear,
    officerId: selectedOfficerId ?? undefined,
    enabled: shouldFetchKpiPlan,
  });

  // === HOOKS (must be before any early returns — Rules of Hooks) ===
  const handleQuickAction = useCallback((action: "new_lead") => {
    switch (action) {
      case "new_lead":
        navRouter.push("/leads?nav_source=dashboard&action=create");
        break;
    }
  }, [navRouter]);

  // === Enrollment pace benchmark (from KPI plan, for PerformanceChart summary) ===
  // Only meaningful when the dashboard date range includes the current month.
  // When viewing historical/custom ranges outside current month, hide the benchmark.
  const enrollmentPace = useMemo(() => {
    if (!kpiPlanQuery.data) return null;
    const now = new Date();
    const currentMonth = now.getMonth() + 1;
    // Guard: only show when date range includes today
    if (dashDateRange?.from && dashDateRange?.to) {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const from = new Date(dashDateRange.from);
      from.setHours(0, 0, 0, 0);
      const to = new Date(dashDateRange.to);
      to.setHours(23, 59, 59, 999);
      if (today < from || today > to) return null;
    }
    const monthData = kpiPlanQuery.data.months.find((m) => m.month === currentMonth);
    if (!monthData) return null;
    const target = monthData.enrollment_target;
    const actual = monthData.enrollment_actual ?? 0;
    const remaining = target - actual;
    if (remaining <= 0) return { pace: 0, onTrack: true, label: `${actual}/${target}` };
    const lastDay = new Date(now.getFullYear(), currentMonth, 0).getDate();
    const daysLeft = Math.max(lastDay - now.getDate(), 1);
    const pace = remaining / daysLeft;
    return { pace, onTrack: actual >= target * (now.getDate() / lastDay), label: `${actual}/${target}` };
  }, [kpiPlanQuery.data, dashDateRange]);

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

  // Gate role-aware Alert behind hasMounted so SSR (user=null → skeleton)
  // and client first render (persisted user=accountant/other → would
  // otherwise show Alert) emit the same tree → no hydration mismatch.
  // Alert fires on the NEXT render after mount effect.
  const isUnsupportedRole = hasMounted && !!user && resolvedScope === null;

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

  // Effective personal view: backend returns personal data when drilling
  // down into a specific officer from team/org scope (officer_service.py:972)
  const effectivePersonalView = scope === "personal" || !!selectedOfficerId;

  // Calculate if daily goal is met for sparkle icon
  // Only meaningful when viewing a range that includes today
  const todayInRange = (() => {
    if (!dashDateRange?.from || !dashDateRange?.to) return true;
    const now = new Date();
    now.setHours(0, 0, 0, 0);
    const from = new Date(dashDateRange.from);
    from.setHours(0, 0, 0, 0);
    const to = new Date(dashDateRange.to);
    to.setHours(23, 59, 59, 999);
    return now >= from && now <= to;
  })();
  const isGoalMet = todayInRange &&
    stats.kpis.consultations_target > 0 &&
    stats.kpis.consultations_today >= stats.kpis.consultations_target;

  return (
    <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
      {/* Header with Date Range Filter, Scope Filter, and Secondary Filters */}
      <SmartHeader
        isGoalMet={isGoalMet}
        onQuickAction={handleQuickAction}
        scope={scope!}
        onScopeChange={(s) => {
          setScope(s);
          setSelectedUnitId(null);
          setSelectedOfficerId(null);
          updateSearchParams({ scope: s, unit: null, officer: null });
        }}
        selectedOfficerId={selectedOfficerId}
        onOfficerChange={(id) => {
          setSelectedOfficerId(id);
          updateSearchParams({ officer: id?.toString() ?? null });
        }}
        selectedUnitId={selectedUnitId}
        onUnitChange={(id) => {
          setSelectedUnitId(id);
          setSelectedOfficerId(null);
          updateSearchParams({ unit: id?.toString() ?? null, officer: null });
        }}
      />

      {/* KPI Summary Banner */}
      <KpiSummaryBanner
        kpis={stats.kpis}
        annualProgress={stats.annual_progress}
        plan={kpiPlanQuery.data}
        anchorMonth={anchorMonth}
        anchorYear={fiscalYear}
        scope={scope}
        officerId={selectedOfficerId}
        unitId={effectiveUnitId}
        includeDescendants={includeDescendants}
      />

      {/* KPI Cards Row */}
      <KPICardsGrid
        kpis={stats.kpis}
        isPersonalView={effectivePersonalView}
        scope={scope}
        officerId={selectedOfficerId}
        unitId={effectiveUnitId}
        includeDescendants={includeDescendants}
      />

      {/* Empty Data Message */}
      {isEmptyData && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>Không có dữ liệu</AlertTitle>
          <AlertDescription>
            {scope === "organization" && selectedUnitId
              ? "Đơn vị được chọn chưa có nhân viên hoặc chưa có lead nào được phân công."
              : scope === "unit"
                ? "Đơn vị của bạn chưa có nhân viên hoặc chưa có lead nào."
                : "Chưa có dữ liệu trong khoảng thời gian được chọn."}
          </AlertDescription>
        </Alert>
      )}

      {/* Row 1: Actions + Operational (action-first, CRM pattern) */}
      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1fr_350px]">
        <ActionInsightsPanel
          actions={stats.priority_actions}
          scope={scope ?? undefined}
          unitId={effectiveUnitId}
          officerId={selectedOfficerId}
          isPersonalView={effectivePersonalView}
        />
        <div className="space-y-4">
          <WorkloadCard statusOverview={stats.status_overview} scope={scope} isPersonalView={effectivePersonalView} />
          <TodaySchedule scope={scope} unitId={effectiveUnitId} officerId={selectedOfficerId} />
        </div>
      </div>

      {/* Row 2: Trend chart + Compact progress cards */}
      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <PerformanceChart
          trends={performanceTrends}
          dailyGoal={stats.kpis.consultations_target}
          teamAverage={effectivePersonalView ? teamStats?.team_avg_consultations : undefined}
          enrollmentPace={enrollmentPace}
        />
        <div className="space-y-4">
          {(scope === "personal" || stats.annual_progress) && (
            <AnnualProgressCard progress={stats.annual_progress} />
          )}
          {shouldFetchKpiPlan && (
            <CurrentMonthSnapshot
              plan={kpiPlanQuery.data}
              isLoading={kpiPlanQuery.isLoading}
              anchorMonth={anchorMonth}
              anchorYear={fiscalYear}
            />
          )}
        </div>
      </div>

      {/* Row 3: Funnel (full-width — highest density component) */}
      <div className="space-y-2">
        <div className="flex justify-end">
          <div className="inline-flex items-center rounded-lg border bg-muted p-1 text-muted-foreground">
            <button
              onClick={() => {
                setFunnelViewMode("chart");
                updateSearchParams({ funnel: null });
              }}
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
              onClick={() => {
                setFunnelViewMode("table");
                updateSearchParams({ funnel: "table" });
              }}
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
        {funnelViewMode === "chart" ? (
          <FunnelChart
            funnel={salesFunnel}
            netConversionTrend={funnelNetConversionTrend}
            scope={scope}
            unitId={effectiveUnitId}
            officerId={selectedOfficerId}
            includeDescendants={includeDescendants}
            suggestions={funnelSuggestions}
          />
        ) : (
          <FunnelTable
            funnel={salesFunnel}
            scope={scope}
            unitId={effectiveUnitId}
            officerId={selectedOfficerId}
            includeDescendants={includeDescendants}
            suggestions={funnelSuggestions}
          />
        )}
      </div>

      {/* Row 4: Monthly KPI Plan (full-width, collapsed) */}
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
            expanded={monthlyExpanded}
            onExpandedChange={(v) => {
              setMonthlyExpanded(v);
              updateSearchParams({ monthly: v ? "expanded" : null });
            }}
          />
        </>
      )}

      {/* Row 5: Leaderboard (supplementary) */}
      <WeeklyLeaderboard scope={scope} unitId={effectiveUnitId} officerId={selectedOfficerId} />
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
