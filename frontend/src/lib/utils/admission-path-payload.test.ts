import { describe, it, expect } from "vitest";
import {
  buildApplicableToPayload,
  buildMethodQuotaPayload,
  buildBonusOverridePayload,
} from "./admission-path-payload";
import type { AdmissionAudience } from "@/lib/zod/admission-path";

/**
 * Unit tests for the extracted AdmissionPath governance payload builders.
 *
 * These import the REAL pure functions (not a re-implementation) so the
 * clear→null semantics stay pinned to the shipped code. Independent of the
 * legacy ``PathBasicInfo.payload.test.tsx`` lifecycle on purpose.
 */
describe("admission-path-payload builders", () => {
  describe("buildApplicableToPayload", () => {
    it("returns null for an empty set (clear filter = every audience)", () => {
      expect(buildApplicableToPayload(new Set())).toBeNull();
    });

    it("returns the audience array for a non-empty set", () => {
      const set = new Set<AdmissionAudience>(["POST_THPT", "POST_THCS"]);
      expect(buildApplicableToPayload(set)).toEqual(["POST_THPT", "POST_THCS"]);
    });
  });

  describe("buildMethodQuotaPayload", () => {
    it("returns null for empty / whitespace-only input", () => {
      expect(buildMethodQuotaPayload("")).toBeNull();
      expect(buildMethodQuotaPayload("   ")).toBeNull();
    });

    it("returns null for a negative number", () => {
      expect(buildMethodQuotaPayload("-1")).toBeNull();
    });

    it("returns null for non-numeric input", () => {
      expect(buildMethodQuotaPayload("abc")).toBeNull();
    });

    it("floors a decimal", () => {
      expect(buildMethodQuotaPayload("1.5")).toBe(1);
    });

    it("passes a valid integer through", () => {
      expect(buildMethodQuotaPayload("50")).toBe(50);
    });

    it("treats 0 as a real cap (not a clear)", () => {
      expect(buildMethodQuotaPayload("0")).toBe(0);
    });
  });

  describe("buildBonusOverridePayload", () => {
    it("returns null when the override toggle is off", () => {
      expect(buildBonusOverridePayload(false, true, true, "5")).toBeNull();
    });

    it("returns max_total_bonus null when enabled but max is empty (no cap)", () => {
      expect(buildBonusOverridePayload(true, true, false, "")).toEqual({
        apply_area_bonus: true,
        apply_object_bonus: false,
        max_total_bonus: null,
      });
    });

    it("builds the full shape when enabled with a valid max", () => {
      expect(buildBonusOverridePayload(true, true, false, "5")).toEqual({
        apply_area_bonus: true,
        apply_object_bonus: false,
        max_total_bonus: 5,
      });
    });

    it("clamps a max above 10 down to 10", () => {
      expect(buildBonusOverridePayload(true, false, false, "11.5")).toEqual({
        apply_area_bonus: false,
        apply_object_bonus: false,
        max_total_bonus: 10,
      });
    });

    it("clamps a negative max up to 0", () => {
      expect(buildBonusOverridePayload(true, false, true, "-3")).toEqual({
        apply_area_bonus: false,
        apply_object_bonus: true,
        max_total_bonus: 0,
      });
    });

    it("returns max_total_bonus null for a non-numeric max", () => {
      expect(buildBonusOverridePayload(true, false, false, "abc")).toEqual({
        apply_area_bonus: false,
        apply_object_bonus: false,
        max_total_bonus: null,
      });
    });
  });
});
