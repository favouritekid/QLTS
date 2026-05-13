/**
 * Phase 3 PR-3D-B FE Wave B Bundle 4 — API versioning soft-cutoff handlers.
 *
 * Implements 2-of-3 Wave B soft-cutoff timeline per Plan v0.7 (Wave B+0
 * dual-field support already shipped via PR-3D-A `hasAction()` helper):
 *
 *   Wave B+30 (2026-09-13): BE sends `X-API-Deprecation: 30 days` header
 *     → FE console.warn ONCE per session (Set-based dedupe across requests).
 *
 *   Wave B+90 SHIFTED (2026-12-15): BE drops legacy field + sends
 *     `X-API-Schema-Version: 2` header. If FE bundle expects v1 (stale
 *     service worker cache), force reload to fetch new bundle.
 *
 * Both handlers are **no-op until BE starts sending headers** — safe to
 * ship now; activate via BE calendar dates.
 *
 * Memory `react-query-mutation-cache-parity`: dedupe scoped per-session
 * (module-level Set), NOT per-page (would spam on SPA navigation). Reload
 * is one-shot guard via sessionStorage so we don't loop on reload itself.
 */

// Header names (lowercase consistent — axios normalizes response headers
// to lowercase in modern versions; defensive against drift).
export const DEPRECATION_HEADER = "x-api-deprecation"
export const SCHEMA_VERSION_HEADER = "x-api-schema-version"

/** Schema version this FE bundle was built against. Bumped via PR when
 *  the FE consumes the v2-only contract (post Wave B+90).
 *  Currently v1 = legacy + v2 dual-field (Wave B+0 state).
 */
export const EXPECTED_SCHEMA_VERSION = "1"

/** sessionStorage key — prevents reload loop if cache refresh races. */
const RELOAD_GUARD_KEY = "qlts:api-schema-reload-fired"

/** Module-level Set deduplicates console.warn across the entire SPA session. */
const warnedDeprecations = new Set<string>()

/**
 * Inspect a successful axios response for soft-cutoff signals.
 *
 * Idempotent + defensive — never throws. Caller (interceptor) wraps in
 * try/catch as belt-and-suspenders.
 */
export function inspectVersionHeaders(
  headers: Record<string, unknown> | undefined,
): void {
  if (!headers) return

  // === Wave B+30: deprecation header ===
  const deprecation = readHeader(headers, DEPRECATION_HEADER)
  if (deprecation && !warnedDeprecations.has(deprecation)) {
    warnedDeprecations.add(deprecation)
    console.warn(
      `[QLTS API] Deprecation notice: ${deprecation}. ` +
        `FE will continue working but BE may drop legacy fields soon. ` +
        `Please update the FE bundle.`,
    )
  }

  // === Wave B+90: schema version mismatch → force reload ===
  const remoteVersion = readHeader(headers, SCHEMA_VERSION_HEADER)
  if (
    remoteVersion &&
    remoteVersion !== EXPECTED_SCHEMA_VERSION &&
    !hasReloadFiredThisSession()
  ) {
    markReloadFired()
    triggerReload(remoteVersion)
  }
}

/** SSR-safe sessionStorage read. */
function hasReloadFiredThisSession(): boolean {
  if (typeof window === "undefined") return true // SSR — don't reload
  try {
    return window.sessionStorage.getItem(RELOAD_GUARD_KEY) === "1"
  } catch {
    return true // sessionStorage unavailable → treat as fired (safe default)
  }
}

function markReloadFired(): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, "1")
  } catch {
    // sessionStorage unavailable — best-effort, OK to lose flag
  }
}

/**
 * Force a hard reload to fetch the new FE bundle. Defensive guard: only
 * fires when running in a browser; logged for operator visibility.
 */
function triggerReload(remoteVersion: string): void {
  if (typeof window === "undefined") return
  console.warn(
    `[QLTS API] Schema version mismatch — server v${remoteVersion} vs ` +
      `bundle v${EXPECTED_SCHEMA_VERSION}. Reloading to fetch new FE…`,
  )
  // Use location.reload() — full reload bypasses Next.js router cache and
  // refetches the service worker registration. Mostly relevant when a long-
  // lived browser tab persists across an FE deploy.
  window.location.reload()
}

/**
 * Defensive header reader — axios may return headers as Record<string, string>
 * OR as AxiosHeaders class instance. Some middleware may not normalize keys to
 * lowercase. Iterate keys case-insensitively for max robustness.
 */
function readHeader(
  headers: Record<string, unknown>,
  name: string,
): string | undefined {
  const targetLower = name.toLowerCase()
  let lookup: unknown = undefined
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === targetLower) {
      lookup = headers[key]
      break
    }
  }
  if (lookup === undefined || lookup === null) return undefined
  if (typeof lookup === "string") return lookup.trim() || undefined
  if (typeof lookup === "number") return String(lookup)
  return undefined
}

/**
 * TEST-ONLY hook to reset the module-level dedupe Set + reload guard.
 * Vitest tests reset these between cases.
 */
export function _resetVersioningStateForTests(): void {
  warnedDeprecations.clear()
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.removeItem(RELOAD_GUARD_KEY)
    } catch {
      // ignore
    }
  }
}
