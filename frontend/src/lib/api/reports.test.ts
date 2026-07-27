import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  api: { get: vi.fn() },
}));

import { api } from "./client";

import { getAdmissionWeeklyReport, getReportFilters } from "./reports";

const row = {
  group_key: 1,
  label: "Công nghệ ô tô (6510216)",
  code: "6510216",
  degree_level: "Cao đẳng",
  is_bucket: false,
  bucket_kind: null,
  lead: { new_in_week: 8, active_current: 196, consulting_positive_current: 115 },
  admission: {
    profiles_total: 32,
    submitted_in_week: 19,
    admitted_in_week: 0,
    enrolled_in_week: 0,
    submitted_cumulative: 19,
    admitted_cumulative: 0,
    enrolled_cumulative: 0,
    quota: 200,
  },
  conversion: { submit_to_admit: 0.6, admit_to_enroll: 0.5 },
  finance: {
    gross_in_week: "1680000",
    refund_in_week: "0",
    net_in_week: "800000",
    application_net_in_week: "1680000",
    tuition_net_in_week: "16400000",
    net_cumulative: "18080000",
    profiles_paid: 13,
  },
};

const payload = {
  academic_year: 2026,
  round_code: "DOT_2",
  group_by: "major",
  week: {
    iso_year: 2026,
    iso_week: 25,
    week_start: "2026-06-15",
    week_end: "2026-06-21",
    timezone: "Asia/Ho_Chi_Minh",
  },
  scope_unit_id: null,
  attribution: { admission: "recomputed-current", tuition_revenue: "major-at-verified" },
  rows: [row],
  totals: row,
  data_quality: {
    total_profiles: 1,
    ambiguous_profiles: 0,
    unresolved_profiles: 0,
    unassigned_profiles: 0,
  },
};

describe("getAdmissionWeeklyReport", () => {
  it("calls the endpoint with params and parses the response", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);

    const result = await getAdmissionWeeklyReport({
      academic_year: 2026,
      group_by: "major",
    });

    expect(api.get).toHaveBeenCalledWith(
      "/api/v2/admin/reports/admission-weekly",
      { params: { academic_year: 2026, group_by: "major" } },
    );
    // proves the real .parse() ran (money kept as string, ints preserved)
    expect(result.rows[0].finance.net_in_week).toBe("800000");
    expect(result.totals.admission.profiles_total).toBe(32);
  });

  it("throws on contract drift (money sent as a number)", async () => {
    const bad = structuredClone(payload);
    (bad.rows[0].finance as Record<string, unknown>).net_in_week = 800000;
    vi.mocked(api.get).mockResolvedValue({ data: bad } as never);

    await expect(
      getAdmissionWeeklyReport({ academic_year: 2026, group_by: "major" }),
    ).rejects.toThrow();
  });

  it("throws when a required field is missing", async () => {
    const bad = structuredClone(payload) as Record<string, unknown>;
    delete bad.data_quality;
    vi.mocked(api.get).mockResolvedValue({ data: bad } as never);

    await expect(
      getAdmissionWeeklyReport({ academic_year: 2026, group_by: "major" }),
    ).rejects.toThrow();
  });
});

describe("getReportFilters", () => {
  it("parses filters and passes academic_year", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { academic_years: [2026, 2025], rounds: ["DOT_1", "DOT_2"] },
    } as never);

    const result = await getReportFilters(2026);

    expect(api.get).toHaveBeenCalledWith(
      "/api/v2/admin/reports/admission-weekly/filters",
      { params: { academic_year: 2026 } },
    );
    expect(result.academic_years).toEqual([2026, 2025]);
    expect(result.rounds).toEqual(["DOT_1", "DOT_2"]);
  });

  it("omits params when no year is given", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { academic_years: [2026], rounds: [] },
    } as never);

    await getReportFilters();

    expect(api.get).toHaveBeenCalledWith(
      "/api/v2/admin/reports/admission-weekly/filters",
      { params: undefined },
    );
  });
});
