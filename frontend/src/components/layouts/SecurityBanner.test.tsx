// @vitest-environment jsdom
/**
 * Option-B Commit 8 — SecurityBanner store + bumpSuspiciousLoginBanner.
 *
 * bumpSuspiciousLoginBanner is the incremental counterpart to
 * triggerSuspiciousLoginBanner: a real-time ``suspicious_login`` socket
 * event means "+1 pending", so the helper ADDS to the current count
 * rather than setting an absolute value. These tests pin:
 *   - increment semantics (count + 1, not reset)
 *   - banner becomes visible on bump
 *   - password_reset banner priority is respected (bump counts but
 *     doesn't steal the visible banner)
 *   - an active 24h dismissal is honoured (bump counts but stays hidden)
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import {
  useSecurityBannerStore,
  triggerSuspiciousLoginBanner,
  bumpSuspiciousLoginBanner,
} from "./SecurityBanner"

// jsdom provides localStorage/sessionStorage; reset between tests.
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  // Reset Zustand store to a clean baseline.
  useSecurityBannerStore.setState({
    isVisible: false,
    bannerType: null,
    suspiciousCount: 0,
  })
  vi.restoreAllMocks()
})

describe("bumpSuspiciousLoginBanner — increment semantics", () => {
  it("increments the count by 1 (does not reset to 1)", () => {
    useSecurityBannerStore.setState({ suspiciousCount: 4 })
    bumpSuspiciousLoginBanner()
    expect(useSecurityBannerStore.getState().suspiciousCount).toBe(5)
  })

  it("makes the suspicious_login banner visible on bump", () => {
    bumpSuspiciousLoginBanner()
    const s = useSecurityBannerStore.getState()
    expect(s.suspiciousCount).toBe(1)
    expect(s.isVisible).toBe(true)
    expect(s.bannerType).toBe("suspicious_login")
  })

  it("stacks multiple bumps", () => {
    bumpSuspiciousLoginBanner()
    bumpSuspiciousLoginBanner()
    bumpSuspiciousLoginBanner()
    expect(useSecurityBannerStore.getState().suspiciousCount).toBe(3)
  })
})

describe("bumpSuspiciousLoginBanner — priority + dismissal rules", () => {
  it("does not steal the visible banner from password_reset (higher priority)", () => {
    // Simulate an active password_reset banner.
    useSecurityBannerStore.setState({
      isVisible: true,
      bannerType: "password_reset",
      suspiciousCount: 0,
    })

    bumpSuspiciousLoginBanner()

    const s = useSecurityBannerStore.getState()
    // Count still increments (we tracked the new suspicious login)...
    expect(s.suspiciousCount).toBe(1)
    // ...but the visible banner stays password_reset.
    expect(s.bannerType).toBe("password_reset")
    expect(s.isVisible).toBe(true)
  })

  it("honours an active 24h dismissal — counts but stays hidden", () => {
    // Simulate the user having dismissed the suspicious banner: the
    // dismiss key stores a future expiry timestamp in localStorage.
    const future = Date.now() + 60 * 60 * 1000 // +1h
    localStorage.setItem(
      "security_banner_suspicious_dismissed_until",
      String(future),
    )

    bumpSuspiciousLoginBanner()

    const s = useSecurityBannerStore.getState()
    // Count still tracked...
    expect(s.suspiciousCount).toBe(1)
    // ...but banner does NOT re-surface (user explicitly snoozed).
    expect(s.isVisible).toBe(false)
  })

  it("re-surfaces after a stale (expired) dismissal", () => {
    const past = Date.now() - 1000 // already expired
    localStorage.setItem(
      "security_banner_suspicious_dismissed_until",
      String(past),
    )

    bumpSuspiciousLoginBanner()

    const s = useSecurityBannerStore.getState()
    expect(s.suspiciousCount).toBe(1)
    expect(s.isVisible).toBe(true)
    expect(s.bannerType).toBe("suspicious_login")
  })
})

describe("triggerSuspiciousLoginBanner — absolute set (regression guard)", () => {
  it("SETS an absolute count (not increment) — distinct from bump", () => {
    useSecurityBannerStore.setState({ suspiciousCount: 2 })
    triggerSuspiciousLoginBanner(5)
    // SET, not +=: 5 (not 7).
    expect(useSecurityBannerStore.getState().suspiciousCount).toBe(5)
  })

  it("count=0 hides the suspicious banner", () => {
    useSecurityBannerStore.setState({
      isVisible: true,
      bannerType: "suspicious_login",
      suspiciousCount: 3,
    })
    triggerSuspiciousLoginBanner(0)
    const s = useSecurityBannerStore.getState()
    expect(s.suspiciousCount).toBe(0)
    expect(s.isVisible).toBe(false)
    expect(s.bannerType).toBeNull()
  })
})
