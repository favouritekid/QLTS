/**
 * Pure scoring helper mirroring the backend authoritative formula at
 * `Backend_FastAPI/app/services/admission_scoring_service.py::_calculate_final_score`.
 *
 * Weighted semantics (backend docstring at `admission_scoring_service.py:226-236`):
 *  - `subject_weights` null / undefined / empty object → plain sum fallback.
 *  - Per-subject missing key → weight 1.0 (NOT a fallback trigger).
 *  - Otherwise: plain weighted sum `Σ score * weight` (no division by total weight).
 */

export type ScoringMethod = "sum" | "average" | "weighted"

export interface ScoringInput {
  subjectScores: Record<string, number | null | undefined> | null | undefined
  scoringMethod: ScoringMethod
  subjectWeights?: Record<string, number> | null
}

function collectValidEntries(
  subjectScores: ScoringInput["subjectScores"],
): Array<[string, number]> {
  if (!subjectScores || typeof subjectScores !== "object") return []
  const entries: Array<[string, number]> = []
  for (const [code, raw] of Object.entries(subjectScores)) {
    if (typeof raw === "number" && !Number.isNaN(raw)) {
      entries.push([code, raw])
    }
  }
  return entries
}

export function calculateAdmissionTotal({
  subjectScores,
  scoringMethod,
  subjectWeights,
}: ScoringInput): number {
  const entries = collectValidEntries(subjectScores)
  if (entries.length === 0) return 0

  if (scoringMethod === "average") {
    const sum = entries.reduce((acc, [, s]) => acc + s, 0)
    return sum / entries.length
  }

  if (scoringMethod === "weighted") {
    const hasWeights =
      subjectWeights != null && Object.keys(subjectWeights).length > 0
    if (!hasWeights) {
      return entries.reduce((acc, [, s]) => acc + s, 0)
    }
    return entries.reduce((acc, [code, s]) => {
      const w = subjectWeights![code] ?? 1.0
      return acc + s * w
    }, 0)
  }

  return entries.reduce((acc, [, s]) => acc + s, 0)
}
