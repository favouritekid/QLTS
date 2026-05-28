export type PublicAdmissionsSearchParams = Promise<Record<string, string | string[] | undefined>>

/**
 * Sentinel round ID for invalid syntactic input. Engineered to:
 *
 *   1. Pass BE Pydantic Query validator (router declares
 *      `_ADMISSION_ROUND_QUERY = Query(None, ge=1, ...)` —
 *      public_admissions.py line 36). Sentinel must satisfy `ge=1` to
 *      avoid HTTP 422 leaking Pydantic constraint detail to the user.
 *      Using 0 here would have produced 422 instead of the intended 200
 *      empty — caught in PR #348 review.
 *
 *   2. Never match a real `OfferingAdmissionRound.id`. The PK column is
 *      `Integer` (PostgreSQL INTEGER, max 2147483647) and autoincrements
 *      from 1. 2147483647 is the upper bound; realistic round_id growth
 *      stays in the low thousands forever, so collision is theoretical
 *      only. If anyone seeds an explicit id=2147483647 row in the future
 *      this sentinel would unintentionally match — defensive note for
 *      future migration authors.
 *
 *   3. BE path-eligibility filter `AdmissionPath.admission_round_id == X`
 *      returns 0 rows for the sentinel → eligible offering set is empty
 *      → snapshot filter returns empty → response 200 empty. Matches the
 *      plan v4 locked contract: explicit `admission_round_id` intent →
 *      strict fail-closed, even when the user-supplied value is
 *      syntactically invalid (e.g. `?round=abc`).
 *
 * Anchor test for the end-to-end sentinel contract:
 *   tests/services/test_phase2_admission_path_quota_integration.py
 *   ::test_invalid_round_sentinel_returns_empty_200_not_422
 */
const INVALID_ROUND_SENTINEL = 2147483647

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
