import { describe, expect, it } from "vitest";
import { feeRecalculateRequestSchema, parseVNDDisplayAmount } from "./finance";

describe("parseVNDDisplayAmount", () => {
  it("parses vi-VN formatted currency strings correctly", () => {
    expect(parseVNDDisplayAmount("9.000.000 VND")).toBe(9000000);
  });

  it("parses plain numeric strings correctly", () => {
    expect(parseVNDDisplayAmount("4500000")).toBe(4500000);
  });

  it("returns 0 for empty or non-numeric values", () => {
    expect(parseVNDDisplayAmount("")).toBe(0);
    expect(parseVNDDisplayAmount("VND")).toBe(0);
  });
});

describe("feeRecalculateRequestSchema", () => {
  it("accepts a valid recalculate payload", () => {
    expect(
      feeRecalculateRequestSchema.parse({
        new_base_amount: "15000000",
        reason: "Cap nhat lai muc phi goc theo quyet dinh moi",
      })
    ).toEqual({
      new_base_amount: "15000000",
      reason: "Cap nhat lai muc phi goc theo quyet dinh moi",
    });
  });

  it("rejects payloads without amount or reason", () => {
    expect(() =>
      feeRecalculateRequestSchema.parse({
        new_base_amount: "",
        reason: "short",
      })
    ).toThrow();
  });
});
