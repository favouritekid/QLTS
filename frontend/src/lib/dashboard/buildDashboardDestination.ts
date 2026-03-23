import type { DashboardScope } from "@/hooks/useDashboardStats";
import { todayVN } from "@/lib/utils/vn-date";

export type DrillDownTarget = "leads_snapshot" | "consultations" | "transitions" | "cohorts";

export interface LeadsSnapshotDrillDownFilters {
  stage_id?: string;
  status_codes?: string[];
  loss_reason_code?: string;
  is_final?: boolean;
  counts_for_funnel?: boolean;
}

export interface ConsultationsDrillDownFilters {
  stage_id?: string;
  loss_reason_code?: string;
  consultation_kind?: "human" | "system";
  response_breach_only?: boolean;
}

export interface TransitionsDrillDownFilters {
  stage_id?: string;
  outcome?: "positive" | "negative" | "neutral";
  final_only?: boolean;
  consulted_only?: boolean;
}

export interface CohortsDrillDownFilters {
  cohort_result?: "converted" | "lost" | "open";
}

export type LeadsSnapshotMetricKey = "active_leads" | "funnel_stage";
export type ConsultationsMetricKey =
  | "consultations_today"
  | "consultations_avg_per_day"
  | "loss_reason"
  | "avg_response_time";
export type TransitionsMetricKey =
  | "bottleneck"
  | "slow_stage"
  | "high_loss"
  | "win_rate"
  | "enrollments_monthly"
  | "consultation_effectiveness";
export type CohortsMetricKey = "new_lead_conversion";
export type DrillDownMetricKey =
  | LeadsSnapshotMetricKey
  | ConsultationsMetricKey
  | TransitionsMetricKey
  | CohortsMetricKey;

export interface LeadsSnapshotDrillDownDescriptor {
  target: "leads_snapshot";
  exactness: "exact";
  metric_key: LeadsSnapshotMetricKey;
  filters?: LeadsSnapshotDrillDownFilters;
}

export interface ConsultationsDrillDownDescriptor {
  target: "consultations";
  exactness: "exact";
  metric_key: ConsultationsMetricKey;
  filters?: ConsultationsDrillDownFilters;
}

export interface TransitionsDrillDownDescriptor {
  target: "transitions";
  exactness: "exact";
  metric_key: TransitionsMetricKey;
  filters?: TransitionsDrillDownFilters;
}

export interface CohortsDrillDownDescriptor {
  target: "cohorts";
  exactness: "exact";
  metric_key: CohortsMetricKey;
  filters?: CohortsDrillDownFilters;
}

export type DrillDownDescriptor =
  | LeadsSnapshotDrillDownDescriptor
  | ConsultationsDrillDownDescriptor
  | TransitionsDrillDownDescriptor
  | CohortsDrillDownDescriptor;

export interface DashboardDestinationContext {
  scope?: DashboardScope;
  officerId?: number | null;
  unitId?: number | null;
  includeDescendants?: boolean;
  startDate?: string;
  endDate?: string;
  dateField?: string;
}

function appendScalarFilter(
  params: URLSearchParams,
  key: string,
  value: string | boolean | undefined,
) {
  if (value === undefined || value === false) return;
  params.set(key, value === true ? "1" : value);
}

function appendSharedFilters(
  params: URLSearchParams,
  filters: Record<string, string | boolean | undefined>,
) {
  for (const [key, value] of Object.entries(filters)) {
    appendScalarFilter(params, key, value);
  }
}

function appendDescriptorFilters(params: URLSearchParams, descriptor: DrillDownDescriptor) {
  if (!descriptor.filters) return;

  switch (descriptor.target) {
    case "leads_snapshot":
      if (descriptor.filters.stage_id) {
        params.set("stage", descriptor.filters.stage_id);
      }
      if (descriptor.filters.status_codes?.length) {
        params.set("status", descriptor.filters.status_codes.join(","));
      }
      if (descriptor.filters.loss_reason_code) {
        params.set("loss_reason", descriptor.filters.loss_reason_code);
      }
      if (descriptor.filters.is_final !== undefined) {
        params.set("is_final", descriptor.filters.is_final ? "true" : "false");
      }
      if (descriptor.filters.counts_for_funnel !== undefined) {
        params.set("counts_for_funnel", descriptor.filters.counts_for_funnel ? "true" : "false");
      }
      return;
    case "consultations":
    case "transitions":
    case "cohorts":
      appendSharedFilters(
        params,
        descriptor.filters as Record<string, string | boolean | undefined>,
      );
      return;
  }
}

export function buildDashboardDestination(
  context: DashboardDestinationContext,
  descriptor: DrillDownDescriptor | null,
): string | null {
  if (!descriptor) return null;

  const params = new URLSearchParams();
  params.set("nav_source", "dashboard");
  params.set("metric_key", descriptor.metric_key);

  const shouldForceTodayContext =
    descriptor.target === "consultations" && descriptor.metric_key === "consultations_today";
  const effectiveStartDate = shouldForceTodayContext ? todayVN() : context.startDate;
  const effectiveEndDate = shouldForceTodayContext ? todayVN() : context.endDate;

  if (context.scope) params.set("scope", context.scope);
  if (context.officerId) params.set("scope_officer_id", context.officerId.toString());
  if (context.unitId) params.set("scope_unit_id", context.unitId.toString());
  if (context.includeDescendants) params.set("include_descendants", "1");

  if (effectiveStartDate) params.set("from", effectiveStartDate);
  if (effectiveEndDate) params.set("to", effectiveEndDate);
  if (context.dateField) params.set("date_field", context.dateField);

  appendDescriptorFilters(params, descriptor);

  switch (descriptor.target) {
    case "leads_snapshot":
      return `/leads?${params.toString()}`;
    case "consultations":
      return `/dashboard/drilldown/consultations?${params.toString()}`;
    case "transitions":
      return `/dashboard/drilldown/transitions?${params.toString()}`;
    case "cohorts":
      return `/dashboard/drilldown/cohorts?${params.toString()}`;
  }
}
