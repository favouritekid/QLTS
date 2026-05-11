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
// ============================================
// DOMAIN FORM TYPES (STRICT)
// ============================================

export interface OfferingTypeFormValues {
  code: string;
  name: string;
  display_order: number;
  is_active: boolean;
}

export interface OrganizationUnitFormValues {
  name: string;
  type: string;
  description: string;
  parent_id: number | null;
  is_active: boolean;
}

export interface AdmissionMethodFormValues {
  code: string;
  name: string;
  description: string;
  requires_gpa: boolean;
  requires_subject_scores: boolean;
  display_order: number;
  is_active: boolean;
}

export interface DocumentTypeFormValues {
  code: string;
  name: string;
  description: string;
  display_order: number;
  is_active: boolean;
}

export interface SubjectFormValues {
  code: string;
  name_vi: string;
  name_en: string;
  display_order: number;
  is_active: boolean;
}

export interface SubjectGroupFormValues {
  code: string;
  name: string;
  description: string;
  display_order: number;
  is_active: boolean;
}

export interface MajorProgramFormValues {
  code: string;
  name: string;
  degree_level: string;
  unit_id: number | null;
  is_heavy: boolean;
  is_active: boolean;
}

export interface ProgramOfferingFormValues {
  program_id: number | null;
  offering_type_id: number | null;
  duration_semesters: number;
  total_credits: number;
  scoring_rules: ScoringRules;
  is_active: boolean;
}

export interface AcademicInfoFormValues {
  offering_id: number | null;
  academic_year: number;
  tuition_fee_per_year: number;
  annual_admission_quota: number;
  is_published: boolean;
}



// ============================================
// STATE MACHINE TYPES
// ============================================

export type Phase1Step =
  | 'units'
  | 'offering-types'
  | 'methods'
  | 'document-types'
  | 'subject-groups'
  | 'rounds';  // Phase 2 v8.2 PR-2A v2 — đợt tuyển sinh year-level

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
  | { type: 'phase3'; context: SelectionContext; view: Phase3View }
  // Phase 2 v8.2 PR-2D.1 v2 — global quota matrix overview (ALL ngành × đợt)
  // KHÔNG cần SelectionContext vì matrix tổng quan all academic_info
  | { type: 'quota-matrix-overview'; academicYear: number };

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

// OrganizationUnit doesn't extend BaseEntity because it lacks code and display_order fields
export interface OrganizationUnit {
  id: number;
  name: string;
  type: string; // Backend field name is "type" not "unit_type"
  description?: string | null;
  parent_id?: number | null;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  children?: OrganizationUnit[];
}

export type OfferingType = BaseEntity;

export interface AdmissionMethod extends BaseEntity {
  requires_gpa: boolean;
  requires_subject_scores: boolean;
}

export type DocumentType = BaseEntity;


export interface DocumentGroupItem {
  id: number;
  document_type_id: number;
  document_type_name: string;
  is_mandatory: boolean;
  requires_upload: boolean;
  submission_format?: string | null;
  display_order: number;
}

export interface SharedDocumentGroup {
  id: number;
  offering_type_id: number;
  code: string;
  name: string;
  items: DocumentGroupItem[];
}

export interface DocumentGroupItemCreate {
  document_type_id: number;
  is_mandatory?: boolean;
  requires_upload?: boolean;
  submission_format?: string | null;
  display_order?: number;
}

export interface SharedDocumentGroupUpdate {
  items: DocumentGroupItemCreate[];
}

export interface Subject extends BaseEntity {
  name_vi: string;
  name_en?: string;
}

export interface SubjectGroup extends BaseEntity {
  subjects?: SubjectInGroup[];
}

export interface SubjectInGroup {
  code: string;
  name_vi: string;
  position: number;
}

// ============================================
// PHASE 2 ENTITY TYPES
// ============================================

// MajorProgram doesn't extend BaseEntity because it lacks description and display_order fields
export interface MajorProgram {
  id: number;
  code: string;
  name: string;
  degree_level: string;
  unit_id: number;
  is_active: boolean;
  is_heavy: boolean;
  offerings?: ProgramOffering[];
  created_at?: string;
  updated_at?: string;
}

// ProgramOffering doesn't extend BaseEntity because it lacks code, name, description, display_order fields
export interface ProgramOffering {
  id: number;
  program_id: number;
  offering_type_id?: number;
  offering_type: string;
  duration_semesters?: number;
  total_credits?: number;
  scoring_rules?: ScoringRules;
  is_active: boolean;
  program?: {
    id: number;
    name: string;
    code: string;
    degree_level: string;
    is_active: boolean;
    is_heavy: boolean;
  };
  academic_info_history?: OfferingAcademicInfo[];
  created_at?: string;
  updated_at?: string;
}

export interface ScoringRules {
  hot_level?: number; // 0=Normal, 1=Hot, 2=Very Hot
  target_age_min?: number;
  target_age_max?: number;
  required_education?: string; // "thpt", "cao_dang", "dai_hoc"
}

export interface SemesterTuition {
  id: number;
  academic_info_id: number;
  semester_no: number;
  amount: number;
  notes?: string | null;
}

export interface OfferingAcademicInfo {
  id: number;
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published: boolean;
  target_audience?: string;
  cutoff_score_previous_year?: number;
  applied_discount_policy_ids?: number[];
  semester_tuitions?: SemesterTuition[];
  created_at: string;
  updated_at: string;
  // Computed fields from backend
  path_count?: number;
  admission_status?: 'CONFIGURED' | 'READY' | 'NOT_ELIGIBLE';
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

// ============================================
// CRUD MUTATION PAYLOAD TYPES
// These types eliminate `as any` casts in admin panels
// ============================================

// Organization Unit payloads
export interface OrganizationUnitCreate {
  name: string;
  type: string;
  description?: string | null;
  parent_id?: number | null;
}

export interface OrganizationUnitUpdate {
  name?: string;
  type?: string;
  description?: string | null;
  parent_id?: number | null;
  is_active?: boolean;
}

// Offering Type payloads
export interface OfferingTypeCreate {
  code: string;
  name: string;
  display_order?: number;
  is_active?: boolean;
}

export interface OfferingTypeUpdate {
  code?: string;
  name?: string;
  display_order?: number;
  is_active?: boolean;
}

// Admission Method payloads
export interface AdmissionMethodCreate {
  code: string;
  name: string;
  description?: string;
  requires_gpa?: boolean;
  requires_subject_scores?: boolean;
  display_order?: number;
  is_active?: boolean;
}

export interface AdmissionMethodUpdate {
  name?: string;
  description?: string;
  requires_gpa?: boolean;
  requires_subject_scores?: boolean;
  display_order?: number;
  is_active?: boolean;
}

// Document Type payloads
export interface DocumentTypeCreate {
  code: string;
  name: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface DocumentTypeUpdate {
  name?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

// Subject payloads
export interface SubjectCreate {
  code: string;
  name_vi: string;
  name_en?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface SubjectUpdate {
  name_vi?: string;
  name_en?: string;
  display_order?: number;
  is_active?: boolean;
}

// Subject Group payloads
export interface SubjectGroupCreate {
  code: string;
  name: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface SubjectGroupUpdate {
  name?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

// Major Program payloads
export interface MajorProgramCreate {
  code: string;
  name: string;
  degree_level: string;
  unit_id: number;
  is_heavy?: boolean;
  is_active?: boolean;
}

export interface MajorProgramUpdate {
  name?: string;
  degree_level?: string;
  unit_id?: number;
  is_heavy?: boolean;
  is_active?: boolean;
}

// Program Offering payloads
export interface ProgramOfferingCreate {
  program_id: number;
  offering_type_id: number;
  offering_type: string;
  duration_semesters?: number;
  total_credits?: number;
  scoring_rules?: ScoringRules;
  is_active?: boolean;
}

export interface ProgramOfferingUpdate {
  duration_semesters?: number;
  total_credits?: number;
  scoring_rules?: ScoringRules;
  is_active?: boolean;
}


// Academic Info payloads
export interface AcademicInfoCreate {
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}

export interface AcademicInfoUpdate {
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}
