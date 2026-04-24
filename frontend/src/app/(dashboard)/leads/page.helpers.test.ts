import { describe, expect, it } from "vitest";

import {
  areLeadsListParamsEqual,
  formatLeadsDateFromApiParam,
  formatLeadsDateToApiParam,
  LEADS_DEFAULT_PAGE_SIZE,
  LEADS_DEFAULT_SORT_BY,
  LEADS_DEFAULT_SORT_ORDER,
  parseSearchParamsToApiParams,
} from "./page.helpers";

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

describe("lead date formatters", () => {
  it("formats the from-date at midnight VN time", () => {
    expect(formatLeadsDateFromApiParam("2026-03-17")).toBe(
      "2026-03-17T00:00:00+07:00",
    );
  });

  it("formats the to-date at end-of-day VN time", () => {
    expect(formatLeadsDateToApiParam("2026-03-23")).toBe(
      "2026-03-23T23:59:59.999+07:00",
    );
  });
});

describe("areLeadsListParamsEqual", () => {
  const defaults = {
    page: 1,
    page_size: LEADS_DEFAULT_PAGE_SIZE,
    sort_by: LEADS_DEFAULT_SORT_BY,
    order: LEADS_DEFAULT_SORT_ORDER,
  };

  it("returns true for the SSR default shape matching the client default shape", () => {
    expect(areLeadsListParamsEqual(defaults, defaults)).toBe(true);
  });

  it("treats missing keys and undefined values as equal", () => {
    expect(
      areLeadsListParamsEqual(defaults, { ...defaults, search: undefined }),
    ).toBe(true);
  });

  it("treats empty string and missing key as equal", () => {
    expect(
      areLeadsListParamsEqual(defaults, { ...defaults, search: "" }),
    ).toBe(true);
  });

  it("returns false when one side carries a filter the other lacks", () => {
    expect(
      areLeadsListParamsEqual(defaults, { ...defaults, status: "sts02" }),
    ).toBe(false);
  });

  it("returns false when date bounds differ", () => {
    const ssr = {
      ...defaults,
      date_from: formatLeadsDateFromApiParam("2026-03-17"),
      date_to: formatLeadsDateToApiParam("2026-03-23"),
      date_field: "created_at" as const,
    };
    const client = {
      ...defaults,
      date_from: formatLeadsDateFromApiParam("2026-03-18"),
      date_to: formatLeadsDateToApiParam("2026-03-23"),
      date_field: "created_at" as const,
    };
    expect(areLeadsListParamsEqual(ssr, client)).toBe(false);
  });

  it("returns true when SSR and client format the same date bounds identically", () => {
    const ssr = {
      ...defaults,
      date_from: formatLeadsDateFromApiParam("2026-03-17"),
      date_to: formatLeadsDateToApiParam("2026-03-23"),
    };
    const client = { ...ssr };
    expect(areLeadsListParamsEqual(ssr, client)).toBe(true);
  });

  it("returns false when dashboard scope differs", () => {
    expect(
      areLeadsListParamsEqual(
        { ...defaults, scope: "unit", scope_officer_id: 18 },
        { ...defaults, scope: "unit", scope_officer_id: 19 },
      ),
    ).toBe(false);
  });

  it("returns false when either side is undefined/null but not both", () => {
    expect(areLeadsListParamsEqual(undefined, defaults)).toBe(false);
    expect(areLeadsListParamsEqual(defaults, undefined)).toBe(false);
    expect(areLeadsListParamsEqual(undefined, undefined)).toBe(true);
  });
});
