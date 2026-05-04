/**
 * Vietnamese i18n labels for the `admission_audience` PG ENUM.
 *
 * Source-of-truth: alembic phase1_03 (BE) +
 * `src/lib/zod/admission-path.ts` `admissionAudienceEnum`.
 * Adding a new audience MUST touch all three (migration + Zod +
 * this constants file) in lockstep — no silent extension.
 *
 * Labels follow the PLAN line 605-606 wording (PR #206 Wave 1
 * PR-1B'-BE) and mirror what admin sees on the form. Keep short
 * enough to fit in a checkbox label without wrapping on a
 * 1024px-wide screen.
 */

import {
  admissionAudienceEnum,
  type AdmissionAudience,
} from "@/lib/zod/admission-path"

export const AUDIENCE_LABELS_VI: Record<AdmissionAudience, string> = {
  POST_THCS: "Sau THCS — đã tốt nghiệp Trung học Cơ sở",
  POST_THPT: "Sau THPT — đã tốt nghiệp Trung học Phổ thông",
  LIEN_THONG_TC: "Liên thông từ Trung cấp",
  LIEN_THONG_CD: "Liên thông từ Cao đẳng",
  VLVH: "Vừa làm vừa học",
}

/**
 * All audience values in declaration order. Use this when
 * iterating to render the admin form so the order stays stable
 * across renders (Object.entries iteration order is insertion-
 * ordered on modern JS engines but iterating the enum directly
 * is more explicit).
 */
export const AUDIENCE_OPTIONS: ReadonlyArray<AdmissionAudience> =
  admissionAudienceEnum.options
