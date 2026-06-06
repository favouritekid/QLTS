/**
 * Zod Validation Schemas for Admission Path Module
 *
 * Mirrors Backend Pydantic schemas for type safety and validation.
 * Used for Admission Configuration Console.
 *
 * Phase 1: Backend APIs complete
 * Phase 2: Frontend Components (this file)
 */

import { z } from "zod"

import { SAFE_MINOR_CORRECTION_FIELDS } from "@/lib/constants/minor-correction"

// ==============================================================================
// STATUS ENUM
// ==============================================================================

export const admissionPathStatusEnum = z.enum([
  "draft",
  "active",
  "inactive",
  "archived",
])

export type AdmissionPathStatus = z.infer<typeof admissionPathStatusEnum>

// ==============================================================================
// AUDIENCE ENUM (phase1_03 / #184 Wave 1 PR-1B')
// ==============================================================================

/**
 * admission_audience PG ENUM mirror — values pinned to alembic
 * phase1_03 + PLAN line 605-606. Adding a new audience must touch
 * the migration, the BE schema (`AdmissionAudience` Literal) and
 * this enum together; do not extend silently.
 */
export const admissionAudienceEnum = z.enum([
  "POST_THCS",
  "POST_THPT",
  "LIEN_THONG_TC",
  "LIEN_THONG_CD",
  "VLVH",
])

export type AdmissionAudience = z.infer<typeof admissionAudienceEnum>

/**
 * Nhãn tiếng Việt cho từng audience — mirror BE
 * `document_resolution_service.AUDIENCE_LABELS`. Dùng để render badge
 * lớp giấy tờ (display-only formatting của enum, KHÔNG phải business
 * logic — như `STATUS_CONFIG` labels). Đổi nhãn phải sync BE.
 */
export const AUDIENCE_LABELS: Record<AdmissionAudience, string> = {
  POST_THCS: "Tốt nghiệp THCS",
  POST_THPT: "Tốt nghiệp THPT",
  LIEN_THONG_TC: "Liên thông Trung cấp",
  LIEN_THONG_CD: "Liên thông Cao đẳng",
  VLVH: "Vừa làm vừa học",
}

// ==============================================================================
// BONUS RULE OVERRIDE (phase1_02 wired in PR-1B')
// ==============================================================================

/**
 * Path-level / method-default bonus rule shape mirror
 * (BE: `BonusRuleOverride` in app/schemas/admission_path.py).
 *
 * `.strict()` rejects unknown keys to keep parity with Pydantic
 * `extra="forbid"` — the admin form must not silently round-trip
 * stray fields that the scoring engine will ignore.
 */
export const bonusRuleOverrideSchema = z
  .object({
    apply_area_bonus: z.boolean(),
    apply_object_bonus: z.boolean(),
    max_total_bonus: z.number().min(0).max(10).nullable().optional(),
  })
  .strict()

export type BonusRuleOverride = z.infer<typeof bonusRuleOverrideSchema>

// ==============================================================================
// NESTED SCHEMAS
// ==============================================================================

/**
 * Academic Info (nested in path response)
 */
export const academicInfoNestedSchema = z.object({
  id: z.number(),
  academic_year: z.number(),
  annual_admission_quota: z.number().nullable(),
  program_offering: z.object({
    id: z.number(),
    name: z.string().nullable(),
    major_program: z.object({
      id: z.number(),
      name: z.string(),
      admission_code: z.string().nullable(),
    }).nullable(),
  }).nullable(),
})

export type AcademicInfoNested = z.infer<typeof academicInfoNestedSchema>

/**
 * Admission Method (nested in path response)
 */
export const admissionMethodNestedSchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  requires_gpa: z.boolean(),
  requires_subject_scores: z.boolean(),
})

export type AdmissionMethodNested = z.infer<typeof admissionMethodNestedSchema>

/**
 * User (nested - used for activator field).
 * Mirror BE UserNested mini-schema.
 */
export const userNestedSchema = z.object({
  id: z.number(),
  username: z.string(),
  full_name: z.string().nullable(),
})

export type UserNested = z.infer<typeof userNestedSchema>

/**
 * Subject Group (nested in criteria)
 * Used for LeadApplicationForm score initialization
 */
export const subjectGroupNestedSchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
})

export type SubjectGroupNested = z.infer<typeof subjectGroupNestedSchema>

/**
 * Admission Criteria (nested in path response)
 * Used by LeadApplicationForm to initialize scores based on criteria
 */
export const admissionCriteriaNestedSchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  
  // Thresholds
  min_gpa: z.number().nullable(),
  min_score: z.number().nullable(),
  min_subject_score: z.number().nullable(),
  max_possible_score: z.number().nullable(),
  conditions: z.string().nullable(),
  
  // Rule Engine config
  required_subject_count: z.number().nullable(),
  subject_selection_mode: z.string().default("fixed"),
  // BE Pydantic Literal["sum", "average", "weighted"] (admission_path.py:373).
  // FE phải mirror đúng — trước đây dùng "avg" sai chính tả + thiếu "weighted"
  // → criteria có scoring_method="average"/"weighted" parse fail.
  scoring_method: z.enum(["sum", "average", "weighted"]).default("sum"),
  
  // Validity
  policy_version: z.string().nullable().optional(),
  effective_from: z.string().nullable().optional(), // Date string YYYY-MM-DD
  effective_to: z.string().nullable().optional(),   // Date string YYYY-MM-DD

  // Subject groups for score initialization
  subject_groups: z.array(subjectGroupNestedSchema).default([]),
})

export type AdmissionCriteriaNested = z.infer<typeof admissionCriteriaNestedSchema>

// ==============================================================================
// ADMISSION PATH SCHEMAS
// ==============================================================================

/**
 * Create Admission Path Schema
 * Used for POST /api/admission-config/paths
 */
export const admissionPathCreateSchema = z.object({
  academic_info_id: z.number().int().positive("Academic Info ID phải là số dương"),
  admission_method_id: z.number().int().positive("Admission Method ID phải là số dương"),
  // Round contract hardening (plan v4 Section B): REQUIRED. The BE
  // auto-resolve DOT_1 shim is removed — wizard / quick-create must always
  // send the round. Mirrors the BE Pydantic ``int = Field(..., gt=0)``.
  admission_round_id: z
    .number()
    .int()
    .positive("Đợt tuyển sinh phải là số dương"),
  // Phase 2 v8.2 PR-2B v2 — per-path quota fields (admit chain Tier 1, submit chain Tier 2).
  round_quota: z.number().int().min(0).optional().nullable(),
  admit_quota: z.number().int().min(0).optional().nullable(),
  // Phase 2 v8.2 — application fee (VND). 0/null = miễn phí.
  application_fee: z.number().min(0).optional().nullable(),
  display_name: z.string().max(255).optional().nullable(),
  display_order: z.number().int().min(0).optional().nullable(),
  visibility: z.enum(["public", "internal"]).optional(),
  // PR #6 — strict submit by default; admin toggles True to keep legacy
  // "uploaded = submittable" behaviour on a per-path basis. Default here
  // matches the backend default so the create form stays explicit.
  allow_unverified_submission: z.boolean().default(false),
  // Per-path correction allowlist. Default empty list (admin must
  // opt-in field-by-field). Refine guards against drift — schema
  // mirrors backend ``SAFE_MINOR_CORRECTION_FIELDS`` so any UI
  // accidentally posting a non-safe key fails Zod before round-trip.
  minor_correction_allowed_fields: z
    .array(z.string())
    .default([])
    .refine(
      (arr) => arr.every((f) => SAFE_MINOR_CORRECTION_FIELDS.has(f as never)),
      { message: "Field không nằm trong safe catalog" },
    ),
  // phase1_03 (#184 Wave 1 PR-1B') — audience filter + per-method
  // quota + typed bonus override. All three optional on create;
  // admin sets via update once Phase 3 validator gate ("X path null
  // applicable_to → admin set trước") flips. NULL on the wire =
  // applicable to every audience (Phase 1+2 contract).
  applicable_to: z.array(admissionAudienceEnum).optional().nullable(),
  method_quota: z.number().int().min(0).optional().nullable(),
  bonus_rule_override: bonusRuleOverrideSchema.optional().nullable(),
})

export type AdmissionPathCreate = z.infer<typeof admissionPathCreateSchema>

/**
 * Update Admission Path Schema
 * Used for PUT /api/admission-config/paths/{id}
 */
export const admissionPathUpdateSchema = z.object({
  display_name: z.string().max(255).optional().nullable(),
  display_order: z.number().int().min(0).optional().nullable(),
  visibility: z.enum(["public", "internal"]).optional(),
  // Phase 2 v8.2 — application fee (VND). 0/null = miễn phí.
  application_fee: z.number().min(0).optional().nullable(),
  // Optional on update — callers that don't want to flip the flag omit
  // it entirely and the backend leaves the current value untouched.
  allow_unverified_submission: z.boolean().optional(),
  // Optional on update so partial PATCH-style updates don't accidentally
  // clear the allowlist. Backend service raises BusinessRuleViolation
  // if a non-admin caller submits this key, so the FE form must hide
  // the section for non-admins.
  minor_correction_allowed_fields: z
    .array(z.string())
    .optional()
    .refine(
      (arr) =>
        arr === undefined ||
        arr.every((f) => SAFE_MINOR_CORRECTION_FIELDS.has(f as never)),
      { message: "Field không nằm trong safe catalog" },
    ),
  // phase1_03 — Optional on update so partial PATCH-style updates
  // don't accidentally clear the audience filter / quota / override.
  // Pass `null` to clear; omit the key to leave unchanged. Pydantic
  // distinguishes `None` (clear) from "key missing" via
  // `model_dump(exclude_unset=True)` on the BE side.
  applicable_to: z.array(admissionAudienceEnum).optional().nullable(),
  method_quota: z.number().int().min(0).optional().nullable(),
  bonus_rule_override: bonusRuleOverrideSchema.optional().nullable(),
})

export type AdmissionPathUpdate = z.infer<typeof admissionPathUpdateSchema>

/**
 * Create/Update Admission Criteria Schema
 */
export const admissionCriteriaCreateSchema = z.object({
  min_gpa: z.number().min(0).max(10).nullable().optional(),
  min_score: z.number().min(0).max(1500).nullable().optional(),
  min_subject_score: z.number().min(0).max(10).nullable().optional(),
  max_possible_score: z.number().min(0).max(1500).nullable().optional(),
  conditions: z.string().nullable().optional(),
  required_subject_count: z.number().int().min(1).nullable().optional(),
  subject_selection_mode: z.enum(["fixed", "best_n", "any_n"]).default("fixed"),
  // PR #251 review fix #1: parity với BE Pydantic Literal["sum", "average",
  // "weighted"] (admission_path.py:373). Trước đây Create schema còn "avg"
  // typo (Response schema đã fix CHECKPOINT 4); payload Create với
  // scoring_method="average" parse fail.
  scoring_method: z.enum(["sum", "average", "weighted"]).default("sum"),
  subject_groups: z.array(z.number().int()).default([]), // List of IDs
  
  // Validity
  policy_version: z.string().default("2025.1"),
  effective_from: z.string().nullable().optional(),
  effective_to: z.string().nullable().optional(),
})

export type AdmissionCriteriaCreate = z.infer<typeof admissionCriteriaCreateSchema>

/**
 * Update Path Document Schema
 */
export const admissionPathDocumentUpsertSchema = z.object({
  document_type_id: z.number().int(),
  is_mandatory: z.boolean(),
  requires_upload: z.boolean(),
  submission_format: z.string().nullable().optional(),
  display_order: z.number().int().default(0),
})

export type AdmissionPathDocumentUpsert = z.infer<typeof admissionPathDocumentUpsertSchema>

/**
 * Admission Path Response Schema
 * Used for API responses
 * 
 * Includes control fields per FRONTEND_ARCHITECTURE_V3.md:
 * - available_actions: Backend-computed allowed actions
 * - can_edit: Whether path is editable
 * - can_activate: Whether path can be activated
 * - validation_errors: Reasons why activation is blocked
 */
export const admissionPathResponseSchema = z.object({
  id: z.number(),
  academic_info_id: z.number(),
  admission_method_id: z.number(),
  // Phase 2 v8.2 PR-2C v2 — NOT NULL post 3-col UNIQUE swap.
  admission_round_id: z.number(),
  // Phase 2 v8.2 PR-2B v2 — per-path quota fields.
  round_quota: z.number().nullable(),
  admit_quota: z.number().nullable(),
  submission_count: z.number().default(0),
  // Round contract hardening (plan v4 Section D — Finding #3): flat round
  // metadata, eager-loaded by the common response queries + populated in
  // build_path_response. ``.nullable().optional()`` mirrors the BE
  // ``Optional[...] = None`` defaults (None when a query didn't eager-load
  // the relationship). The officer create page derives its round dropdown
  // from these fields. date-only fields (start/end) come as YYYY-MM-DD
  // strings; archived_at is a tz-aware ISO datetime.
  round_code: z.string().nullable().optional(),
  round_name: z.string().nullable().optional(),
  round_start_date: z.string().nullable().optional(),
  round_end_date: z.string().nullable().optional(),
  round_archived_at: z.string().datetime({ offset: true }).nullable().optional(),
  round_is_active: z.boolean().nullable().optional(),
  round_allow_multi_nv: z.boolean().nullable().optional(),
  // Phase 2 v8.2 — application fee (VND).
  application_fee: z.number().nullable(),
  // BE Pydantic field default=False (admission_path.py:440), FE phải mirror.
  // FE dùng để hiển thị flow thanh toán — không suy luận từ application_fee > 0.
  requires_application_fee: z.boolean().default(false),
  status: admissionPathStatusEnum,
  display_name: z.string().nullable(),
  display_order: z.number(),
  visibility: z.enum(["public", "internal"]),
  // Trình độ (cấp đào tạo) + tên ngành — BE populate từ
  // academic_info.offering.program (build_path_response). FE phân biệt CĐ/TC
  // trong dropdown nguyện vọng. NULL/absent nếu BE chưa load chain.
  degree_level: z.string().nullable().optional(),
  major_name: z.string().nullable().optional(),
  activated_at: z.string().datetime({ offset: true }).nullable(),
  // BE Pydantic trả nested ``activator: Optional[UserNested]`` (admission_path.py:499).
  // Trước đây FE viết ``activated_by: number`` → Zod parse fail khi BE trả object.
  activator: userNestedSchema.nullable().optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  
  // Nested relationships
  academic_info: academicInfoNestedSchema.nullable(),
  admission_method: admissionMethodNestedSchema.nullable(),
  
  // Nested criteria (for LeadApplicationForm - GAP-D fix)
  criteria: admissionCriteriaNestedSchema.nullable().optional(),
  
  // Control fields (FRONTEND_ARCHITECTURE_V3.md compliance)
  available_actions: z.array(z.string()).default([]),
  can_edit: z.boolean().default(true),
  can_activate: z.boolean().default(false),
  // PR matrix-funnel — server-side governance (Nâng cao) gate. FE gates the
  // 'Nâng cao' tab on this flag instead of user.role (thin-client). Default
  // false mirrors BE default + keeps parse lenient for endpoints that return
  // raw ORM without the computed field.
  can_edit_governance: z.boolean().default(false),
  validation_errors: z.array(z.string()).default([]),

  // PR #6 — REQUIRED in the response so Zod fails loudly when the backend
  // forgets to emit the field. Admin UI mirrors this bool as a toggle.
  allow_unverified_submission: z.boolean(),
  // Required so the admin form pre-checks the right boxes. No refine
  // on response — data from DB has already passed Create/Update
  // validation, so re-checking here would be redundant work that
  // surfaces no new bugs.
  minor_correction_allowed_fields: z.array(z.string()),

  // phase1_03 (#184 Wave 1 PR-1B') — REQUIRED on the response (no
  // default) so the parse fails loudly if BE forgets to map the
  // column. NULL on wire = "applicable to every audience" / "no
  // quota cap" / "inherit method bonus default". Admin UI must
  // distinguish NULL vs `[]`/`0` for `applicable_to` / `method_quota`
  // since they have different semantics.
  applicable_to: z.array(admissionAudienceEnum).nullable(),
  method_quota: z.number().int().min(0).nullable(),
  bonus_rule_override: bonusRuleOverrideSchema.nullable(),
})

export type AdmissionPathResponse = z.infer<typeof admissionPathResponseSchema>

/**
 * Admission Path List Response
 */
export const admissionPathListResponseSchema = z.object({
  total: z.number(),
  items: z.array(admissionPathResponseSchema),
})

export type AdmissionPathListResponse = z.infer<typeof admissionPathListResponseSchema>

// ==============================================================================
// ACADEMIC YEAR SCHEMAS
// ==============================================================================

/**
 * Academic Year List Response
 * Used for GET /api/admission-config/years
 */
export const academicYearListResponseSchema = z.object({
  years: z.array(z.number()),
  current_year: z.number(),
})

export type AcademicYearListResponse = z.infer<typeof academicYearListResponseSchema>

// ==============================================================================
// RESOLVED DOCUMENT SCHEMAS
// ==============================================================================

/**
 * Resolved Document Response
 * Used for GET /api/admission-config/paths/{id}/documents
 *
 * The `source` field indicates which tier of the 3-tier resolution
 * (phase1_06 / #184 Wave 1 PR-1C') provided the document config:
 * - "path_override": Tier 1 — path-specific group (admission_path_id = X)
 * - "method_override": Tier 2 — method-specific override
 *   (admission_path_id NULL, admission_method_id = path.method)
 * - "shared": Tier 3 — shared offering-type fallback
 *   (admission_path_id NULL, admission_method_id NULL)
 *
 * Precedence: tier 1 fully wins if present; else tier 2 fully
 * wins; else tier 3. Within a tier, mandatory-wins on duplicate
 * document_type.
 */
export const resolvedDocumentResponseSchema = z.object({
  document_type_id: z.number(),
  document_type_code: z.string(),
  document_type_name: z.string(),
  is_mandatory: z.boolean(),
  requires_upload: z.boolean(),
  submission_format: z.string().nullable(),
  display_order: z.number(),
  source: z.enum(["shared", "method_override", "path_override"]),
  // feat/document-group-audience-merge (ĐỢT A) — audience layer metadata.
  // applicable_audience: [POST_THPT,...] = lớp theo đối tượng/trình độ;
  //   null = lớp NỀN (luôn gộp) hoặc override (method/path).
  // layer_kind: phân loại lớp để render badge — KHÔNG overload `source`.
  applicable_audience: admissionAudienceEnum.array().nullable(),
  layer_kind: z.enum([
    "shared_base",
    "shared_audience",
    "method_override",
    "path_override",
  ]),
})

export type ResolvedDocumentResponse = z.infer<typeof resolvedDocumentResponseSchema>

/**
 * Resolved Document List Response
 */
export const resolvedDocumentListResponseSchema = z.object({
  path_id: z.number(),
  offering_type_id: z.number(),
  admission_method_id: z.number(),
  documents: z.array(resolvedDocumentResponseSchema),
})

export type ResolvedDocumentListResponse = z.infer<typeof resolvedDocumentListResponseSchema>

// ==============================================================================
// ACTIVATION SCHEMAS
// ==============================================================================

/**
 * Activation Validation Response
 * Used for GET /api/admission-config/paths/{id}/validate-activation
 */
export const activationValidationResponseSchema = z.object({
  can_activate: z.boolean(),
  validation_errors: z.array(z.string()),
})

export type ActivationValidationResponse = z.infer<typeof activationValidationResponseSchema>

// ==============================================================================
// COVERAGE MATRIX SCHEMAS (Phase 2.5)
// ==============================================================================

/**
 * Coverage Matrix Cell
 */
export const coverageMatrixCellSchema = z.object({
  path_id: z.number().nullable(),
  status: admissionPathStatusEnum.nullable(),
  has_criteria: z.boolean(),
  has_documents: z.boolean(),
  has_quota: z.boolean(),
})

export type CoverageMatrixCell = z.infer<typeof coverageMatrixCellSchema>

/**
 * Coverage Matrix Row (one per offering)
 */
export const coverageMatrixRowSchema = z.object({
  offering_id: z.number(),
  offering_name: z.string(),
  major_name: z.string(),
  methods: z.record(z.string(), coverageMatrixCellSchema), // method_id -> cell
})

export type CoverageMatrixRow = z.infer<typeof coverageMatrixRowSchema>

/**
 * Coverage Matrix Response
 */
export const coverageMatrixResponseSchema = z.object({
  academic_year: z.number(),
  methods: z.array(admissionMethodNestedSchema),
  offerings: z.array(coverageMatrixRowSchema),
})

export type CoverageMatrixResponse = z.infer<typeof coverageMatrixResponseSchema>

// ==============================================================================
// UI HELPERS
// ==============================================================================

/**
 * Get status badge color for admission path
 */
export function getPathStatusColor(status: AdmissionPathStatus): string {
  switch (status) {
    case "draft":
      return "bg-muted text-muted-foreground"
    case "active":
      return "bg-success-100 text-success-800"
    case "inactive":
      return "bg-warning-100 text-warning-800"
    case "archived":
      return "bg-error-100 text-error-800"
    default:
      return "bg-muted text-muted-foreground"
  }
}

/**
 * Get status label (Vietnamese) for admission path
 */
export function getPathStatusLabel(status: AdmissionPathStatus): string {
  switch (status) {
    case "draft":
      return "Nháp"
    case "active":
      return "Hoạt động"
    case "inactive":
      return "Tạm dừng"
    case "archived":
      return "Lưu trữ"
    default:
      return status
  }
}

/**
 * Check if action is available
 */
export function canPerformAction(
  path: AdmissionPathResponse,
  action: "save" | "activate" | "deactivate" | "archive"
): boolean {
  return path.available_actions.includes(action)
}
