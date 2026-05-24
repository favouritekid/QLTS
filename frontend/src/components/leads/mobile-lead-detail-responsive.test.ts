/**
 * Mobile responsive anchors — lead detail + intake selectors.
 *
 * Source-contract tests (no DOM render): they read the component source
 * and assert the responsive class patterns that the 2026-05-24 mobile
 * audit fixes introduced. Render-based tests for these components need
 * the full React Query + hooks provider tree and would mostly assert
 * the mocks; a source contract is the cheapest durable guard against a
 * refactor silently reintroducing the bugs verified in-browser @375px.
 *
 * Covers:
 *  - Bug #2: consultation method ToggleGroup wraps (flex-wrap).
 *  - Bug #1: offering/unit combobox scroll containers stop touchmove
 *    propagation (defeats Radix Dialog react-remove-scroll touch-lock)
 *    + use responsive width instead of a fixed px that overflows mobile.
 *  - Touch targets: Sheet close button is a 44px hit area; lead-detail
 *    chips/buttons use `h-11 sm:*` (mobile 44, desktop compact).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(resolve(__dirname, rel), "utf-8");

const v2 = read("./QuickConsultationSectionV2.tsx");
const offering = read("../common/selectors/SmartOfferingSelector.tsx");
const unit = read("../common/selectors/SmartUnitSelector.tsx");
const sheet = read("../ui/sheet.tsx");

describe("Bug #2 — consultation method toggle wraps on mobile", () => {
  it("method ToggleGroup uses flex-wrap (no horizontal overflow @375px)", () => {
    // The method selector row must wrap; pre-fix it was `flex justify-start
    // gap-1` (no wrap) and the "Gặp mặt" chip overflowed the 319px drawer.
    expect(v2).toMatch(/value=\{method\}[\s\S]{0,200}?className="flex flex-wrap justify-start gap-1"/);
  });

  it("sibling toggle rows also wrap (consistency guard)", () => {
    const wrapCount = (v2.match(/flex flex-wrap (?:justify-start )?gap-1(?:\.5)?/g) ?? []).length;
    expect(wrapCount).toBeGreaterThanOrEqual(3);
  });
});

describe("Bug #1 — combobox selectors scroll on touch inside a Dialog", () => {
  it("SmartOfferingSelector scroll container stops touchmove propagation", () => {
    // Defeats the Dialog's react-remove-scroll bubble-phase document
    // touchmove listener so native scroll works on mobile.
    expect(offering).toMatch(/onTouchMove=\{\(e\)\s*=>\s*e\.stopPropagation\(\)\}/);
    expect(offering).toContain("overscroll-contain");
  });

  it("SmartOfferingSelector popover width is responsive (no 420px overflow @375px)", () => {
    expect(offering).toMatch(/w-\[calc\(100vw-2rem\)\][^"]*sm:w-\[420px\]/);
    // the old hardcoded fixed width must be gone
    expect(offering).not.toMatch(/className="w-\[420px\] p-0"/);
  });

  it("SmartUnitSelector has the same touch-scroll shim + responsive width", () => {
    expect(unit).toMatch(/onTouchMove=\{\(e\)\s*=>\s*e\.stopPropagation\(\)\}/);
    expect(unit).toMatch(/w-\[calc\(100vw-2rem\)\][^"]*sm:w-\[400px\]/);
    expect(unit).not.toMatch(/className="w-\[400px\] p-0"/);
  });
});

describe("Touch targets — 44px on mobile, compact on desktop", () => {
  it("Sheet close button is a 44px hit area (shared primitive)", () => {
    // X icon stays 16px but the SheetPrimitive.Close hit area is 44px.
    expect(sheet).toMatch(/SheetPrimitive\.Close[\s\S]{0,160}?h-11 w-11/);
  });

  it("lead-detail chips/buttons bump to 44px on mobile via h-11 sm:*", () => {
    // method chip, outcome chips, quick-action buttons all gated h-11 sm:*
    expect(v2).toMatch(/h-11 sm:h-8/);     // method chips
    expect(v2).toMatch(/h-11 sm:h-7/);     // outcome chips
    expect(v2).toMatch(/min-h-11 sm:min-h-0/); // status pills / disclosure
  });
});
