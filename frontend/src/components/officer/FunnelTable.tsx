// src/components/officer/FunnelTable.tsx
/**
 * FunnelTable - Tabular view of Pipeline Funnel Analytics
 *
 * A cleaner, more scannable alternative to FunnelChart.
 * Displays funnel metrics in a structured table format.
 *
 * Features:
 * - Stage-by-stage metrics in rows
 * - Clear columns for Leads, Conversion, Velocity, Lost Revenue
 * - Expandable loss breakdown per stage
 * - Separate suggestions panel
 */
"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useDashboardDate } from "@/contexts/DashboardDateContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
// Note: Not using Collapsible inside table as it renders <div> which is invalid in <tbody>
// Using conditional rendering with state instead
import { cn } from "@/lib/utils";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  DollarSign,
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  ExternalLink,
  Users,
  Target,
  XCircle,
} from "lucide-react";

// ============================================================================
// INTERFACES (same as FunnelChart for compatibility)
// ============================================================================

interface OutcomeBreakdown {
  positive: number;
  negative: number;
  neutral: number;
}

interface LossBreakdownItem {
  reason_code: string;
  count: number;
  percentage: number;
}

interface VelocityStats {
  avg_days: number;
  min_days: number;
  max_days: number;
  sample_size: number;
}

interface EstimatedLostRevenue {
  lost_leads_count: number;
  avg_tuition: number;
  total_lost_revenue: number;
  leads_with_tuition: number;
}

interface FunnelSuggestion {
  id: string;
  type: "bottleneck" | "slow_stage" | "high_loss" | "loss_reason";
  priority: "critical" | "high" | "medium" | "low";
  stage_id?: string | null;
  stage_name?: string | null;
  title: string;
  description: string;
  metric_value?: number | null;
  metric_label?: string | null;
  action_label?: string | null;
  action_url?: string | null;
}

interface FunnelStage {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  lead_count: number;
  is_final_stage?: boolean;
  conversion_rate?: number | null;
  outcome_breakdown?: OutcomeBreakdown;
  early_exit_count?: number;
  move_forward?: number;
  loss_breakdown?: LossBreakdownItem[] | null;
  velocity?: VelocityStats | null;
  estimated_lost_revenue?: EstimatedLostRevenue | null;
}

interface FunnelTableProps {
  funnel: FunnelStage[];
  suggestions?: FunnelSuggestion[];
  scope?: "personal" | "team" | "organization";
  unitId?: number | null;
  officerId?: number | null;
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

// Positive/Negative outcome IDs from pipeline_stage.csv seed data
const POSITIVE_STAGE_IDS = ["stg06"];  // "Đã nhập học"
const NEGATIVE_STAGE_IDS = ["stg07"];  // "Không đi học"

/**
 * Determine if a final stage is positive outcome.
 * Mirrors FunnelChart's isPositiveOutcome logic (config IDs → heuristics → outcome_breakdown).
 */
const isPositiveOutcomeStage = (stage: FunnelStage): boolean => {
  // 1. Check configured IDs
  if (POSITIVE_STAGE_IDS.includes(stage.stage_id)) return true;
  if (NEGATIVE_STAGE_IDS.includes(stage.stage_id)) return false;

  // 2. Heuristics based on Vietnamese stage names
  const nameLower = stage.stage_name.toLowerCase();
  if (nameLower.includes("nhập học") || nameLower.includes("hoàn thành") || nameLower.includes("thành công")) return true;
  if (nameLower.includes("không") || nameLower.includes("từ chối") || nameLower.includes("hủy")) return false;

  // 3. Fallback: outcome breakdown
  if (stage.outcome_breakdown) {
    return stage.outcome_breakdown.positive > stage.outcome_breakdown.negative;
  }

  return false;
};

/** Format VND currency (compact) */
const formatVND = (amount: number): string => {
  if (amount >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)}B`;
  if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(0)}M`;
  if (amount >= 1_000) return `${(amount / 1_000).toFixed(0)}K`;
  return amount.toFixed(0);
};

/** Format VND currency (full) */
const formatVNDFull = (amount: number): string => {
  return new Intl.NumberFormat('vi-VN').format(amount) + ' ₫';
};

/** Loss reason labels */
const LOSS_REASON_LABELS: Record<string, string> = {
  PRICE_HIGH: "Học phí cao",
  LOCATION_FAR: "Xa nhà",
  CHOSE_COMPETITOR: "Chọn trường khác",
  NO_CONTACT: "Không liên lạc được",
  TIMING_BAD: "Chưa sẵn sàng",
  OTHER: "Khác",
};

/** Suggestion type styles */
const SUGGESTION_STYLES: Record<FunnelSuggestion["type"], { icon: string; color: string; bg: string }> = {
  bottleneck: { icon: "\u25B2", color: "text-red-600", bg: "bg-red-50 dark:bg-red-950/30" },
  slow_stage: { icon: "\u25C7", color: "text-amber-600", bg: "bg-amber-50 dark:bg-amber-950/30" },
  high_loss: { icon: "\u25BC", color: "text-rose-600", bg: "bg-rose-50 dark:bg-rose-950/30" },
  loss_reason: { icon: "\u25C9", color: "text-blue-600", bg: "bg-blue-50 dark:bg-blue-950/30" },
};

/** Priority badge styles */
const PRIORITY_STYLES: Record<FunnelSuggestion["priority"], { label: string; variant: "destructive" | "default" | "secondary" | "outline" }> = {
  critical: { label: "Cấp bách", variant: "destructive" },
  high: { label: "Cao", variant: "default" },
  medium: { label: "TB", variant: "secondary" },
  low: { label: "Thấp", variant: "outline" },
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export function FunnelTable({
  funnel,
  suggestions = [],
  scope,
  unitId,
  officerId,
}: FunnelTableProps) {
  const router = useRouter();
  const { startDate, endDate } = useDashboardDate();
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Sort stages by order
  const sortedFunnel = [...funnel].sort((a, b) => a.stage_order - b.stage_order);
  const coreStages = sortedFunnel.filter(s => !s.is_final_stage);
  const outcomeStages = sortedFunnel.filter(s => s.is_final_stage);

  // Calculate totals
  const totalLeads = sortedFunnel.reduce((sum, s) => sum + s.lead_count, 0);
  const totalLostRevenue = sortedFunnel.reduce(
    (sum, s) => sum + (s.estimated_lost_revenue?.total_lost_revenue || 0),
    0
  );
  const totalEarlyExit = coreStages.reduce((sum, s) => sum + (s.early_exit_count || 0), 0);

  // Toggle row expansion
  const toggleRow = (stageId: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(stageId)) {
      newExpanded.delete(stageId);
    } else {
      newExpanded.add(stageId);
    }
    setExpandedRows(newExpanded);
  };

  // Navigate to leads filtered by stage
  const handleStageClick = (stageId: string) => {
    const params = new URLSearchParams();
    params.set("stage", stageId);
    if (startDate) params.set("from", startDate);
    if (endDate) params.set("to", endDate);
    if (officerId) params.set("officer", officerId.toString());
    else if (unitId) params.set("unit_id", unitId.toString());
    router.push(`/leads?${params.toString()}`);
  };

  // Empty state
  if (!funnel || funnel.length === 0) {
    return (
      <Card className="border bg-card">
        <CardContent className="flex items-center justify-center min-h-[200px]">
          <div className="text-center text-muted-foreground">
            <Target className="h-10 w-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">Chưa có dữ liệu Pipeline</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* === MAIN TABLE === */}
      <Card className="border bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <Target className="h-4 w-4" />
              Pipeline Analytics
            </CardTitle>
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">
                Tổng: <strong className="text-foreground">{totalLeads}</strong> leads
              </span>
              {totalLostRevenue > 0 && (
                <span className="text-amber-600">
                  Mất: <strong>{formatVND(totalLostRevenue)}</strong>
                </span>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="w-[200px]">Stage</TableHead>
                <TableHead className="text-center w-[100px]">Leads</TableHead>
                <TableHead className="text-center w-[100px]">Conversion</TableHead>
                <TableHead className="text-center w-[100px]">Velocity</TableHead>
                <TableHead className="text-center w-[100px]">Early Exit</TableHead>
                <TableHead className="text-right w-[120px]">Lost Revenue</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {/* Core Stages */}
              {coreStages.map((stage) => {
                const isExpanded = expandedRows.has(stage.stage_id);
                const hasLossBreakdown = stage.loss_breakdown && stage.loss_breakdown.length > 0;
                const conversionRate = stage.conversion_rate;
                const isBottleneck = conversionRate !== null && conversionRate !== undefined && conversionRate < 50;

                return (
                  <React.Fragment key={stage.stage_id}>
                    <TableRow
                      className={cn(
                        "cursor-pointer hover:bg-muted/50 transition-colors",
                        isBottleneck && "bg-red-50/50 dark:bg-red-950/10"
                      )}
                      onClick={() => hasLossBreakdown && toggleRow(stage.stage_id)}
                    >
                      {/* Stage Name */}
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {hasLossBreakdown ? (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-5 w-5 p-0"
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleRow(stage.stage_id);
                              }}
                              aria-label={isExpanded ? "Thu gọn" : "Mở rộng"}
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4" />
                              ) : (
                                <ChevronRight className="h-4 w-4" />
                              )}
                            </Button>
                          ) : (
                            <span className="w-5" />
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStageClick(stage.stage_id);
                            }}
                            className="text-left hover:underline hover:text-primary"
                          >
                            {stage.stage_name}
                          </button>
                          {isBottleneck && (
                            <AlertTriangle className="h-4 w-4 text-red-500" />
                          )}
                        </div>
                      </TableCell>

                      {/* Leads Count */}
                      <TableCell className="text-center">
                        <div className="flex flex-col items-center">
                          <span className="font-semibold tabular-nums">{stage.lead_count}</span>
                          <span className="text-xs text-muted-foreground">
                            {totalLeads > 0 ? ((stage.lead_count / totalLeads) * 100).toFixed(0) : 0}%
                          </span>
                        </div>
                      </TableCell>

                      {/* Conversion Rate */}
                      <TableCell className="text-center">
                        {conversionRate !== null && conversionRate !== undefined ? (
                          <div className="flex items-center justify-center gap-1">
                            {conversionRate >= 70 ? (
                              <TrendingUp className="h-3 w-3 text-green-500" />
                            ) : conversionRate < 50 ? (
                              <TrendingDown className="h-3 w-3 text-red-500" />
                            ) : null}
                            <span
                              className={cn(
                                "font-semibold tabular-nums",
                                conversionRate >= 70 && "text-green-600",
                                conversionRate >= 50 && conversionRate < 70 && "text-amber-600",
                                conversionRate < 50 && "text-red-600"
                              )}
                            >
                              {conversionRate.toFixed(0)}%
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>

                      {/* Velocity */}
                      <TableCell className="text-center">
                        {stage.velocity && stage.velocity.sample_size > 0 ? (
                          <div className="flex items-center justify-center gap-1 text-cyan-600">
                            <Clock className="h-3 w-3" />
                            <span className="font-medium tabular-nums">
                              {stage.velocity.avg_days.toFixed(1)}d
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>

                      {/* Early Exit */}
                      <TableCell className="text-center">
                        {stage.early_exit_count !== undefined && stage.early_exit_count > 0 ? (
                          <div className="flex items-center justify-center gap-1 text-red-500">
                            <XCircle className="h-3 w-3" />
                            <span className="font-medium tabular-nums">
                              {stage.early_exit_count}
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </TableCell>

                      {/* Lost Revenue */}
                      <TableCell className="text-right">
                        {stage.estimated_lost_revenue?.total_lost_revenue ? (
                          <div className="flex items-center justify-end gap-1 text-amber-600">
                            <DollarSign className="h-3 w-3" />
                            <span className="font-medium tabular-nums">
                              {formatVND(stage.estimated_lost_revenue.total_lost_revenue)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>

                    {/* Expanded Row: Loss Breakdown (conditional, no Collapsible) */}
                    {hasLossBreakdown && isExpanded && (
                      <TableRow className="bg-muted/30">
                        <TableCell colSpan={6} className="py-3">
                          <div className="pl-7 space-y-2">
                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                              Lý do mất leads tại stage này:
                            </p>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                              {stage.loss_breakdown!.map((item) => (
                                <div
                                  key={item.reason_code}
                                  className="flex items-center justify-between bg-background rounded px-3 py-2 border"
                                >
                                  <span className="text-sm">
                                    {LOSS_REASON_LABELS[item.reason_code] || item.reason_code}
                                  </span>
                                  <Badge variant="secondary" className="ml-2">
                                    {item.count} ({item.percentage}%)
                                  </Badge>
                                </div>
                              ))}
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}

              {/* Outcome Stages (Final) */}
              {outcomeStages.length > 0 && (
                <>
                  <TableRow className="bg-muted/30">
                    <TableCell colSpan={6} className="py-2">
                      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Kết quả cuối cùng
                      </span>
                    </TableCell>
                  </TableRow>
                  {outcomeStages.map((stage) => {
                    const isPositive = isPositiveOutcomeStage(stage);
                    return (
                      <TableRow
                        key={stage.stage_id}
                        className={cn(
                          "cursor-pointer hover:bg-muted/50",
                          isPositive ? "bg-green-50/50 dark:bg-green-950/10" : "bg-red-50/30 dark:bg-red-950/10"
                        )}
                        onClick={() => handleStageClick(stage.stage_id)}
                      >
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2 pl-7">
                            <span className={isPositive ? "text-green-600" : "text-red-500"}>
                              {isPositive ? "✓" : "✗"}
                            </span>
                            {stage.stage_name}
                          </div>
                        </TableCell>
                        <TableCell className="text-center">
                          <span className={cn(
                            "font-semibold tabular-nums",
                            isPositive ? "text-green-600" : "text-red-500"
                          )}>
                            {stage.lead_count}
                          </span>
                        </TableCell>
                        <TableCell colSpan={4} className="text-center text-muted-foreground">
                          -
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </>
              )}

              {/* Summary Row */}
              <TableRow className="bg-muted font-medium border-t-2">
                <TableCell>
                  <div className="flex items-center gap-2 pl-7">
                    <Users className="h-4 w-4" />
                    Tổng cộng
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  <span className="font-bold tabular-nums">{totalLeads}</span>
                </TableCell>
                <TableCell className="text-center">-</TableCell>
                <TableCell className="text-center">-</TableCell>
                <TableCell className="text-center">
                  {totalEarlyExit > 0 && (
                    <span className="text-red-500 font-semibold">{totalEarlyExit}</span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {totalLostRevenue > 0 && (
                    <span className="text-amber-600 font-semibold">
                      {formatVNDFull(totalLostRevenue)}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* === SUGGESTIONS PANEL === */}
      {suggestions && suggestions.length > 0 && (
        <Card className="border bg-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-amber-500" />
              Gợi ý cải thiện
              <Badge variant="secondary" className="ml-auto">
                {suggestions.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {suggestions.map((suggestion) => {
              const style = SUGGESTION_STYLES[suggestion.type];
              const priorityStyle = PRIORITY_STYLES[suggestion.priority];

              return (
                <div
                  key={suggestion.id}
                  className={cn(
                    "p-4 rounded-lg border transition-colors hover:shadow-sm",
                    style.bg
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-xl shrink-0">{style.icon}</span>
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className={cn("font-medium", style.color)}>
                          {suggestion.title}
                        </h4>
                        <Badge variant={priorityStyle.variant} className="text-xs">
                          {priorityStyle.label}
                        </Badge>
                        {suggestion.stage_name && (
                          <Badge variant="outline" className="text-xs">
                            {suggestion.stage_name}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {suggestion.description}
                      </p>
                      {suggestion.metric_label && (
                        <p className="text-sm font-medium text-foreground">
                          {suggestion.metric_label}
                        </p>
                      )}
                    </div>
                    {suggestion.action_url && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="shrink-0"
                        onClick={() => router.push(suggestion.action_url!)}
                      >
                        {suggestion.action_label || "Xem"}
                        <ExternalLink className="h-3 w-3 ml-1" />
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
