import { describe, expect, it } from "vitest";

import { parseSearchParamsToApiParams } from "./page.helpers";

describe("parseSearchParamsToApiParams", () => {
  it("converts VN day bounds and preserves false dashboard snapshot filters", () => {
    const params = parseSearchParamsToApiParams({
      from: "2026-03-17",
      to: "2026-03-23",
      date_field: "created_at",
      is_final: "false",
      counts_for_funnel: "false",
      scope: "team",
      scope_officer_id: "18",
      include_descendants: "true",
    });

    expect(params.date_from).toBe("2026-03-17T00:00:00+07:00");
    expect(params.date_to).toBe("2026-03-23T23:59:59.999+07:00");
    expect(params.date_field).toBe("created_at");
    expect(params.is_final).toBe(false);
    expect(params.counts_for_funnel).toBe(false);
    expect(params.scope).toBe("unit");
    expect(params.scope_officer_id).toBe(18);
    expect(params.include_descendants).toBe(true);
  });

  it("parses true snapshot filters for dashboard drill-down URLs", () => {
    const params = parseSearchParamsToApiParams({
      is_final: "true",
      counts_for_funnel: "true",
      stage: "stg01",
    });

    expect(params.is_final).toBe(true);
    expect(params.counts_for_funnel).toBe(true);
    expect(params.pipeline_stage_id).toBe("stg01");
  });
});
