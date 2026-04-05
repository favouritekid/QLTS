import { describe, expect, it } from "vitest";
import { parseVNDDisplayAmount } from "./finance";

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
