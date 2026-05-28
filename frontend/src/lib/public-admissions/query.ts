export type PublicAdmissionsSearchParams = Promise<Record<string, string | string[] | undefined>>

/**
 * Sentinel round ID for invalid syntactic input. BE schema treats this as
 * a non-existent round (auto-increment PK starts at 1) → 0 matches 0 paths
 * → eligible offering set is empty → response 200 empty.
 *
 * Preserves the plan v4 locked contract: explicit `admission_round_id`
 * intent → strict fail-closed, even when the user-supplied value is
 * syntactically invalid (e.g. `?round=abc`). Previously, invalid values
 * silently fell back to "default eligible-active union" which contradicts
 * the explicit-intent semantic.
 */
const INVALID_ROUND_SENTINEL = 0

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value
}

export function publicAdmissionsCatalogParams(
  searchParams: Record<string, string | string[] | undefined>,
): { admission_round_id?: number; audience?: string } | undefined {
  // Canonical `admission_round_id` wins over alias `round` when both present.
  const rawRound = firstValue(searchParams.admission_round_id) ?? firstValue(searchParams.round)
  const audience = firstValue(searchParams.audience)

  const params: { admission_round_id?: number; audience?: string } = {}

  if (rawRound !== undefined && rawRound !== "") {
    // Explicit intent — preserve even if invalid. Valid positive integer
    // passes through; anything else (NaN, ≤0, decimal, negative) lands on
    // the sentinel → BE returns empty.
    const roundId = Number.parseInt(rawRound, 10)
    if (Number.isInteger(roundId) && roundId > 0 && String(roundId) === rawRound.trim()) {
      params.admission_round_id = roundId
    } else {
      params.admission_round_id = INVALID_ROUND_SENTINEL
    }
  }

  if (audience) {
    params.audience = audience
  }

  return Object.keys(params).length > 0 ? params : undefined
}
