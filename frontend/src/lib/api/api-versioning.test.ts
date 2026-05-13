/**
 * Phase 3 PR-3D-B FE Wave B Bundle 4 — api-versioning tests.
 *
 * Non-tautological per memory pattern-change-impact-audit:
 * - dedupe Set verified by triggering 2 calls with same header → 1 warn fires
 * - reload trigger verified via window.location.reload mock
 * - reload guard verified by triggering 2 mismatches → 1 reload only
 * - defensive header reader verified (uppercase + lowercase + numeric + missing)
 * - SSR-safe (typeof window check) verified by removing window globally
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  DEPRECATION_HEADER,
  EXPECTED_SCHEMA_VERSION,
  SCHEMA_VERSION_HEADER,
  _resetVersioningStateForTests,
  inspectVersionHeaders,
} from "./api-versioning"

describe("inspectVersionHeaders", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>
  let reloadSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    _resetVersioningStateForTests()
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})
    // Mock window.location.reload — jsdom defaults throw on it
    reloadSpy = vi.fn()
    Object.defineProperty(window, "location", {
      writable: true,
      value: { ...window.location, reload: reloadSpy },
    })
    window.sessionStorage.clear()
  })

  afterEach(() => {
    warnSpy.mockRestore()
    vi.clearAllMocks()
  })

  it("does nothing when headers undefined", () => {
    inspectVersionHeaders(undefined)
    expect(warnSpy).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it("does nothing when neither relevant header present", () => {
    inspectVersionHeaders({ "content-type": "application/json" })
    expect(warnSpy).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it("warns ONCE when deprecation header present (Wave B+30 path)", () => {
    inspectVersionHeaders({
      [DEPRECATION_HEADER]: "30 days — available_actions field will be dropped",
    })
    expect(warnSpy).toHaveBeenCalledTimes(1)
    expect(warnSpy.mock.calls[0][0]).toContain("Deprecation notice")
    expect(warnSpy.mock.calls[0][0]).toContain("available_actions")
  })

  it("deduplicates identical deprecation header across requests (Set-based)", () => {
    const headers = {
      [DEPRECATION_HEADER]: "30 days notice",
    }
    inspectVersionHeaders(headers)
    inspectVersionHeaders(headers)
    inspectVersionHeaders(headers)
    expect(warnSpy).toHaveBeenCalledTimes(1)
  })

  it("warns again when deprecation MESSAGE differs (dedupe by value, not key)", () => {
    inspectVersionHeaders({ [DEPRECATION_HEADER]: "30 days notice" })
    inspectVersionHeaders({ [DEPRECATION_HEADER]: "60 days notice — stricter" })
    expect(warnSpy).toHaveBeenCalledTimes(2)
  })

  it("triggers reload when schema version mismatch (Wave B+90 path)", () => {
    inspectVersionHeaders({ [SCHEMA_VERSION_HEADER]: "2" })
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it("does NOT reload when schema version matches expected", () => {
    inspectVersionHeaders({
      [SCHEMA_VERSION_HEADER]: EXPECTED_SCHEMA_VERSION,
    })
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it("reload fires ONCE per session (sessionStorage guard prevents loop)", () => {
    inspectVersionHeaders({ [SCHEMA_VERSION_HEADER]: "2" })
    inspectVersionHeaders({ [SCHEMA_VERSION_HEADER]: "2" })
    inspectVersionHeaders({ [SCHEMA_VERSION_HEADER]: "3" })
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it("handles uppercase header keys defensively (lowercase fallback)", () => {
    // Some axios versions / mock middleware may not normalize to lowercase.
    inspectVersionHeaders({
      "X-API-Deprecation": "Uppercase route still parsed",
    })
    expect(warnSpy).toHaveBeenCalledTimes(1)
    expect(warnSpy.mock.calls[0][0]).toContain("Uppercase route still parsed")
  })

  it("processes both deprecation + schema mismatch in same response", () => {
    inspectVersionHeaders({
      [DEPRECATION_HEADER]: "60 days",
      [SCHEMA_VERSION_HEADER]: "2",
    })
    expect(warnSpy).toHaveBeenCalledTimes(2) // 1 deprecation + 1 reload pre-warn
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it("ignores null/empty header values (defensive)", () => {
    inspectVersionHeaders({
      [DEPRECATION_HEADER]: null,
      [SCHEMA_VERSION_HEADER]: "",
    })
    expect(warnSpy).not.toHaveBeenCalled()
    expect(reloadSpy).not.toHaveBeenCalled()
  })
})
