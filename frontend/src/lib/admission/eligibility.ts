/**
 * Phase 3 PR-3D-B FE Wave B Bundle 2 — Engine eligibility result types + i18n.
 *
 * Mirror of `AdmissionProfileChoice.eligibility_check_result` JSONB written
 * by `admission_choice_engine_service._evaluate_single_choice` (BE).
 *
 * BE shape (from admission_choice_engine_service.py line 319-337):
 *   {
 *     decision: "admitted" | "waitlisted" | "rejected" | "skip",
 *     reason_codes: string[],   // DisqualificationReason values
 *     score: {
 *       final_score: number | null,
 *       passed: boolean,
 *       selected_subjects: string[]
 *     } | null
 *   }
 *
 * Reason code source: `DisqualificationReason` enum trong
 * `admission_scoring_service.py` (7 codes).
 */

export type EligibilityReasonCode =
  | "MISSING_REQUIRED_SUBJECTS"
  | "BELOW_MIN_SCORE"
  | "BELOW_MIN_GPA"
  | "SUBJECT_BELOW_THRESHOLD"
  | "NO_VALID_SCORES"
  | "INVALID_SUBJECT_GROUP"
  | "GRADUATION_YEAR_OUT_OF_RANGE"

export interface EligibilityScoreResult {
  final_score: number | null
  passed: boolean
  selected_subjects: string[]
}

export interface EligibilityCheckResult {
  decision: "admitted" | "waitlisted" | "rejected" | "skip" | "pending"
  reason_codes: string[]
  score: EligibilityScoreResult | null
}

/**
 * i18n labels per BE reason code. Catch-all for unknown codes ensures FE
 * doesn't crash if BE adds a new code before FE catches up — falls back to
 * the raw code as label.
 */
export const REASON_CODE_LABELS: Record<EligibilityReasonCode, string> = {
  MISSING_REQUIRED_SUBJECTS: "Thiếu môn bắt buộc trong tổ hợp",
  BELOW_MIN_SCORE: "Điểm tổng dưới ngưỡng tối thiểu",
  BELOW_MIN_GPA: "Điểm GPA dưới ngưỡng tối thiểu",
  SUBJECT_BELOW_THRESHOLD: "Có môn dưới ngưỡng riêng",
  NO_VALID_SCORES: "Chưa có điểm xét tuyển hợp lệ",
  INVALID_SUBJECT_GROUP: "Tổ hợp môn không hợp lệ",
  GRADUATION_YEAR_OUT_OF_RANGE: "Năm tốt nghiệp ngoài phạm vi cho phép",
}

export function getReasonLabel(code: string): string {
  return REASON_CODE_LABELS[code as EligibilityReasonCode] ?? code
}
