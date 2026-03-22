import type { DashboardScope } from "@/hooks/useDashboardStats";

/** V12: Drill-down target types */
export type DrillDownTarget = "leads_snapshot" | "consultations" | "transitions" | "cohorts";

/** V12: Descriptor for dashboard deep-links */
export interface DrillDownDescriptor {
  target: DrillDownTarget;
  exactness: "exact";
  metric_key: string;
  filters?: Record<string, string | string[] | boolean | undefined>;
}

export interface DashboardDestinationContext {
  scope?: DashboardScope;
  officerId?: number | null;
  unitId?: number | null;
  includeDescendants?: boolean;
  startDate?: string;
  endDate?: string;
  dateField?: string;
}

/**
 * V12: Build a deep-link URL from dashboard to a target page.
 * All links always carry nav_source=dashboard plus scope context.
 *
 * Phase B: all targets now route to their respective drill-down pages.
 */
export function buildDashboardDestination(
  context: DashboardDestinationContext,
  descriptor: DrillDownDescriptor | null,
): string | null {
  if (!descriptor) return null;

  const params = new URLSearchParams();
  params.set("nav_source", "dashboard");
  params.set("metric_key", descriptor.metric_key);

  // Scope context
  if (context.scope) params.set("scope", context.scope);
  if (context.officerId) params.set("scope_officer_id", context.officerId.toString());
  if (context.unitId) params.set("scope_unit_id", context.unitId.toString());
  if (context.includeDescendants) params.set("include_descendants", "1");

  // Date context
  if (context.startDate) params.set("from", context.startDate);
  if (context.endDate) params.set("to", context.endDate);
  if (context.dateField) params.set("date_field", context.dateField);

  // Descriptor filters
  if (descriptor.filters) {
    for (const [key, value] of Object.entries(descriptor.filters)) {
      if (value === undefined || value === false) continue;
      if (Array.isArray(value)) {
        params.set(key, value.join(","));
      } else if (typeof value === "boolean") {
        params.set(key, "1");
      } else {
        params.set(key, value);
      }
    }
  }

  // Route based on target
  switch (descriptor.target) {
    case "leads_snapshot":
      return `/leads?${params.toString()}`;
    case "consultations":
      return `/dashboard/drilldown/consultations?${params.toString()}`;
    case "transitions":
      return `/dashboard/drilldown/transitions?${params.toString()}`;
    case "cohorts":
      return `/dashboard/drilldown/cohorts?${params.toString()}`;
    default:
      return null;
  }
}
