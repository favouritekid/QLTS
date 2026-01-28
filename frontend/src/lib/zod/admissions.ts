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
})

export type DocumentItem = z.infer<typeof documentItemSchema>

// ==============================================================================
// ADMISSION PROFILE SCHEMAS
// ==============================================================================

/**
 * Create Admission Profile Schema
 * Used for POST /api/admissions
 * REFACTORED (Phase 2): Now requires admission_method_id for AdmissionPath lookup
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
})

export type AdmissionProfileUpdateInput = z.input<
  typeof admissionProfileUpdateSchema
>

export type AdmissionProfileUpdate = z.output<
  typeof admissionProfileUpdateSchema
>

/**
 * Subject Group Schema (for applied_rules snapshot)
 * Preserved from AdmissionPath for audit trail
 */
export const subjectGroupSnapshotSchema = z.object({
  code: z.string(), // e.g., "A00", "D01"
  name: z.string(), // e.g., "Toán - Lý - Hóa"
  subjects: z.array(z.string()), // e.g., ["math", "physics", "chemistry"]
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
  place_of_birth: z.string().nullable(),
  native_place: z.string().nullable(),
  union_entry_date: z.string().datetime({ offset: true }).nullable(),
  party_entry_date: z.string().datetime({ offset: true }).nullable(),
  party_official_entry_date: z.string().datetime({ offset: true }).nullable(),
  // Status (extended for async-first workflow)
  status: z.enum(["draft", "submitted", "resubmitted", "approved", "rejected", "confirmed", "enrolled"]),
  version: z.number().int().optional(), // Optimistic locking
  academic_year: z.number().int().optional(), // Academic year
  applied_rules: appliedRulesSchema, // ✅ NEW: Properly typed with 18 fields
  family_info: z.array(familyMemberSchema).default([]),
  academic_history: z.array(academicRecordSchema).default([]),
  admission_scores: admissionScoreSchema.nullable(),
  documents_checklist: z.array(documentItemSchema).default([]),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  // Nested relationships (optional)
  lead: z.any().optional().nullable(),
  student: z.any().optional().nullable(),
  
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
    missing_count: z.number().int()
  }).nullable().optional(),
  
  // Eligibility status (backend-computed)
  eligibility_status: z.enum(["eligible", "ineligible", "pending"]).default("pending"),
  
  // Validation errors (reasons for ineligibility)
  validation_errors: z.array(z.string()).default([]),
  
  // Available workflow actions
  available_actions: z.array(z.string()).default([]),
  
  // Profile completion percentage (0-100)
  completion_percent: z.number().int().min(0).max(100).default(0),
  
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
      count: z.number().int()
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

  // Ticket #2: Backend-computed qualification status
  is_qualified: z.boolean().nullable().optional().describe("Whether profile meets admission criteria. Computed by backend."),

  // =========================================================================
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
  confirmed: "bg-success-100 text-success-800",
  enrolled: "bg-info-100 text-info-800",
  overridden: "bg-purple-100 text-purple-800",
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
  confirmed: "Đã xác nhận",
  enrolled: "Đã nhập học",
  overridden: "Đã override",
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

