import { describe, expect, it } from "vitest";
import {
  buildDashboardDestination,
  type DashboardDestinationContext,
  type DrillDownDescriptor,
} from "./buildDashboardDestination";

function toUrl(path: string) {
  return new URL(path, "http://test");
}

describe("buildDashboardDestination", () => {
  const context: DashboardDestinationContext = {
    scope: "unit",
    unitId: 7,
    includeDescendants: true,
    startDate: "2026-03-01",
    endDate: "2026-03-31",
    dateField: "created_at",
  };

  it("maps leads snapshot descriptor filters to canonical leads params", () => {
    const descriptor: DrillDownDescriptor = {
      target: "leads_snapshot",
      exactness: "exact",
      metric_key: "funnel_stage",
      filters: {
        stage_id: "stg03",
        status_codes: ["assigned", "contacted"],
        loss_reason_code: "PRICE_HIGH",
      },
    };

    const url = toUrl(buildDashboardDestination(context, descriptor)!);
    expect(url.pathname).toBe("/leads");
    expect(url.searchParams.get("metric_key")).toBe("funnel_stage");
    expect(url.searchParams.get("stage")).toBe("stg03");
    expect(url.searchParams.get("status")).toBe("assigned,contacted");
    expect(url.searchParams.get("loss_reason")).toBe("PRICE_HIGH");
    expect(url.searchParams.get("scope")).toBe("unit");
    expect(url.searchParams.get("scope_unit_id")).toBe("7");
    expect(url.searchParams.get("include_descendants")).toBe("1");
  });

  it("preserves exact drilldown filters for transitions targets", () => {
    const descriptor: DrillDownDescriptor = {
      target: "transitions",
      exactness: "exact",
      metric_key: "consultation_effectiveness",
      filters: {
        final_only: true,
        consulted_only: true,
        outcome: "positive",
      },
    };

    const url = toUrl(buildDashboardDestination(context, descriptor)!);
    expect(url.pathname).toBe("/dashboard/drilldown/transitions");
    expect(url.searchParams.get("metric_key")).toBe("consultation_effectiveness");
    expect(url.searchParams.get("final_only")).toBe("1");
    expect(url.searchParams.get("consulted_only")).toBe("1");
    expect(url.searchParams.get("outcome")).toBe("positive");
    expect(url.searchParams.get("from")).toBe("2026-03-01");
    expect(url.searchParams.get("to")).toBe("2026-03-31");
  });
});
