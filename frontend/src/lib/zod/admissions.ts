/**
 * Zod Validation Schemas for Admission Module
 *
 * Mirrors Backend Pydantic schemas for type safety and validation.
 * Used with React Hook Form via @hookform/resolvers/zod
 *
 * Security Features:
 * - Input sanitization (HTML escape handled by backend)
 * - Strict validation (regex, length limits, GPA range)
 * - Type safety (TypeScript + Zod)
 *
 * Architecture:
 * - Zod schemas used for form validation
 * - Pydantic schemas used for API validation
 * - Both must stay in sync
 */

import { z } from "zod"

import { admissionProfileChoiceResponseSchema } from "./admission-choices"

// ==============================================================================
// HELPERS
// ==============================================================================

/**
 * Nullable String Helper
 * Phase 3.1 Refactor: Reduces duplication for optional fields that need empty-string-to-null transformation.
 */
const nullableString = (max: number = 255) =>
  z.string()
    .max(max, `Không được quá ${max} ký tự`)
    .optional()
    .nullable()
    .or(z.literal(""))
    .transform(v => v === "" ? null : v)

// ==============================================================================
// NESTED SCHEMAS (for JSONB fields)
// ==============================================================================

/**
 * Family Member Schema
 * Stored in admission_profile.family_info JSONB array
 */
export const familyMemberSchema = z.object({
  relationship: z
    .string()
    .min(1, "Quan hệ không được để trống")
    .max(50, "Quan hệ không được quá 50 ký tự")
    .trim(),
  full_name: z
    .string()
    .min(1, "Họ tên không được để trống")
    .max(255, "Họ tên không được quá 255 ký tự")
    .trim(),
  occupation: z
    .string()
    .max(255, "Nghề nghiệp không được quá 255 ký tự")
    .trim(),
  phone: z
    .string()
    .regex(
      /^0\d{9,10}$/,
      "Số điện thoại phải bắt đầu bằng 0 và có 10-11 chữ số"
    )
    .trim(),
  is_primary_guardian: z.boolean().optional(),
})

export type FamilyMember = z.infer<typeof familyMemberSchema>

/**
 * Priority Bonus — UT đối tượng sub_code regex (Q9 #07 PR1/PR5).
 *
 * Mirror of phase1_08b CHECK ``sub_code ~ '^[0-9]{2}$'`` + Pydantic
 * PrioritySubCode in BE schemas/admission.py. 2-digit numeric like
 * "01".."07+" per TT 05/2021 Phụ lục 01.
 */
export const prioritySubCodeSchema = z
  .string()
  .regex(/^[0-9]{2}$/, "Mã UT phải là 2 chữ số (vd: '04')")

/**
 * Priority Object Evidence Entry — nested shape for each evidence dict
 * value in priority_object_evidence JSONB. Mirror of BE
 * PriorityObjectEvidenceEntry (Q9 #07 review-2 + m-RV2-1).
 *
 * Status enum gates the engine bonus calc — only "verified" contributes.
 * Cross-field invariants on BE (rejected → reject_reason, verified →
 * verified_by) surface as 400 ValidationError from PUT; FE form should
 * pre-validate to give a faster red-state.
 */
export const priorityObjectEvidenceEntrySchema = z.object({
  status: z.enum(["pending", "verified", "rejected"]),
  document_id: z.number().int().nullable().optional(),
  verified_by: z.number().int().nullable().optional(),
  verified_at: z.string().datetime({ offset: true }).nullable().optional(),
  reject_reason: z.string().max(500).nullable().optional(),
  requested_at: z.string().datetime({ offset: true }).nullable().optional(),
}).strict()

export type PriorityObjectEvidenceEntry = z.infer<
  typeof priorityObjectEvidenceEntrySchema
>

/**
 * Academic Record Schema
 * Stored in admission_profile.academic_history JSONB array
 */
export const academicRecordSchema = z
  .object({
    school_name: z
      .string()
      .min(1, "Tên trường không được để trống")
      .max(255, "Tên trường không được quá 255 ký tự")
      .trim(),
    year_from: z
      .number()
      .int("Năm bắt đầu phải là số nguyên")
      .min(1900, "Năm bắt đầu phải từ 1900 trở lên")
      .max(2100, "Năm bắt đầu không được quá 2100"),
    year_to: z
      .number()
      .int("Năm kết thúc phải là số nguyên")
      .min(1900, "Năm kết thúc phải từ 1900 trở lên")
      .max(2100, "Năm kết thúc không được quá 2100"),
    gpa: z
      .number()
      .min(0, "GPA phải từ 0 trở lên")
      .max(10, "GPA không được quá 10")
      .optional()
      .nullable(),
    graduation_type: z
      .string()
      .trim()
      .optional()
      .nullable(),
  })
  .refine((data) => data.year_to >= data.year_from, {
    message: "Năm kết thúc phải lớn hơn hoặc bằng năm bắt đầu",
    path: ["year_to"],
  })

export type AcademicRecord = z.infer<typeof academicRecordSchema>

/**
 * Admission Score Schema
 * Stored in admission_profile.admission_scores JSONB object
 * 
 * Structure:
 * - selected_criterion_id: ID of the selected admission method
 * - selected_group: Subject group code (e.g., "A00", "D01")
 * - gpa: GPA score (for học bạ method)
 * - subject_scores: Dynamic object with subject scores (e.g., math: 8.5)
 * - total_score: Auto-calculated total of subject scores
 * - average_score: Auto-calculated average
 */
export const admissionScoreSchema = z.object({
  // Method selection
  selected_criterion_id: z.string().optional().nullable(),
  selected_group: z.string().optional().nullable(),
  
  // GPA-based method
  gpa: z
    .number()
    .min(0, "GPA phải từ 0 trở lên")
    .max(10, "GPA không được quá 10")
    .optional()
    .nullable(),
  
  // Exam-based method - Dynamic subject scores
  subject_scores: z.record(
    z.string(),
    z.number().min(0).max(10).optional().nullable()
  ).optional().nullable(),
  
  // Auto-calculated values
  total_score: z.number().optional().nullable(),
  average_score: z.number().optional().nullable(),
  
  // =========================================================================
  // ⚠️ DEPRECATED: Legacy fields – DO NOT USE FOR CALCULATION
  // Only for backward compatibility
  // =========================================================================
  math_score: z.number().min(0).max(10).optional().nullable(),
  literature_score: z.number().min(0).max(10).optional().nullable(),
  english_score: z.number().min(0).max(10).optional().nullable(),
})

export type AdmissionScore = z.infer<typeof admissionScoreSchema>

/**
 * Document Item Schema
 * Stored in admission_profile.documents_checklist JSONB array
 */
export const documentItemSchema = z.object({
  code: z
    .string()
    .min(1, "Mã tài liệu không được để trống")
    .max(100, "Mã tài liệu không được quá 100 ký tự")
    .trim(),
  label: z
    .string()
    .min(1, "Tên tài liệu không được để trống")
    .max(255, "Tên tài liệu không được quá 255 ký tự")
    .trim(),
  is_mandatory: z.boolean().optional(),
  /**
   * BR2 (2026-04-29): true when this row is a ProfileDocument that
   * exists in the DB but is NOT in the current
   * applied_rules.mandatory_docs snapshot — typically because the
   * AdmissionPath was edited after the profile was created. Extras are
   * read-only (all can_* flags false); UI renders them in a separate
   * "Tài liệu ngoài yêu cầu hiện tại" section.
   */
  is_extra: z.boolean().optional(),
  // Phase 0.9: New document config fields (all optional for form/response compatibility)
  requires_upload: z.boolean().optional(),
  submission_format: z.enum(["photo", "certified_copy", "original"]).nullable().optional(),
  /**
   * FE-only state field - tracks user confirmation of submission format.
   * Backend does not need this field.
   * @see ADR-FE-005-submission-format-confirmed.md
   */
  submission_format_confirmed: z.boolean().optional(),
  // Status and upload info
  status: z.enum(["missing", "uploaded", "verified", "rejected", "paper_submitted"]),
  file_path: z
    .string()
    .max(512, "Đường dẫn file không được quá 512 ký tự")
    .nullable()
    .optional(),
  /**
   * File size in bytes (max 10MB).
   * Added for BE-FE contract sync per admission.py:229-233
   */
  file_size: z.number().int().min(0).max(10485760).nullable().optional(),
  uploaded_at: z
    .string()
    .nullable()
    .optional(),
  /**
   * Paper-receipt timestamp — when officer marked the paper document as
   * received. Surfaced in the FE so the "Đã ghi nhận" cell can show the
   * receipt date for paper-only docs the same way it shows uploaded_at
   * for online docs (ADM-031 round 7).
   */
  paper_submitted_at: z.string().nullable().optional(),
  rejection_reason: z.string().nullable().optional(),
  actual_submission_format: z.string().nullable().optional(),
  /**
   * Verified format - confirmed by officer during document review.
   * Records the actual physical format of the document after verification.
   */
  verified_format: z.enum(["photo", "certified_copy", "original"]).nullable().optional(),
  /**
   * Verification timestamp - when officer verified the document.
   */
  verified_at: z.string().datetime({ offset: true }).nullable().optional(),
  /**
   * ID of officer who verified the document.
   */
  verified_by: z.number().int().nullable().optional(),
  /**
   * Display name of the verifier — backend resolves full_name → username
   * via a batched User lookup (ADM-031 round 10). Email is intentionally
   * NOT a fallback (staff-to-staff privacy). When null, the FE falls
   * back to "User #<verified_by>".
   */
  verified_by_name: z.string().nullable().optional(),
  // ---------------------------------------------------------------------
  // PR #5 — explicit per-document permission flags.
  // Backend computes these per (role × doc status × profile status × unit
  // scope) in admission_service._compute_document_permissions. FE must
  // gate the matching button iff the flag is true. Defaulting missing
  // flags to `false` via .optional() so legacy rows (pre-deploy) render
  // in read-only mode rather than leaking buttons.
  // ---------------------------------------------------------------------
  can_upload: z.boolean().optional(),
  can_verify: z.boolean().optional(),
  can_reject: z.boolean().optional(),
  can_reset: z.boolean().optional(),
  can_mark_paper_submitted: z.boolean().optional(),
})

export type DocumentItem = z.infer<typeof documentItemSchema>

// ==============================================================================
// ADMISSION PROFILE SCHEMAS
// ==============================================================================

/**
 * Create Admission Profile Schema
 * Used for POST /api/admissions
 * REFACTORED (Phase 2): Now requires admission_method_id for AdmissionPath lookup
 *
 * ADM-017: ``academic_year`` lets the caller bind the profile to a
 * specific (offering, year) ``OfferingAcademicInfo`` row. Pre-fix
 * BE picked "newest published year" implicitly — broken when an
 * offering had multiple published years simultaneously (transition
 * windows). BE phase merged in PR #176; this FE schema makes the
 * field required client-side. Backend still tolerates it being
 * omitted (legacy fallback) until the strict-required follow-up
 * ships.
 */
export const admissionProfileCreateSchema = z.object({
  lead_id: z
    .number()
    .int("Lead ID phải là số nguyên")
    .positive("Lead ID phải là số dương"),
  admission_method_id: z
    .number()
    .int("Admission Method ID phải là số nguyên")
    .positive("Admission Method ID phải là số dương"),
  academic_year: z
    .number()
    .int("Năm học phải là số nguyên")
    .min(2000, "Năm học không hợp lệ")
    .max(2100, "Năm học không hợp lệ"),
})

export type AdmissionProfileCreate = z.infer<
  typeof admissionProfileCreateSchema
>

/**
 * Update Admission Profile Schema
 * Used for PUT /api/admissions/{id}
 * All fields are optional (partial update) except version
 */
export const admissionProfileUpdateSchema = z.object({
  // Version for optimistic locking (set via defaultValues)
  version: z.number().int().min(1).optional(),

  // Personal Info Fields
  // Phase 4 Fix: Allow optional for draft Save, backend enforces required on Submit
  full_name: nullableString(255),
  dob: nullableString(),
  gender: nullableString(50),
  nationality: nullableString(100),
  ethnicity: nullableString(100),

  // Optional fields
  phone: z
    .string()
    .regex(/^0\d{9,10}$/, "Số điện thoại không hợp lệ")
    .optional()
    .nullable()
    .or(z.literal(""))
    .transform(v => v === "" ? null : v),
  email: z.string().email("Email không hợp lệ").max(255).optional().nullable().or(z.literal("")).transform(v => v === "" ? null : v),
  social_insurance_number: nullableString(50),
  religion: nullableString(100),
  disability_type: nullableString(100),
  permanent_province: nullableString(100),
  permanent_district: nullableString(100),
  permanent_ward: nullableString(100),
  // Sub-ward + street (free-text). See backend admission.py model comment.
  permanent_residential_group: nullableString(150),
  permanent_street_address: nullableString(255),
  place_of_birth: nullableString(255),
  native_place: nullableString(255),
  
  // Political Info Dates - Relaxed validation
  union_entry_date: nullableString(),
  party_entry_date: nullableString(),
  party_official_entry_date: nullableString(),

  // Identity - Optional for draft, backend enforces on Submit
  citizen_id: z
    .string()
    .regex(/^\d{12}$/, "CCCD/CMND phải là 12 chữ số")
    .optional()
    .nullable()
    .or(z.literal("")) // Allow empty string for drafts
    .transform(v => v === "" ? null : v),

  // JSONB Arrays
  family_info: z.array(familyMemberSchema).optional().nullable(),
  academic_history: z.array(academicRecordSchema).optional().nullable(),
  admission_scores: admissionScoreSchema.optional().nullable(),
  documents_checklist: z.array(documentItemSchema).optional().nullable(),

  // =========================================================================
  // Q9 #07 PR5 v1.3 (phase1_09) — Priority bonus fields (2-field parallel).
  // Trình độ văn hóa: 5 options (Hoàn thành THCS / Tốt nghiệp THCS / Hoàn thành
  //   THPT / Tốt nghiệp THPT / Tốt nghiệp GDTX) — per Luật GDNN 2014/2025.
  // Trình độ chuyên môn: 4 options (Chưa có / Sơ cấp / Trung cấp / Cao đẳng).
  // KV BACKUP for special case (PT DTNT / quân nhân): permanent_commune_code.
  // UT (đối tượng): priority_object_codes + per-code evidence dict.
  // Multi-school history live in academic_history JSONB array (NOT single field).
  // Legacy (PR1 phase1_08b) high_school_id / kv_resolved / area_resolution_reason
  //   DROPPED in phase1_09.
  // =========================================================================
  cultural_education_level: z
    .enum([
      "completed_thcs",
      "graduated_thcs",
      "completed_thpt",
      "graduated_thpt",
      "graduated_gdtx",
    ])
    .nullable()
    .optional(),
  vocational_qualification: z
    .enum(["none", "so_cap", "trung_cap", "cao_dang"])
    .nullable()
    .optional(),
  permanent_commune_code: nullableString(20),
  area_resolution_basis: z
    .enum(["high_school", "permanent_address_special", "manual_override"])
    .nullable()
    .optional(),
  priority_object_codes: z.array(prioritySubCodeSchema).max(20).nullable().optional(),
  priority_object_evidence: z
    .record(prioritySubCodeSchema, priorityObjectEvidenceEntrySchema)
    .nullable()
    .optional(),
})

export type AdmissionProfileUpdateInput = z.input<
  typeof admissionProfileUpdateSchema
>

export type AdmissionProfileUpdate = z.output<
  typeof admissionProfileUpdateSchema
>

/**
 * Subject Group Schema (for applied_rules snapshot)
 * Preserved from AdmissionPath for audit trail.
 *
 * PR6 Step 1 (2026-04-19): `weights` is a NEW parallel field mapping each
 * subject code in `subjects` to its raw coefficient. Default 1.0 per
 * subject = no-op (plain sum behavior). The field is optional so older
 * snapshots (pre-migration) pass validation — those profiles keep their
 * original plain-sum calculation as agreed during PR6 spec (no
 * retroactive backfill).
 */
export const subjectGroupSnapshotSchema = z.object({
  code: z.string(), // e.g., "A00", "D01"
  name: z.string(), // e.g., "Toán - Lý - Hóa"
  subjects: z.array(z.string()), // e.g., ["math", "physics", "chemistry"]
  // e.g., { math: 2.0, physics: 1.0, chemistry: 1.0 }
  weights: z.record(z.string(), z.number().positive()).optional(),
})

export type SubjectGroupSnapshot = z.infer<typeof subjectGroupSnapshotSchema>

/**
 * Document Config Schema (for applied_rules snapshot)
 */
export const documentConfigSnapshotSchema = z.object({
  requires_upload: z.boolean().optional(),
  submission_format: z.string().optional().nullable(),
  is_mandatory: z.boolean().optional(),
})

export type DocumentConfigSnapshot = z.infer<typeof documentConfigSnapshotSchema>

/**
 * Applied Rules Schema
 *
 * ✅ CRITICAL: Complete snapshot with ALL scoring parameters
 * Per ADMISSION_PROCESSING_FLOW_ANALYSIS.md Section 6.1
 *
 * This schema ensures immutable snapshot compliance:
 * - All scoring rules frozen at profile creation time
 * - No dependency on live configuration changes
 * - Deterministic evaluation guaranteed
 */
export const appliedRulesSchema = z.object({
  // =========================================================================
  // GROUP 1: Basic Criteria
  // =========================================================================
  min_gpa: z.number().optional().nullable(),
  min_score: z.number().optional().nullable(),

  // =========================================================================
  // GROUP 2: Scoring Configuration (CRITICAL for deterministic scoring)
  // =========================================================================
  subject_selection_mode: z.enum(["fixed", "best_n", "any_n"]).optional(),
  scoring_method: z.enum(["sum", "average", "weighted"]).optional(),
  required_subject_count: z.number().int().optional().nullable(),
  min_subject_score: z.number().optional().nullable(), // Điểm liệt
  max_possible_score: z.number().optional().nullable(),
  // PR6 Step 1 (2026-04-19): per-subject weights frozen into the snapshot
  // at application time. Mirrors the backend field emitted by
  // AdmissionScoringService.generate_snapshot(). Optional + missing-key
  // semantics — a missing code or an entire absent object means weight 1.0
  // (plain sum), which preserves behavior for pre-migration snapshots.
  subject_weights: z.record(z.string(), z.number().positive()).optional(),

  // =========================================================================
  // GROUP 3: Subject Validation (CRITICAL for input validation)
  // =========================================================================
  allowed_subject_codes: z.array(z.string()).optional().default([]), // e.g., ["math", "physics", "chemistry", "english"]
  subject_groups: z.array(subjectGroupSnapshotSchema).optional().default([]), // Audit trail

  // =========================================================================
  // GROUP 4: Method & Path Metadata
  // =========================================================================
  admission_method: z.string().optional().nullable(), // e.g., "HOC_BA"
  admission_method_id: z.number().int().optional(),
  // Ticket #3: Explicit method type (Strict)
  method_type: z.enum(["gpa_only", "subject_based", "combined"]).nullable(),

  // =========================================================================
  // GROUP 5: Document Requirements
  // =========================================================================
  mandatory_docs: z.array(z.string()).optional().default([]),
  doc_configs: z.record(z.string(), documentConfigSnapshotSchema).optional().default({}),
  // Ticket #4: Upload Configuration (Relaxed for migration compatibility)
  upload_config: z.object({
    allowed_types: z.array(z.string()).default([]),
    max_file_size: z.number().int().default(10 * 1024 * 1024), // 10MB default
    allowed_extensions: z.array(z.string()).default([]),
  }).optional().nullable(),

  // =========================================================================
  // GROUP 6: Snapshot Metadata
  // =========================================================================
  snapshot_source: z.enum(["relational", "jsonb", "migration"]).optional(),
  admission_path_id: z.number().int().optional(),
  academic_info_id: z.number().int().optional(),
  // Phase 2 v8.2 PR-2B snapshot admission_round_id từ path. Mirrors BE
  // admission_service.py:2825. Used by AddChoiceDialog (E2E #6 fix
  // 2026-05-15) để resolve round khi profile chưa có NV nào.
  admission_round_id: z.number().int().positive().optional(),
})

export type AppliedRules = z.infer<typeof appliedRulesSchema>

/**
 * Admission Profile Response Schema
 * Used for API responses (GET, POST, PUT)
 *
 * Phase 7: Added permissions, eligibility_status, validation_errors,
 * available_actions, completion_percent for Frontend Thin Client compliance.
 *
 * Phase 8: Updated applied_rules with complete 18-field schema
 */
export const admissionProfileResponseSchema = z.object({
  id: z.number(),
  lead_id: z.number(),
  citizen_id: z.string().optional().nullable(),
  citizen_id_masked: z.string().optional().nullable(), // Masked CCCD for display (e.g., ********1234)
  // Personal Info Extensions
  full_name: z.string().nullable(),
  dob: z.string().datetime({ offset: true }).nullable(), // Backend returns ISO string
  gender: z.string().nullable(),
  email: z.string().nullable(),
  phone: z.string().nullable(),
  social_insurance_number: z.string().nullable(),
  nationality: z.string().nullable(),
  ethnicity: z.string().nullable(),
  religion: z.string().nullable(),
  disability_type: z.string().nullable(),
  permanent_province: z.string().nullable(),
  permanent_district: z.string().nullable(),
  permanent_ward: z.string().nullable(),
  permanent_residential_group: z.string().nullable(),
  permanent_street_address: z.string().nullable(),
  place_of_birth: z.string().nullable(),
  native_place: z.string().nullable(),

  // Q9 #07 v1.3 priority bonus — READ side (mirror of BE AdmissionProfileResponse).
  // 2-field parallel design (phase1_09): cultural + vocational.
  // Defaults match BE: list/dict default-factory, scalars nullable.
  cultural_education_level: z.string().nullable().optional(),
  vocational_qualification: z.string().nullable().optional(),
  permanent_commune_code: z.string().nullable().optional(),
  area_resolution_basis: z.string().nullable().optional(),
  priority_object_codes: z.array(z.string()).default([]),
  priority_object_evidence: z
    .record(z.string(), priorityObjectEvidenceEntrySchema)
    .default({}),
  priority_resolution_snapshot: z.record(z.string(), z.unknown()).default({}),

  union_entry_date: z.string().datetime({ offset: true }).nullable(),
  party_entry_date: z.string().datetime({ offset: true }).nullable(),
  party_official_entry_date: z.string().datetime({ offset: true }).nullable(),
  // Status (extended for async-first workflow).
  //
  // STRICT PARSE — Stage 3 of the 3-stage deploy choreography for
  // M-1-11 (status CHECK extend 10 → 14 state) per PLAN line
  // 188-191 v2.10 fix #7. Flipped from permissive ``z.union(enum,
  // z.string())`` to strict ``z.enum`` of exactly 14 values after
  // Wave 3-A ``phase1_11`` shipped (PR #219 squash 55f3eb41).
  //
  // 10 legacy + 4 new (choice-engine milestones per PLAN §3.3.b):
  //   reviewing / result_published / admitted / waitlisted.
  //
  // Strict enum semantics:
  //   * Backend response with unknown status string → Zod parse
  //     failure → React Query reports error → user sees error UI,
  //     not a malformed render. Force the contract end-to-end.
  //   * Tests must assert this rejection so future drift (BE adds
  //     a 15th state without coordinating FE) is caught at CI, not
  //     in prod.
  //
  // Surfaces already aligned to 14 states (no follow-up needed):
  //   * ``status-badge.config.ts`` — 14 entries (PR #212 squash
  //     2c411306 Wave 3 PR-3A pre-flight).
  //   * ``AdmissionsClient.tsx`` STATUS_TABS + STATUS_OPTIONS —
  //     14 entries (PR #212).
  //   * ``useAdmissionsFilter.ts`` STATUS_TABS — 14 entries (PR
  //     #212, drift-guarded by ``AdmissionsClient.status-tabs.test``).
  status: z.enum([
    "draft", "submitted", "resubmitted", "approved", "rejected",
    "revision_requested", "confirmed", "overridden", "enrolled", "withdrawn",
    "reviewing", "result_published", "admitted", "waitlisted",
  ]),
  version: z.number().int().optional(), // Optimistic locking
  academic_year: z.number().int().optional(), // Academic year
  applied_rules: appliedRulesSchema, // ✅ NEW: Properly typed with 18 fields
  // Phase 3 multi-NV gate. false = legacy single-NV ProfileSubjectScore flow
  // (ScoresTab legacy form); true = ChoiceListEditor + ChoiceScoreCard render.
  uses_choice_engine: z.boolean().default(false),
  // Phase 3 multi-NV choices array. Empty cho legacy. BE eager-loads via
  // selectinload chain (admission_repository.py _choices_eager_load_options).
  choices: z.array(admissionProfileChoiceResponseSchema).default([]),
  family_info: z.array(familyMemberSchema).default([]),
  academic_history: z.array(academicRecordSchema).default([]),
  admission_scores: admissionScoreSchema.nullable(),
  documents_checklist: z.array(documentItemSchema).default([]),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  // Nested relationships (optional)
  lead: z.object({
    id: z.number(),
    full_name: z.string(),
    phone: z.string().nullable().optional(),
    email: z.string().nullable().optional(),
    unit_id: z.number().nullable().optional(),
    assigned_officer_id: z.number().nullable().optional(),
    assigned_officer: z.object({
      id: z.number(),
      full_name: z.string(),
    }).nullable().optional(),
  }).nullable().optional(),
  student: z.any().optional().nullable(),

  // Denormalized fields for list display
  program_name: z.string().optional().nullable(),
  
  // =========================================================================
  // Phase 7: Frontend Thin Client Fields (computed by backend)
  // =========================================================================
  
  // Permission flags (from backend Casbin + status)
  permissions: z.record(z.string(), z.boolean()).default({}),
  
  // ✅ Ticket #3.1: Document Status Summary (Computed by Backend)
  document_stats: z.object({
    submitted_count: z.number().int(),
    verified_count: z.number().int(),
    mandatory_count: z.number().int(),
    missing_count: z.number().int(),
    // PR #6 review — strict-mode submit gate splits truly-missing from
    // uploaded-pending-verify so the FE can label them differently.
    // Optional for backwards compatibility with legacy responses that
    // predate the split.
    unverified_count: z.number().int().optional(),
  }).nullable().optional(),
  
  // Eligibility status (backend-computed)
  eligibility_status: z.enum(["eligible", "ineligible", "pending"]).default("pending"),

  // F7: True when reviewer is about to act on a profile that bypassed
  // eligibility (allow_unverified_submission=true + ineligible). FE
  // renders an orange warning banner + confirmation dialog in front of
  // the Approve button.
  bypass_warning: z.boolean().default(false),

  // Validation errors (reasons for ineligibility)
  validation_errors: z.array(z.string()).default([]),
  
  // Available workflow actions (legacy string list — kept intact for
  // backward compatibility through Wave B+90 soft cutoff per Plan v0.7
  // P-UI-08. Consumers should migrate to `hasAction(profile, name)`
  // helper which checks v2 typed shape first, falls back here.)
  available_actions: z.array(z.string()).default([]),

  // Phase 3 PR-3D-A typed `available_actions_v2` (additive, OPTIONAL).
  // Backend may populate this NEW field with `{action, target?, endpoint?}`
  // shape; FE consumers via `hasAction()` helper handle both legacy +
  // typed transparently. Wave B+90 (2026-12-15) drop legacy after FE
  // fully migrates.
  available_actions_v2: z
    .array(
      z.object({
        action: z.string(),
        target: z.number().int().positive().optional(),
        endpoint: z.string().optional(),
      })
    )
    .optional(),

  // Per-profile effective allowlist for the post-approval correction
  // dialog (mirrors AdmissionProfileResponse.minor_correction_fields).
  // Backend resolves SAFE catalog ∩ AdmissionPath config; FE renders
  // the dialog rows from this list, never derives anything itself.
  minor_correction_fields: z.array(z.string()).default([]),
  
  // Profile completion percentage (0-100)
  completion_percent: z.number().int().min(0).max(100).default(0),

  // =========================================================================
  // phase1_09a (#184 Wave 2 PR-2A wired in FE-zod-eligibility) —
  // 4 eligibility scalar fields. BE migration ships 4 nullable
  // columns + backfills 2 (gpa_overall + graduation_year via
  // academic_history JSON). conduct + health_category STAY NULL
  // post-migration — admin reviews via UI Phase 1+2.
  // =========================================================================
  //
  // FE Zod parse parity per Codex Guard 4 — DB shipped in PR-2A
  // (squash 2d8b52f1) but FE Zod was deferred to this PR per the
  // Phase 3 deploy choreography Stage 1 contract (FE permissive
  // BEFORE BE M-1-11 status CHECK extend). All 4 nullable +
  // optional so legacy responses without the fields still parse.
  //
  // Range guards mirror PLAN + alembic migration:
  // * gpa_overall: 0..10 (numeric(4,2) on the wire — string-or-
  //   number depending on BE serializer). Coerce because Pydantic
  //   `Numeric` typically serializes as string in JSON.
  // * conduct: enum TB/KHA/TOT (PLAN line 818).
  // * health_category: smallint 1..4, where 1 = best (PLAN line 819).
  // * graduation_year: smallint 1900..2100 (PLAN line 2795).
  gpa_overall: z.coerce
    .number()
    .min(0)
    .max(10)
    .nullable()
    .optional(),
  conduct: z
    .enum(["TB", "KHA", "TOT"])
    .nullable()
    .optional(),
  health_category: z
    .number()
    .int()
    .min(1)
    .max(4)
    .nullable()
    .optional(),
  graduation_year: z
    .number()
    .int()
    .min(1900)
    .max(2100)
    .nullable()
    .optional(),
  
  // Phase 0.9: Validation Summary (Grouped Errors for UX)
  validation_summary: z.object({
    gpa: z.object({
      has_error: z.boolean(),
      label: z.string(),
      count: z.number().int()
    }).optional(),
    documents: z.object({
      has_error: z.boolean(),
      label: z.string(),
      count: z.number().int()
    }).optional(),
    personal: z.object({
      has_error: z.boolean(),
      label: z.string(),
      count: z.number().int()
    }).optional()
  }).optional().nullable(),

  // Grouped validation errors (categorized display)
  grouped_validation_errors: z.object({
    personal_info: z.object({
      category: z.string(),
      errors: z.array(z.string()),
      count: z.number().int()
    }).optional(),
    documents: z.object({
      category: z.string(),
      errors: z.array(z.string()),
      count: z.number().int(),
      // PR #6 review — split bucket counts so the FE can render
      // "Thiếu N" + "Chờ xác minh M" separately. Optional for
      // legacy responses.
      missing_count: z.number().int().optional(),
      unverified_count: z.number().int().optional(),
    }).optional(),
    scores: z.object({
      category: z.string(),
      errors: z.array(z.string()),
      count: z.number().int()
    }).optional()
  }).optional().nullable(),

  /**
   * Step status for sidebar navigation.
   * NOTE: Backend returns Dict[int, str] but JSON serializes keys as strings.
   * Frontend converts parseInt() in AdmissionDetailClient.tsx:102-106
   * @see FRONTEND_ARCHITECTURE_V3.md Section 0.6
   */
  step_status: z.record(z.string(), z.enum(["success", "warning", "error", "locked"])).optional().nullable(),

  /**
   * Executive summary for dashboard overview.
   * Provides high-level status summary computed by backend.
   * Frontend uses this to display overall progress, next actions, and blocking issues.
   */
  executive_summary: z.object({
    overall_status: z.enum(["incomplete", "warning", "ready"]),
    completion_percent: z.number().int().min(0).max(100),
    step_summary: z.record(z.string(), z.number()),
    critical_blockers: z.array(z.string()),
    warnings: z.array(z.string()),
    next_action: z.string(),
    can_submit: z.boolean(),
  }).optional().nullable(),

  // Computed scores (backend-calculated)
  total_score: z.number().optional().nullable(),
  average_score: z.number().optional().nullable(),
  
  // =========================================================================
  // Audit Trail Fields (BE-FE Contract Sync per admission.py:427-434)
  // =========================================================================
  approved_at: z.string().datetime({ offset: true }).nullable().optional(),
  approved_by_id: z.number().nullable().optional(),
  approval_notes: z.string().nullable().optional(),
  rejected_at: z.string().datetime({ offset: true }).nullable().optional(),
  rejected_by_id: z.number().nullable().optional(),
  rejection_reason: z.string().nullable().optional(),

  // Revision request audit fields
  revision_requested_at: z.string().datetime({ offset: true }).nullable().optional(),
  revision_requested_by_id: z.number().nullable().optional(),
  revision_reason: z.string().nullable().optional(),

  // Resubmit audit fields
  resubmitted_at: z.string().datetime({ offset: true }).nullable().optional(),
  resubmitted_by_id: z.number().nullable().optional(),
  resubmit_notes: z.string().nullable().optional(),

  // Override audit fields
  overridden_at: z.string().datetime({ offset: true }).nullable().optional(),
  overridden_by_id: z.number().nullable().optional(),
  override_reason: z.string().nullable().optional(),

  // Confirmation tracking
  confirmed_by_id: z.number().nullable().optional(),

  // Drop-out tracking (side-channel, status stays "enrolled")
  is_dropped: z.boolean().nullable().optional(),
  dropped_at: z.string().datetime({ offset: true }).nullable().optional(),
  dropped_by_id: z.number().nullable().optional(),
  dropped_reason: z.string().nullable().optional(),

  // Claim/assignment fields
  assigned_reviewer_id: z.number().nullable().optional(),
  assigned_reviewer_name: z.string().nullable().optional(),
  assigned_at: z.string().datetime({ offset: true }).nullable().optional(),
  assigned_officer_name: z.string().nullable().optional(),

  // Ticket #2: Backend-computed qualification status
  is_qualified: z.boolean().nullable().optional().describe("Whether profile meets admission criteria. Computed by backend."),

  // =========================================================================
  // Best N mode: selected subjects for highlighting (computed by backend)
  snapshot_score: z.object({
    selected_subjects: z.array(z.string()).optional(),
  }).nullable().optional(),

  // Ticket #5: Score Snapshot Status (Thin Client Compliance)
  // Backend computes pass/fail status, Frontend ONLY renders
  // =========================================================================
  score_snapshot_status: z.object({
    total_status: z.enum(["passing", "failing"]).nullable(),
    subject_statuses: z.record(z.string(), z.enum(["passing", "failing"]).nullable()),
    min_subject_score: z.number(),
    min_score: z.number(),
  }).nullable().optional().describe("Backend-computed score pass/fail status for each subject and total"),
})

export type AdmissionProfileResponse = z.infer<
  typeof admissionProfileResponseSchema
>

/**
 * Paginated Admissions Response Schema
 * Used for GET /api/admissions response
 */
export const admissionsPageSchema = z.object({
  total_count: z.number(),
  page: z.number(),
  page_size: z.number(),
  profiles: z.array(admissionProfileResponseSchema),
})

export type AdmissionsPage = z.infer<typeof admissionsPageSchema>

/**
 * Submit Response Schema
 * Used for POST /api/admissions/{id}/submit response
 * 
 * ✅ FIXED: Match Backend admission.py:546 exactly
 * Backend only returns: "draft" (validation failed) or "submitted" (success)
 * Other statuses (approved, rejected) come from separate action endpoints.
 * 
 * @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #4
 */
export const admissionSubmitResponseSchema = z.object({
  /** Status after submit: "draft" (failed validation) or "submitted" (success) */
  status: z.enum(["draft", "submitted"]).nullable(),
  message: z.string().nullable(),
  errors: z.array(z.string()).nullable(),
  validation_errors: z.array(z.string()).default([]),
})

export type AdmissionSubmitResponse = z.infer<
  typeof admissionSubmitResponseSchema
>

/**
 * Enroll Student Response Schema
 * Used for POST /api/admissions/{id}/enroll response
 */
export const enrollStudentResponseSchema = z.object({
  student_id: z.number(),
  student_code: z.string(),
  enrollment_date: z.string().datetime(),
})

export type EnrollStudentResponse = z.infer<typeof enrollStudentResponseSchema>

// ==============================================================================
// FORM SCHEMAS (for React Hook Form)
// ==============================================================================

/**
 * Family Info Form Schema
 * Used for family_info section in profile update
 */
export const familyInfoFormSchema = z.object({
  family_info: z.array(familyMemberSchema).min(0).default([]),
})

export type FamilyInfoForm = z.infer<typeof familyInfoFormSchema>

/**
 * Academic History Form Schema
 * Used for academic_history section in profile update
 */
export const academicHistoryFormSchema = z.object({
  academic_history: z.array(academicRecordSchema).min(0).default([]),
})

export type AcademicHistoryForm = z.infer<typeof academicHistoryFormSchema>

/**
 * Admission Scores Form Schema
 * Used for admission_scores section in profile update
 */
export const admissionScoresFormSchema = z.object({
  admission_scores: admissionScoreSchema,
})

export type AdmissionScoresForm = z.infer<typeof admissionScoresFormSchema>

/**
 * Applicant Info Form Schema
 * Used for basic applicant information (citizen_id)
 */
export const applicantInfoFormSchema = z.object({
  citizen_id: z
    .string()
    .regex(/^\d{12}$/, "CCCD/CMND phải là 12 chữ số")
    .trim(),
})

export type ApplicantInfoForm = z.infer<typeof applicantInfoFormSchema>

// ==============================================================================
// STUDENT SCHEMAS (for responses)
// ==============================================================================

/**
 * Student Document Response Schema
 */
export const studentDocumentResponseSchema = z.object({
  id: z.number(),
  student_id: z.number(),
  doc_type: z.string(),
  file_path: z.string(),
  is_verified: z.boolean(),
  reviewer_note: z.string().nullable(),
  uploaded_at: z.string().datetime(),
  verified_at: z.string().datetime().nullable(),
})

export type StudentDocumentResponse = z.infer<
  typeof studentDocumentResponseSchema
>

/**
 * Student Response Schema
 */
export const studentResponseSchema = z.object({
  id: z.number(),
  admission_profile_id: z.number(),
  student_code: z.string(),
  enrollment_date: z.string().datetime(),
  created_at: z.string().datetime(),
  documents: z.array(studentDocumentResponseSchema).default([]),
})

export type StudentResponse = z.infer<typeof studentResponseSchema>

// ==============================================================================
// VALIDATION HELPERS
// ==============================================================================

/**
 * Validate GPA range (0-10)
 */
export function validateGPA(gpa: number): boolean {
  return gpa >= 0 && gpa <= 10
}

/**
 * Validate citizen ID format (12 digits)
 */
export function validateCitizenID(citizenId: string): boolean {
  return /^\d{12}$/.test(citizenId)
}

/**
 * Validate phone number format (Vietnam)
 */
export function validatePhoneNumber(phone: string): boolean {
  return /^0\d{9,10}$/.test(phone)
}

/**
 * Status color mapping
 * Phase 3 Fix: Use Record with fallback for unknown statuses
 * @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #5
 */
const STATUS_COLORS: Record<string, string> = {
  draft: "bg-muted text-muted-foreground",
  submitted: "bg-warning-100 text-warning-800",
  resubmitted: "bg-warning-100 text-warning-800",
  approved: "bg-success-100 text-success-800",
  rejected: "bg-error-100 text-error-800",
  revision_requested: "bg-orange-100 text-orange-800",
  confirmed: "bg-success-100 text-success-800",
  enrolled: "bg-info-100 text-info-800",
  overridden: "bg-purple-100 text-purple-800",
  withdrawn: "bg-muted text-muted-foreground",
}

/**
 * Get status badge color
 * Phase 3 Fix: Accepts any string status with fallback for unknown values
 */
export function getStatusColor(status: string): string {
  return STATUS_COLORS[status] ?? "bg-muted text-muted-foreground"
}

/**
 * Status label mapping (Vietnamese)
 * Phase 3 Fix: Use Record with fallback for unknown statuses
 */
const STATUS_LABELS: Record<string, string> = {
  draft: "Nháp",
  submitted: "Chờ duyệt",
  resubmitted: "Nộp lại",
  approved: "Đã duyệt",
  rejected: "Từ chối",
  revision_requested: "Yêu cầu bổ sung",
  confirmed: "Đã xác nhận",
  enrolled: "Đã nhập học",
  overridden: "Đã override",
  withdrawn: "Đã rút hồ sơ",
}

/**
 * Get status label (Vietnamese)
 * Phase 3 Fix: Accepts any string status with fallback
 */
export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

// ==============================================================================
// WORKFLOW ACTION SCHEMAS
// ==============================================================================

/**
 * Approve Request Schema
 * Mirrors backend: app/schemas/admissions.py -> ApproveRequest
 * 
 * Used when Manager/Admin approves a submitted admission profile.
 * Requires version for optimistic locking.
 */
export const approveRequestSchema = z.object({
  notes: z.string().optional(),
  version: z.number().int().positive("Version must be a positive integer"),
})

export type ApproveRequest = z.infer<typeof approveRequestSchema>

/**
 * Reject Request Schema
 * Mirrors backend: app/schemas/admissions.py -> RejectRequest
 * 
 * Used when Manager/Admin rejects a submitted admission profile.
 * Requires rejection reason (minimum 10 characters for clarity)
 * and version for optimistic locking.
 */
export const rejectRequestSchema = z.object({
  reason: z
    .string()
    .min(10, "Lý do từ chối phải có ít nhất 10 ký tự")
    .max(1000, "Lý do từ chối không được quá 1000 ký tự")
    .trim(),
  version: z.number().int().positive("Version must be a positive integer"),
})

export type RejectRequest = z.infer<typeof rejectRequestSchema>

/**
 * Revision Request Schema
 * Mirrors backend: app/schemas/admissions.py -> RevisionRequest
 *
 * Used when Manager/Admin requests revision on a submitted admission profile.
 * Requires reason (minimum 10 characters) and version for optimistic locking.
 */
export const revisionRequestSchema = z.object({
  reason: z
    .string()
    .min(10, "Lý do yêu cầu bổ sung phải có ít nhất 10 ký tự")
    .max(1000, "Lý do yêu cầu bổ sung không được quá 1000 ký tự")
    .trim(),
  version: z.number().int().positive("Version must be a positive integer"),
})

export type RevisionRequest = z.infer<typeof revisionRequestSchema>

/**
 * Resubmit Request Schema
 * Mirrors backend: app/schemas/admissions.py -> ResubmitRequest
 *
 * Used when Officer resubmits a rejected/revision_requested admission profile.
 * Requires version for optimistic locking. Optional notes about what was fixed.
 */
export const resubmitRequestSchema = z.object({
  version: z.number().int().positive("Version must be a positive integer"),
  notes: z.string().max(1000, "Ghi chú không được quá 1000 ký tự").trim().optional().nullable(),
})

export type ResubmitRequest = z.infer<typeof resubmitRequestSchema>

/**
 * Drop Student Request Schema
 * Mirrors backend: app/schemas/admissions.py -> DropStudentRequest
 *
 * Used when Manager/Admin marks an enrolled student as dropped out.
 * Requires reason (minimum 10 characters) and version for optimistic locking.
 */
export const dropStudentRequestSchema = z.object({
  reason: z
    .string()
    .min(10, "Lý do ngừng theo học phải có ít nhất 10 ký tự")
    .max(1000, "Lý do ngừng theo học không được quá 1000 ký tự")
    .trim(),
  version: z.number().int().positive("Version must be a positive integer"),
})

export type DropStudentRequest = z.infer<typeof dropStudentRequestSchema>

// ==============================================================================
// BULK ACTION SCHEMAS
// ==============================================================================

/**
 * Bulk Approve Request Schema
 * Used for POST /api/admissions/bulk/approve
 */
export const bulkApproveItemSchema = z.object({
  profile_id: z.number().int().positive(),
  version: z.number().int().positive(),
})

export type BulkApproveItem = z.infer<typeof bulkApproveItemSchema>

export const bulkApproveRequestSchema = z.object({
  items: z.array(bulkApproveItemSchema).min(1).max(100),
  notes: z.string().max(1000).optional(),
})

export type BulkApproveRequest = z.infer<typeof bulkApproveRequestSchema>

/**
 * Bulk Reject Request Schema
 * Used for POST /api/admissions/bulk/reject
 */
export const bulkRejectItemSchema = z.object({
  profile_id: z.number().int().positive(),
  version: z.number().int().positive(),
})

export type BulkRejectItem = z.infer<typeof bulkRejectItemSchema>

export const bulkRejectRequestSchema = z.object({
  items: z.array(bulkRejectItemSchema).min(1).max(100),
  reason: z.string().min(10, "Lý do từ chối phải có ít nhất 10 ký tự").max(1000),
})

export type BulkRejectRequest = z.infer<typeof bulkRejectRequestSchema>

/**
 * Bulk Assign Request Schema
 * Used for POST /api/admissions/bulk/assign
 */
export const bulkAssignRequestSchema = z.object({
  profile_ids: z.array(z.number().int().positive()).min(1).max(100),
  officer_id: z.number().int().positive(),
})

export type BulkAssignRequest = z.infer<typeof bulkAssignRequestSchema>

/**
 * Bulk Action Response Schema
 * Used for bulk approve/reject/assign responses
 */
export const bulkActionResponseSchema = z.object({
  success_count: z.number().int(),
  failed_count: z.number().int(),
  failed_ids: z.array(z.number().int()),
  errors: z.record(z.string(), z.string()).optional().nullable(),
  message: z.string(),
})

export type BulkActionResponse = z.infer<typeof bulkActionResponseSchema>

/**
 * Admission List Params
 * Query parameters for GET /api/admissions
 */
export interface AdmissionListParams {
  page?: number
  page_size?: number
  status?: string       // comma-separated for multi-select
  search?: string
  major_id?: string     // comma-separated
  academic_year?: number
  degree_level?: string
  payment_status?: string  // paid | unpaid | partial | no_fee
  date_from?: string    // ISO date string
  date_to?: string      // ISO date string
  sort_by?: 'created_at' | 'updated_at' | 'full_name' | 'status'
  order?: 'asc' | 'desc'
}

/**
 * Status Counts Response
 * From GET /api/admissions/status-counts
 */
export interface AdmissionStatusCounts {
  counts: Record<string, number>
  total: number
}

/**
 * Aggregate Stats Response
 * From GET /api/admissions/stats
 */
export interface AdmissionStats {
  total_profiles: number
  draft_count: number
  submitted_count: number
  approved_count: number
  enrolled_count: number
  rejected_count: number
  dropped_count: number
  conversion_rate: number
  avg_completion: number
}

// ==============================================================================
// MAGIC-LINK CONFIRMATION (Public flow)
// ==============================================================================
// Mirrors backend schemas in Backend_FastAPI/app/schemas/admission.py:1198-1244.
// Applicant clicks email link → /confirm/[token] page → submits 4 CCCD digits.

/**
 * POST /api/admissions/confirm/{token} body
 */
export const ConfirmTokenVerifyRequestSchema = z.object({
  last_digits_citizen_id: z
    .string()
    .regex(/^\d{4}$/, "Phải là 4 chữ số"),
})
export type ConfirmTokenVerifyRequest = z.infer<typeof ConfirmTokenVerifyRequestSchema>

/**
 * POST /api/admissions/confirm/{token} response (success)
 */
export const ConfirmTokenResponseSchema = z.object({
  message: z.string(),
  profile_id: z.number().int(),
  status: z.string(),
  confirmed_at: z.string().datetime({ offset: true }),
})
export type ConfirmTokenResponse = z.infer<typeof ConfirmTokenResponseSchema>

/**
 * GET /api/admissions/confirm/{token} response — used to render form pre-submit
 * (attempts remaining, expiry state, locked state, already-used state).
 */
export const ConfirmTokenInfoResponseSchema = z.object({
  valid: z.boolean(),
  expired: z.boolean(),
  locked: z.boolean(),
  already_used: z.boolean(),
  attempts_remaining: z.number().int(),
  profile_name: z.string(),
  expires_at: z.string().datetime({ offset: true }).nullable(),
})
export type ConfirmTokenInfoResponse = z.infer<typeof ConfirmTokenInfoResponseSchema>

/**
 * POST /api/admissions/{id}/minor-correction — request schema.
 *
 * Mirrors backend ``MinorCorrectionRequest``. ``reason`` is trimmed
 * before length check so a "          a" (length 10 with 9 spaces)
 * fails Zod the same way it fails backend StringConstraints. ``changes``
 * is enforced non-empty; per-field type validation is left to the
 * server (single source of truth for SAFE catalog adapters).
 */
export const MinorCorrectionRequestSchema = z.object({
  version: z.number().int().min(1),
  reason: z
    .string()
    .trim()
    .min(10, "Vui lòng nhập lý do tối thiểu 10 ký tự")
    .max(1000, "Lý do tối đa 1000 ký tự"),
  changes: z
    .record(z.string(), z.unknown())
    .refine(
      (obj) => Object.keys(obj).length > 0,
      { message: "Chưa có thay đổi nào" },
    ),
})
export type MinorCorrectionRequest = z.infer<typeof MinorCorrectionRequestSchema>

