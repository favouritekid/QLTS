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
  
  // Legacy fields for backward compatibility
  math_score: z
    .number()
    .min(0, "Điểm Toán phải từ 0 trở lên")
    .max(10, "Điểm Toán không được quá 10")
    .optional()
    .nullable(),
  literature_score: z
    .number()
    .min(0, "Điểm Văn phải từ 0 trở lên")
    .max(10, "Điểm Văn không được quá 10")
    .optional()
    .nullable(),
  english_score: z
    .number()
    .min(0, "Điểm Tiếng Anh phải từ 0 trở lên")
    .max(10, "Điểm Tiếng Anh không được quá 10")
    .optional()
    .nullable(),
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
  submission_format_confirmed: z.boolean().optional(),
  // Status and upload info
  status: z.enum(["missing", "uploaded", "verified", "rejected"]),
  file_path: z
    .string()
    .max(512, "Đường dẫn file không được quá 512 ký tự")
    .nullable()
    .optional(),
  uploaded_at: z
    .string()
    .nullable()
    .optional(),
  rejection_reason: z.string().nullable().optional(),
})

export type DocumentItem = z.infer<typeof documentItemSchema>

// ==============================================================================
// ADMISSION PROFILE SCHEMAS
// ==============================================================================

/**
 * Create Admission Profile Schema
 * Used for POST /api/admissions
 */
export const admissionProfileCreateSchema = z.object({
  lead_id: z
    .number()
    .int("Lead ID phải là số nguyên")
    .positive("Lead ID phải là số dương"),
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
  full_name: z.string().max(255).optional().nullable(),
  phone: z
    .string()
    .regex(/^0\d{9,10}$/, "Số điện thoại không hợp lệ")
    .optional()
    .nullable()
    .or(z.literal("")),
  email: z.string().email("Email không hợp lệ").max(255).optional().nullable().or(z.literal("")),
  dob: z.string().datetime({ offset: true }).optional().nullable(),
  gender: z.string().max(50).optional().nullable(),
  social_insurance_number: z.string().max(50).optional().nullable(),
  nationality: z.string().max(100).optional().nullable(),
  ethnicity: z.string().max(100).optional().nullable(),
  religion: z.string().max(100).optional().nullable(),
  disability_type: z.string().max(100).optional().nullable(),
  permanent_province: z.string().max(100).optional().nullable(),
  permanent_district: z.string().max(100).optional().nullable(),
  permanent_ward: z.string().max(100).optional().nullable(),
  place_of_birth: z.string().max(255).optional().nullable(),
  native_place: z.string().max(255).optional().nullable(),
  
  // Political Info Dates
  union_entry_date: z.string().datetime({ offset: true }).optional().nullable(),
  party_entry_date: z.string().datetime({ offset: true }).optional().nullable(),
  party_official_entry_date: z.string().datetime({ offset: true }).optional().nullable(),

  // Identity
  citizen_id: z
    .string()
    .regex(/^\d{12}$/, "CCCD/CMND phải là 12 chữ số")
    .optional()
    .nullable()
    .or(z.literal("")), // Allow empty string for drafts

  // JSONB Arrays
  family_info: z.array(familyMemberSchema).optional().nullable(),
  academic_history: z.array(academicRecordSchema).optional().nullable(),
  admission_scores: admissionScoreSchema.optional().nullable(),
  documents_checklist: z.array(documentItemSchema).optional().nullable(),
})

export type AdmissionProfileUpdate = z.infer<
  typeof admissionProfileUpdateSchema
>

/**
 * Admission Profile Response Schema
 * Used for API responses (GET, POST, PUT)
 * 
 * Phase 7: Added permissions, eligibility_status, validation_errors, 
 * available_actions, completion_percent for Frontend Thin Client compliance.
 */
export const admissionProfileResponseSchema = z.object({
  id: z.number(),
  lead_id: z.number(),
  citizen_id: z.string().optional().nullable(),
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
  applied_rules: z.record(z.string(), z.any()), // JSONB object
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
  
  // Phase 0.9: Step Status (Backend computes, FE renders)
  // Note: Record keys are always strings in JSON, convert on read in component
  step_status: z.record(z.string(), z.enum(["success", "warning", "error", "locked"])).optional().nullable(),
  
  // Computed scores (backend-calculated)
  total_score: z.number().optional().nullable(),
  average_score: z.number().optional().nullable(),
})

export type AdmissionProfileResponse = z.infer<
  typeof admissionProfileResponseSchema
>

/**
 * Submit Response Schema
 * Used for POST /api/admissions/{id}/submit response
 * 
 * Phase 7: Updated for async-first workflow (ADR-FE-003)
 * - May return intermediate statuses (submitted, resubmitted)
 * - Includes validation_errors from backend
 */
export const admissionSubmitResponseSchema = z.object({
  status: z.enum(["draft", "submitted", "resubmitted", "approved", "rejected"]).nullable(),
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
 * Get status badge color
 * Phase 7: Updated to handle async-first workflow statuses
 */
export function getStatusColor(
  status: "draft" | "submitted" | "resubmitted" | "approved" | "rejected" | "confirmed" | "enrolled"
): string {
  switch (status) {
    case "draft":
      return "bg-gray-100 text-gray-800"
    case "submitted":
    case "resubmitted":
      return "bg-yellow-100 text-yellow-800"
    case "approved":
      return "bg-green-100 text-green-800"
    case "rejected":
      return "bg-red-100 text-red-800"
    case "confirmed":
      return "bg-emerald-100 text-emerald-800"
    case "enrolled":
      return "bg-blue-100 text-blue-800"
    default:
      return "bg-gray-100 text-gray-800"
  }
}

/**
 * Get status label (Vietnamese)
 * Phase 7: Updated to handle async-first workflow statuses
 */
export function getStatusLabel(
  status: "draft" | "submitted" | "resubmitted" | "approved" | "rejected" | "confirmed" | "enrolled"
): string {
  switch (status) {
    case "draft":
      return "Nháp"
    case "submitted":
      return "Chờ duyệt"
    case "resubmitted":
      return "Nộp lại"
    case "approved":
      return "Đã duyệt"
    case "rejected":
      return "Từ chối"
    case "confirmed":
      return "Đã xác nhận"
    case "enrolled":
      return "Đã nhập học"
    default:
      return status
  }
}
