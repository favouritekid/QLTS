import { describe, expect, it } from "vitest";

import { isLeadOverdue } from "./overdue";

describe("isLeadOverdue", () => {
  it("trả về true khi next_activity_at đã ở quá khứ", () => {
    const past = new Date(Date.now() - 60 * 60 * 1000).toISOString(); // -1h
    expect(isLeadOverdue({ next_activity_at: past })).toBe(true);
  });

  it("trả về false khi next_activity_at ở tương lai", () => {
    const future = new Date(Date.now() + 60 * 60 * 1000).toISOString(); // +1h
    expect(isLeadOverdue({ next_activity_at: future })).toBe(false);
  });

  it("trả về false khi next_activity_at là null", () => {
    expect(isLeadOverdue({ next_activity_at: null })).toBe(false);
  });

  it("trả về false khi next_activity_at là undefined", () => {
    expect(isLeadOverdue({ next_activity_at: undefined })).toBe(false);
  });

  it("trả về false khi next_activity_at là chuỗi không hợp lệ (NaN — fail-safe)", () => {
    expect(isLeadOverdue({ next_activity_at: "không-phải-ngày" })).toBe(false);
  });

  it("dùng tham số now (cho SSR/useClientNow) thay vì Date.now()", () => {
    const t = new Date("2026-06-19T10:00:00Z").getTime();
    const past = new Date("2026-06-19T09:00:00Z").toISOString();
    const future = new Date("2026-06-19T11:00:00Z").toISOString();
    expect(isLeadOverdue({ next_activity_at: past }, t)).toBe(true);
    expect(isLeadOverdue({ next_activity_at: future }, t)).toBe(false);
  });
});
