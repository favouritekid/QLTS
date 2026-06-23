import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/reports", () => ({
  getAdmissionWeeklyReport: vi.fn(),
}));

import * as reportsApi from "@/lib/api/reports";

import { useWeeklyReport, weeklyReportKeys } from "./useWeeklyReport";

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const sample = { rows: [], totals: {}, group_by: "major" };

describe("useWeeklyReport", () => {
  it("fetches with the given params and exposes data", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(reportsApi.getAdmissionWeeklyReport).mockResolvedValue(sample as never);

    const { result } = renderHook(
      () => useWeeklyReport({ academic_year: 2026, group_by: "major" }),
      { wrapper: makeWrapper(qc) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(reportsApi.getAdmissionWeeklyReport).toHaveBeenCalledWith({
      academic_year: 2026,
      group_by: "major",
    });
  });

  it("is disabled when academic_year is falsy", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => useWeeklyReport({ academic_year: 0, group_by: "major" }),
      { wrapper: makeWrapper(qc) },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(reportsApi.getAdmissionWeeklyReport).not.toHaveBeenCalled();
  });

  it("key factory includes the params", () => {
    expect(
      weeklyReportKeys.query({ academic_year: 2026, group_by: "officer" }),
    ).toEqual(["admission-weekly-report", { academic_year: 2026, group_by: "officer" }]);
  });
});
