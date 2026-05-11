/**
 * Parse axios/fetch error and extract user-readable message.
 *
 * Priority:
 * 1. Pydantic/FastAPI `response.data.detail` (string OR array of validation
 *    errors with `msg`)
 * 2. JS `Error.message` (network, timeout, etc.)
 * 3. Caller-provided fallback
 */
export function parseApiError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail

  if (typeof detail === "string" && detail.length > 0) {
    return detail
  }

  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d as { msg?: unknown })?.msg)
      .filter((m): m is string => typeof m === "string" && m.length > 0)
    if (msgs.length > 0) return msgs.join("; ")
  }

  if (e instanceof Error && e.message.length > 0) {
    return e.message
  }

  return fallback
}
