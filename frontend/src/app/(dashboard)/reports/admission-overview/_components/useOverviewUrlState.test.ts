/**
 * useOverviewUrlState — guardrail của URL-state trang Tổng quan tuyển sinh.
 *
 * Ghim đúng các điểm rủi ro:
 *   - parse theo allowlist: enum/năm/đơn vị/ngày sai → fallback an toàn (không request lỗi);
 *   - serialize canonical: bỏ mặc định, LUÔN ghi year, round-trip parse∘serialize;
 *   - canonicalize: đợt không thuộc năm → bỏ; manager bị khóa về scope_unit_id (bỏ unit lạ);
 *   - resolveApiUnitId: bootstrap không gửi unit; manager không gửi unit của URL (chống 404).
 */

import { describe, it, expect } from "vitest";

import {
  ALL_ROUNDS,
  ALL_UNITS,
  canonicalizeOverviewState,
  parseOverviewParams,
  resolveApiUnitId,
  serializeOverviewParams,
  type OverviewUrlState,
} from "./useOverviewUrlState";

const YEAR = 2026;
const sp = (q: string) => new URLSearchParams(q);

const base: OverviewUrlState = {
  tab: "exec",
  year: YEAR,
  round: ALL_ROUNDS,
  unit: ALL_UNITS,
  groupBy: "major",
  period: "ytd",
  weekStart: undefined,
  heatmap: "profiles",
};

describe("parseOverviewParams", () => {
  it("URL rỗng → mặc định (year = năm hiện tại)", () => {
    expect(parseOverviewParams(sp(""), YEAR)).toEqual(base);
  });

  it("URL đầy đủ hợp lệ → tất cả field khớp", () => {
    const state = parseOverviewParams(
      sp(
        "tab=analysis&year=2025&round=DOT_2&unit=14&group_by=officer&period=week&week_start=2025-09-01&heatmap=fee",
      ),
      YEAR,
    );
    expect(state).toEqual({
      tab: "analysis",
      year: 2025,
      round: "DOT_2",
      unit: "14",
      groupBy: "officer",
      period: "week",
      weekStart: "2025-09-01",
      heatmap: "fee",
    });
  });

  it("enum sai → fallback mặc định", () => {
    const state = parseOverviewParams(
      sp("tab=xxx&group_by=yyy&period=zzz&heatmap=qqq"),
      YEAR,
    );
    expect(state.tab).toBe("exec");
    expect(state.groupBy).toBe("major");
    expect(state.period).toBe("ytd");
    expect(state.heatmap).toBe("profiles");
  });

  it("năm sai kiểu / ngoài khoảng → năm hiện tại", () => {
    expect(parseOverviewParams(sp("year=abc"), YEAR).year).toBe(YEAR);
    expect(parseOverviewParams(sp("year=99"), YEAR).year).toBe(YEAR);
    expect(parseOverviewParams(sp("year=2026.5"), YEAR).year).toBe(YEAR);
    expect(parseOverviewParams(sp("year=3001"), YEAR).year).toBe(YEAR);
  });

  it("đơn vị không phải số nguyên dương → ALL_UNITS", () => {
    expect(parseOverviewParams(sp("unit=abc"), YEAR).unit).toBe(ALL_UNITS);
    expect(parseOverviewParams(sp("unit=0"), YEAR).unit).toBe(ALL_UNITS);
    expect(parseOverviewParams(sp("unit=-3"), YEAR).unit).toBe(ALL_UNITS);
    expect(parseOverviewParams(sp("unit=14"), YEAR).unit).toBe("14");
  });

  it("week_start sai định dạng / sai lịch → undefined; đúng lịch → giữ", () => {
    expect(parseOverviewParams(sp("week_start=nope"), YEAR).weekStart).toBeUndefined();
    expect(parseOverviewParams(sp("week_start=2026-13-01"), YEAR).weekStart).toBeUndefined();
    expect(parseOverviewParams(sp("week_start=2026-02-31"), YEAR).weekStart).toBeUndefined();
    expect(parseOverviewParams(sp("week_start=2026-09-01"), YEAR).weekStart).toBe("2026-09-01");
  });
});

describe("serializeOverviewParams", () => {
  it("mặc định → chỉ còn year", () => {
    expect(serializeOverviewParams(base)).toBe("year=2026");
  });

  it("bỏ mọi field mặc định, chỉ ghi field khác mặc định", () => {
    const qs = serializeOverviewParams({ ...base, tab: "analysis", period: "week" });
    const out = new URLSearchParams(qs);
    expect(out.get("year")).toBe("2026");
    expect(out.get("tab")).toBe("analysis");
    expect(out.get("period")).toBe("week");
    expect(out.get("round")).toBeNull();
    expect(out.get("group_by")).toBeNull();
    expect(out.get("heatmap")).toBeNull();
  });

  it("round-trip: parse(serialize(s)) === s cho state đầy đủ khác mặc định", () => {
    const full: OverviewUrlState = {
      tab: "analysis",
      year: 2025,
      round: "DOT_3",
      unit: "14",
      groupBy: "officer",
      period: "week",
      weekStart: "2025-09-08",
      heatmap: "enrolled",
    };
    expect(parseOverviewParams(sp(serializeOverviewParams(full)), YEAR)).toEqual(full);
  });
});

describe("canonicalizeOverviewState", () => {
  const ready = { roundReady: true, scopeResolved: true };

  it("đợt không thuộc năm → bỏ về ALL_ROUNDS", () => {
    const out = canonicalizeOverviewState(
      { ...base, round: "DOT_9" },
      { ...ready, roundCodes: ["DOT_1", "DOT_2"], enforcedUnit: null },
    );
    expect(out.round).toBe(ALL_ROUNDS);
  });

  it("đợt hợp lệ theo năm → giữ nguyên tham chiếu", () => {
    const input = { ...base, round: "DOT_2" };
    const out = canonicalizeOverviewState(input, {
      ...ready,
      roundCodes: ["DOT_1", "DOT_2"],
      enforcedUnit: null,
    });
    expect(out).toBe(input);
  });

  it("chưa tải catalog đợt (roundReady=false) → KHÔNG đụng round", () => {
    const input = { ...base, round: "DOT_9" };
    const out = canonicalizeOverviewState(input, {
      roundReady: false,
      scopeResolved: true,
      roundCodes: [],
      enforcedUnit: null,
    });
    expect(out).toBe(input);
  });

  it("manager: khóa unit về scope_unit_id dù URL để unit lạ", () => {
    const out = canonicalizeOverviewState(
      { ...base, unit: "99" },
      { ...ready, roundCodes: [], enforcedUnit: 14 },
    );
    expect(out.unit).toBe("14");
  });

  it("chưa resolve scope → KHÔNG khóa unit", () => {
    const input = { ...base, unit: "99" };
    const out = canonicalizeOverviewState(input, {
      roundReady: true,
      scopeResolved: false,
      roundCodes: [],
      enforcedUnit: null,
    });
    expect(out).toBe(input);
  });
});

describe("resolveApiUnitId", () => {
  it("bootstrap (chưa resolve scope) → undefined dù URL có unit", () => {
    expect(
      resolveApiUnitId({ scopeResolved: false, enforcedUnit: null, urlUnitId: 5 }),
    ).toBeUndefined();
  });

  it("manager (bị giới hạn) → undefined dù URL có unit lạ (BE tự scope)", () => {
    expect(
      resolveApiUnitId({ scopeResolved: true, enforcedUnit: 14, urlUnitId: 5 }),
    ).toBeUndefined();
  });

  it("admin không chọn unit → undefined", () => {
    expect(
      resolveApiUnitId({ scopeResolved: true, enforcedUnit: null, urlUnitId: undefined }),
    ).toBeUndefined();
  });

  it("admin chọn unit → gửi đúng unit của URL", () => {
    expect(
      resolveApiUnitId({ scopeResolved: true, enforcedUnit: null, urlUnitId: 5 }),
    ).toBe(5);
  });
});
