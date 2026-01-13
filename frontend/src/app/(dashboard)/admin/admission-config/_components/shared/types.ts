/**
 * Shared Types for Admission Config
 *
 * Common interfaces and types used across all admission config components
 */

// ============================================
// BASE TYPES
// ============================================

export interface BaseEntity {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  display_order: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface BaseEntityCreate {
  code: string;
  name: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface BaseEntityUpdate {
  name?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

// Form data type for CRUD operations - uses string/number/boolean for form inputs
export interface BaseFormData {
  code?: string;
  name?: string;
  name_vi?: string;
  name_en?: string;
  major_code?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
  requires_gpa?: boolean;
  requires_subject_scores?: boolean;
  organization_unit_id?: number | null;
  major_program_id?: number | null;
  offering_type_id?: number | null;
  offering_id?: number | null;
  academic_year?: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
  [key: string]: string | number | boolean | null | undefined;
}

// ============================================
// STATE MACHINE TYPES
// ============================================

export type Phase1Step =
  | 'units'
  | 'offering-types'
  | 'methods'
  | 'document-types'
  | 'subject-groups';

export type Phase2Step =
  | 'majors'
  | 'offerings'
  | 'academic-info';

export interface SelectionContext {
  academicYear: number;
  majorProgramId: number;
  offeringId: number;
  academicInfoId: number;
}

export type Phase3View =
  | { type: 'list' }
  | { type: 'matrix' }
  | { type: 'wizard'; pathId?: number; wizardStep?: number };

export type AdmissionConfigState =
  | { type: 'welcome' }
  | { type: 'phase1'; step: Phase1Step }
  | { type: 'phase2'; step: Phase2Step }
  | { type: 'select-context' }
  | { type: 'phase3'; context: SelectionContext; view: Phase3View };

// ============================================
// NAVIGATION TYPES
// ============================================

export interface NavigationTarget {
  state: AdmissionConfigState;
  replace?: boolean;
}

export interface PhaseProgress {
  completed: number;
  total: number;
  steps: StepStatus[];
}

export interface StepStatus {
  id: string;
  label: string;
  status: 'completed' | 'in-progress' | 'pending';
  enabled: boolean;
}

export interface CoverageSummary {
  totalPaths: number;
  readyPaths: number;
  allReady: boolean;
}

// ============================================
// CRUD TABLE TYPES
// ============================================

export interface CRUDTableAction<T> {
  label: string;
  icon?: React.ReactNode;
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
  onClick: (item: T) => void;
  show?: (item: T) => boolean;
}

export interface CRUDTableColumn<T> {
  key: keyof T | string;
  header: string;
  render?: (item: T) => React.ReactNode;
  sortable?: boolean;
  width?: string;
}

// ============================================
// FORM TYPES
// ============================================

export interface FormFieldConfig {
  name: string;
  label: string;
  type: 'text' | 'textarea' | 'number' | 'select' | 'checkbox' | 'multi-select';
  placeholder?: string;
  required?: boolean;
  options?: { value: string | number; label: string }[];
  disabled?: boolean;
  helperText?: string;
}

// ============================================
// PHASE 1 ENTITY TYPES
// ============================================

export interface OrganizationUnit extends BaseEntity {
  unit_type?: string;
  parent_id?: number | null;
}

export type OfferingType = BaseEntity;

export interface AdmissionMethod extends BaseEntity {
  requires_gpa: boolean;
  requires_subject_scores: boolean;
}

export interface DocumentType extends BaseEntity {
  category?: string;
}

export interface Subject extends BaseEntity {
  name_vi: string;
  name_en?: string;
}

export interface SubjectGroup extends BaseEntity {
  subjects?: SubjectInGroup[];
}

export interface SubjectInGroup {
  id: number;
  code: string;
  name_vi: string;
  position: number;
}

// ============================================
// PHASE 2 ENTITY TYPES
// ============================================

export interface MajorProgram extends BaseEntity {
  major_code: string;
  degree_level_id?: number;
  organization_unit_id?: number;
}

export interface ProgramOffering extends BaseEntity {
  major_program_id: number;
  offering_type_id: number;
}

export interface OfferingAcademicInfo {
  id: number;
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

export interface OfferingAcademicInfoCreate {
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}

export interface OfferingAcademicInfoUpdate {
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}

// ============================================
// PHASE 3 ENTITY TYPES (ADMISSION PATHS)
// ============================================

export interface CoverageRow {
  path_id: number;
  method_name: string;
  method_code: string;
  status: "draft" | "active" | "inactive" | "archived";
  has_criteria: boolean;
  has_documents: boolean;
  has_quota: boolean;
  can_activate: boolean;
  validation_errors: string[];
}

export interface CoverageMatrixResponse {
  academic_info_id: number;
  rows: CoverageRow[];
  total_paths: number;
  paths_ready: number;
  all_ready: boolean;
}

// ============================================
// API RESPONSE TYPES
// ============================================

export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface ApiError {
  detail: string;
  field?: string;
}
