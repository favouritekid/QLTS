// src/app/(dashboard)/dashboard/officer/page.tsx
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { WorkloadCard } from "@/components/officer/WorkloadCard";
import { PerformanceChart } from "@/components/officer/PerformanceChart";
import { FunnelChart } from "@/components/officer/FunnelChart";
import { ActionableLists } from "@/components/officer/ActionableLists";
import { api } from "@/lib/api/client";
import { socket } from "@/lib/socket/client";

/**
 * Officer Command Center - Dashboard for officers
 *
 * Features:
 * - Real-time stats with Socket.IO updates
 * - Performance trends (7 days)
 * - Sales funnel visualization
 * - Actionable lead lists
 * - Availability toggle
 */

interface OfficerStats {
  status_overview: {
    workload: number;
    max_capacity: number;
    utilization: number;
    availability_status: "available" | "busy" | "offline";
    last_assigned_at: string | null;
  };
  performance_trends: Array<{
    date: string;
    leads_assigned: number;
    consultations: number;
    converted: number;
  }>;
  sales_funnel: Array<{
    stage_name: string;
    stage_order: number;
    lead_count: number;
  }>;
  actionable_lists: {
    high_score: Array<{
      id: number;
      full_name: string;
      email: string;
      lead_score: number;
      status: string;
      created_at: string;
    }>;
    stale: Array<{
      id: number;
      full_name: string;
      email: string;
      last_updated: string;
      days_stale: number;
    }>;
    upcoming: Array<{
      id: number;
      lead_id: number;
      lead_name: string;
      consultation_date: string;
      method: string;
      notes: string | null;
    }>;
  };
}

async function fetchOfficerStats(): Promise<OfficerStats> {
  const response = await api.get("/api/officer/stats");
  return response.data;
}

export default function OfficerDashboardPage() {
  const queryClient = useQueryClient();

  // Fetch officer stats
  const {
    data: stats,
    isLoading,
    error,
    refetch
  } = useQuery({
    queryKey: ["officer", "stats"],
    queryFn: fetchOfficerStats,
    refetchInterval: 60000, // Refresh every 60 seconds
    staleTime: 30000, // Consider data stale after 30 seconds
  });

  // === REAL-TIME SOCKET.IO INTEGRATION ===
  useEffect(() => {
    if (!socket.connected) {
      socket.connect();
    }

    // Listen for data update events
    const handleDataUpdate = (data: { resource: string }) => {
      // Invalidate queries when leads or consultations are updated
      if (data.resource === "lead" || data.resource === "consultation") {
        queryClient.invalidateQueries({ queryKey: ["officer", "stats"] });
        console.log("Officer stats invalidated due to:", data.resource);
      }
    };

    // Listen for lead reassignment events
    const handleLeadReassigned = () => {
      queryClient.invalidateQueries({ queryKey: ["officer", "stats"] });
      console.log("Officer stats invalidated due to lead reassignment");
    };

    socket.on("data_updated", handleDataUpdate);
    socket.on("lead_reassigned", handleLeadReassigned);
    socket.on("lead_transferred_in", handleLeadReassigned);

    return () => {
      socket.off("data_updated", handleDataUpdate);
      socket.off("lead_reassigned", handleLeadReassigned);
      socket.off("lead_transferred_in", handleLeadReassigned);
    };
  }, [queryClient]);

  // === LOADING STATE ===
  if (isLoading) {
    return (
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-10 w-64" />
        </div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
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
            Failed to load dashboard statistics. Please try again later.
            <button
              onClick={() => refetch()}
              className="ml-4 underline"
            >
              Retry
            </button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Officer Dashboard</h1>
          <p className="text-muted-foreground">
            Track your performance and manage your leads
          </p>
        </div>
      </div>

      {/* Workload Overview */}
      <WorkloadCard statusOverview={stats.status_overview} />

      {/* Performance and Funnel Charts */}
      <div className="grid gap-6 md:grid-cols-2">
        <PerformanceChart trends={stats.performance_trends} />
        <FunnelChart funnel={stats.sales_funnel} />
      </div>

      {/* Actionable Lists */}
      <ActionableLists lists={stats.actionable_lists} />
    </div>
  );
}
