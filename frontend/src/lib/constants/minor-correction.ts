/**
 * Mirror of `app/core/admission_correction_constants.py`.
 *
 * Backend is the single source of truth — this file exists so the
 * dialog + admin allowlist UI can render labels without round-tripping
 * to fetch them and so Zod refinements can guard against drift at the
 * client edge. Sync rule: changes here must follow a backend change,
 * never lead it.
 */

export const SAFE_MINOR_CORRECTION_FIELDS = new Set<string>([
  // Demographic supplements
  "gender",
  "nationality",
  "ethnicity",
  "religion",
  "disability_type",
  "social_insurance_number",
  "place_of_birth",
  "native_place",
  // Đoàn / Đảng entry dates
  "union_entry_date",
  "party_entry_date",
  "party_official_entry_date",
  // Permanent residence
  "permanent_province",
  "permanent_district",
  "permanent_ward",
  "permanent_residential_group",
  "permanent_street_address",
  // Family / guardian
  "family_info",
])

/** Vietnamese labels surfaced in the dialog + admin allowlist multi-select. */
export const FIELD_LABELS_VI: Record<string, string> = {
  gender: "Giới tính",
  nationality: "Quốc tịch",
  ethnicity: "Dân tộc",
  religion: "Tôn giáo",
  disability_type: "Loại khuyết tật",
  social_insurance_number: "Số sổ BHXH",
  place_of_birth: "Nơi sinh",
  native_place: "Nguyên quán",
  union_entry_date: "Ngày vào Đoàn",
  party_entry_date: "Ngày vào Đảng",
  party_official_entry_date: "Ngày chính thức vào Đảng",
  permanent_province: "Tỉnh/TP thường trú",
  permanent_district: "Quận/Huyện thường trú",
  permanent_ward: "Phường/Xã thường trú",
  permanent_residential_group: "Tổ/Thôn/Khu phố",
  permanent_street_address: "Địa chỉ chi tiết",
  family_info: "Thông tin gia đình / người giám hộ",
}

/**
 * Visual grouping for the dialog + admin form. Order here is the
 * render order; nothing else in the codebase depends on these group
 * names, so renaming is safe.
 */
export const FIELD_GROUPS_VI: Record<string, readonly string[]> = {
  "Thông tin bổ sung": [
    "gender",
    "nationality",
    "ethnicity",
    "religion",
    "disability_type",
    "social_insurance_number",
    "place_of_birth",
    "native_place",
  ],
  "Đoàn / Đảng": [
    "union_entry_date",
    "party_entry_date",
    "party_official_entry_date",
  ],
  "Địa chỉ thường trú": [
    "permanent_province",
    "permanent_district",
    "permanent_ward",
    "permanent_residential_group",
    "permanent_street_address",
  ],
  "Gia đình": ["family_info"],
}

/** Gender values matching backend ALLOWED_GENDERS + PersonalInfoTab dropdown. */
export const ALLOWED_GENDERS = ["Nam", "Nữ", "Khác"] as const
export type AllowedGender = (typeof ALLOWED_GENDERS)[number]

/**
 * Drift guard — every label entry must reference a SAFE field. Mirrors
 * the assert in the backend constants module so dev catches the
 * mismatch the moment the file imports rather than at runtime.
 */
const labelKeys = new Set(Object.keys(FIELD_LABELS_VI))
const safeArr = Array.from(SAFE_MINOR_CORRECTION_FIELDS)
if (
  labelKeys.size !== SAFE_MINOR_CORRECTION_FIELDS.size ||
  safeArr.some((f) => !labelKeys.has(f))
) {
  throw new Error(
    "FIELD_LABELS_VI keys must match SAFE_MINOR_CORRECTION_FIELDS exactly",
  )
}
