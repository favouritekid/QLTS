import { describe, expect, it } from "vitest";

import {
  shouldUseInitialLeadsData,
  type InitialDataGuardState,
} from "./LeadsClient.helpers";

const baseFilterState: InitialDataGuardState = {
  page: 1,
  search: "",
  statusFilters: [],
  offeringFilters: [],
  sourceFilters: [],
  validityFilters: [],
  stageFilters: [],
  officerFilters: [],
  unitId: "",
  dateFrom: "",
  dateTo: "",
  scoreRange: [0, 100],
  sortBy: "created_at",
  sortOrder: "desc",
};

describe("shouldUseInitialLeadsData", () => {
  it("returns true for the pristine SSR state with no snapshot flags", () => {
    expect(shouldUseInitialLeadsData(baseFilterState, {})).toBe(true);
  });

  it("treats is_final=false as an active untracked snapshot filter", () => {
    expect(
      shouldUseInitialLeadsData(baseFilterState, {
        is_final: false,
      }),
    ).toBe(false);
  });

  it("treats counts_for_funnel=false as an active untracked snapshot filter", () => {
    expect(
      shouldUseInitialLeadsData(baseFilterState, {
        counts_for_funnel: false,
      }),
    ).toBe(false);
  });

  it("disables initialData when visible lead filters are active", () => {
    expect(
      shouldUseInitialLeadsData(
        {
          ...baseFilterState,
          stageFilters: ["stg01"],
        },
        {},
      ),
    ).toBe(false);
  });
});
