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
  scoring_method: z.string().default("sum"),
  
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
  display_name: z.string().max(255).optional().nullable(),
  display_order: z.number().int().min(0).optional().nullable(),
  visibility: z.enum(["public", "internal"]).optional(),
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
  subject_selection_mode: z.enum(["fixed", "dynamic"]).default("fixed"),
  scoring_method: z.enum(["sum", "avg"]).default("sum"),
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
  status: admissionPathStatusEnum,
  display_name: z.string().nullable(),
  display_order: z.number(),
  visibility: z.enum(["public", "internal"]),
  activated_at: z.string().datetime({ offset: true }).nullable(),
  activated_by: z.number().nullable(),
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
  validation_errors: z.array(z.string()).default([]),
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
 * The `source` field indicates whether document config comes from:
 * - "shared": Applies to all methods (admission_method_id = NULL)
 * - "method_override": Method-specific config that overrides shared
 */
export const resolvedDocumentResponseSchema = z.object({
  document_type_id: z.number(),
  document_type_code: z.string(),
  document_type_name: z.string(),
  is_mandatory: z.boolean(),
  requires_upload: z.boolean(),
  submission_format: z.string().nullable(),
  display_order: z.number(),
  source: z.enum(["shared", "method_override"]),
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
      return "bg-gray-100 text-gray-800"
    case "active":
      return "bg-green-100 text-green-800"
    case "inactive":
      return "bg-yellow-100 text-yellow-800"
    case "archived":
      return "bg-red-100 text-red-800"
    default:
      return "bg-gray-100 text-gray-800"
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
