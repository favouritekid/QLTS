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
  // PR-1 (2026-05-28) — capacity gate codes appended bởi
  // admission_choice_engine_service.check_choice_admit_capacity khi NV
  // pass eligibility/score nhưng quota path/academic_info đã hết. Engine
  // degrade decision='admitted' → 'waitlisted' và append code này.
  | "PATH_QUOTA_EXHAUSTED"
  | "OFFERING_ANNUAL_QUOTA_EXHAUSTED"

export interface EligibilityScoreResult {
  final_score: number | null
  passed: boolean
  selected_subjects: string[]
}

/**
 * Capacity detail payload (PR-1 2026-05-28). Additive JSONB field —
 * only present khi engine waitlist NV vì quota exhausted. Shape mirror
 * BE CapacityCheck.detail:
 *   - PATH_QUOTA_EXHAUSTED: { path_id, current_count, cap }
 *   - OFFERING_ANNUAL_QUOTA_EXHAUSTED: { academic_info_id, current_count, cap }
 */
export interface EligibilityCapacityDetail {
  path_id?: number
  academic_info_id?: number
  current_count: number
  cap: number
}

export interface EligibilityCheckResult {
  decision: "admitted" | "waitlisted" | "rejected" | "skip" | "pending"
  reason_codes: string[]
  /**
   * PR-1 (2026-05-28) — Capacity probe detail. Only present when
   * decision='waitlisted' due to quota exhaustion (reason_codes contains
   * PATH_QUOTA_EXHAUSTED or OFFERING_ANNUAL_QUOTA_EXHAUSTED). Allows FE
   * to render "X/Y seats taken" alongside the reason label.
   */
  capacity_detail?: EligibilityCapacityDetail | null
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
  // PR-1 (2026-05-28) — capacity-gate codes (plan v4 locked decision #2).
  PATH_QUOTA_EXHAUSTED: "Hết chỉ tiêu cho phương thức tuyển sinh",
  OFFERING_ANNUAL_QUOTA_EXHAUSTED: "Hết chỉ tiêu năm học cho ngành",
}

export function getReasonLabel(code: string): string {
  return REASON_CODE_LABELS[code as EligibilityReasonCode] ?? code
}
