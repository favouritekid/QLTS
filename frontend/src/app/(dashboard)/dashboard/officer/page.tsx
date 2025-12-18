// src/app/(dashboard)/dashboard/officer/page.tsx
"use client";

import { useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { WorkloadCard } from "@/components/officer/WorkloadCard";
import { PerformanceChart } from "@/components/officer/PerformanceChart";
import { FunnelChart } from "@/components/officer/FunnelChart";
import { TodaySchedule } from "@/components/officer/TodaySchedule";
import { 
  KPICardsGrid, 
  PriorityActionsPanel, 
  WeeklyLeaderboard, 
  SmartHeader
} from "@/components/officer/dashboard";
import { DashboardDateProvider } from "@/contexts/DashboardDateContext";
import { useDashboardStats, type DashboardScope } from "@/hooks/useDashboardStats";
import { api } from "@/lib/api/client";
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
  // Scope state for manager/admin view switching
  const [scope, setScope] = useState<DashboardScope>("personal");
  
  // Pass scope to useDashboardStats hook
  const { stats, teamStats, isLoading, error, refetch } = useDashboardStats({ scope });

  // === LOADING STATE ===
  if (isLoading) {
    return (
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-10 w-80" />
        </div>

        {/* KPI Cards Skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
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
      <div className="container mx-auto p-6">
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
    <div className="container mx-auto p-6 space-y-6">
      {/* Header with Date Range Filter and Scope Filter */}
      <SmartHeader
        isGoalMet={isGoalMet}
        onQuickAction={handleQuickAction}
        scope={scope}
        onScopeChange={setScope}
      />

      {/* KPI Cards Row */}
      <KPICardsGrid kpis={stats.kpis} />

      {/* Main Content: Bento Grid 75/25 */}
      <div className="grid gap-6 lg:grid-cols-[1fr_350px]">
        {/* Left Column - Charts */}
        <div className="space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <PerformanceChart 
              trends={performanceTrends} 
              teamAverage={teamStats?.team_avg_consultations}
            />
            <FunnelChart funnel={salesFunnel} />
          </div>
        </div>

        {/* Right Column - Action Center */}
        <div className="space-y-6">
          <WorkloadCard statusOverview={stats.status_overview} />
          <TodaySchedule />
          <PriorityActionsPanel actions={stats.priority_actions} />
          <WeeklyLeaderboard />
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
