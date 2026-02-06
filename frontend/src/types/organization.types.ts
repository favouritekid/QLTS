// src/types/organization.types.ts

// =============================================================================
// 3-TIER ARCHITECTURE TYPES (NEW)
// =============================================================================

// NOTE: AdmissionCriterion interface REMOVED
// Use AdmissionPath API with useAdmissionPathsForOffering hook instead
// See: frontend/src/hooks/admissions/useAdmissionPaths.ts

/**
 * TIER 3: OfferingAcademicInfo (Thông tin tuyển sinh theo năm)
 * Thông tin động thay đổi theo năm học
 */
export interface OfferingAcademicInfo {
  id: number;
  offering_id: number; // Foreign key to ProgramOffering (Tier 2)
  academic_year: number; // Năm học (vd: 2025)
  tuition_fee_per_year?: number | null; // Học phí/năm
  annual_admission_quota?: number | null; // Chỉ tiêu tuyển sinh
  is_published: boolean; // Trạng thái công khai
  is_deleted: boolean; // Soft delete flag - NEVER hard delete financial/historical data
  // NOTE: admission_criteria removed - use AdmissionPath API instead
  target_audience?: string | null; // Đối tượng tuyển sinh
  cutoff_score_previous_year?: number | null; // Điểm chuẩn năm trước
  applied_discount_policy_ids?: number[] | null; // Danh sách ID chính sách ưu đãi áp dụng

  // Audit trail
  created_at?: string | null;
  updated_at?: string | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
}

/**
 * Form data for creating OfferingAcademicInfo (Tier 3)
 */
export interface OfferingAcademicInfoCreate {
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number | null;
  annual_admission_quota?: number | null;
  is_published?: boolean;
  // NOTE: admission_criteria removed - use AdmissionPath API instead
  target_audience?: string | null;
  cutoff_score_previous_year?: number | null;
  applied_discount_policy_ids?: number[] | null;
}

/**
 * Form data for updating OfferingAcademicInfo (Tier 3)
 */
export interface OfferingAcademicInfoUpdate {
  academic_year?: number;
  tuition_fee_per_year?: number | null;
  annual_admission_quota?: number | null;
  is_published?: boolean;
  // NOTE: admission_criteria removed - use AdmissionPath API instead
  target_audience?: string | null;
  cutoff_score_previous_year?: number | null;
  applied_discount_policy_ids?: number[] | null;
}

/**
 * TIER 2: ProgramOffering (Loại hình đào tạo)
 * Thông tin tĩnh về loại hình (vd: "Chính quy", "Liên thông")
 */

/**
 * ScoringRules - Cấu hình chấm điểm Fit Score cho từng ngành
 */
export interface ScoringRules {
  hot_level?: number; // 0=Bình thường, 1=Hot, 2=Rất Hot (tối đa +10 điểm)
  target_age_min?: number | null; // Độ tuổi mục tiêu tối thiểu (vd: 18)
  target_age_max?: number | null; // Độ tuổi mục tiêu tối đa (vd: 25)
  required_education?: string | null; // Trình độ yêu cầu: "thpt", "cao_dang", "dai_hoc"
}

export interface ProgramOffering {
  id: number;
  program_id: number; // Foreign key to MajorProgram (Tier 1)
  offering_type: string; // Tên loại hình (vd: "Chính quy")
  duration_semesters?: number | null; // Số kỳ học
  total_credits?: number | null; // Tổng số tín chỉ
  is_active: boolean; // Soft delete flag
  scoring_rules?: ScoringRules | null; // Cấu hình chấm điểm Fit Score

  // Nested program info for display
  program?: {
    id: number;
    name: string;
    degree_level: string;
    code: string;
    is_active: boolean;
  } | null;

  // ✅ Removed academic_info_history - should be loaded on-demand
  // Use dedicated endpoints to fetch academic info when needed
}

/**
 * Form data for creating ProgramOffering (Tier 2)
 */
export interface ProgramOfferingCreate {
  program_id: number;
  offering_type: string;
  duration_semesters?: number | null;
  total_credits?: number | null;
  is_active?: boolean;
  scoring_rules?: ScoringRules | null;
}

/**
 * Form data for updating ProgramOffering (Tier 2)
 */
export interface ProgramOfferingUpdate {
  offering_type?: string;
  duration_semesters?: number | null;
  total_credits?: number | null;
  is_active?: boolean;
  scoring_rules?: ScoringRules | null;
}

/**
 * TIER 1: MajorProgram (Ngành/Trình độ)
 * Định danh duy nhất bằng Mã ngành (code)
 */
export interface MajorProgram {
  id: number;
  name: string; // Tên hiển thị (vd: "Cao đẳng Công nghệ thông tin")
  degree_level: string; // Trình độ (vd: "Cao đẳng")
  code: string; // Mã ngành tuyển sinh (vd: "6480201") - UNIQUE
  is_active: boolean; // Soft delete flag
  is_heavy: boolean; // Ngành nghề nặng nhọc, độc hại, nguy hiểm
  unit_id: number; // Foreign key to OrganizationUnit

  // Nested: Offerings (Tier 2)
  offerings: ProgramOffering[];

  // Relationship
  unit?: OrganizationUnit;
}

/**
 * Form data for creating MajorProgram (Tier 1)
 */
export interface MajorProgramCreate {
  name: string;
  degree_level: string;
  code: string;
  unit_id: number;
  is_active?: boolean;
  is_heavy?: boolean; // Ngành nghề nặng nhọc, độc hại
}

/**
 * Form data for updating MajorProgram (Tier 1)
 */
export interface MajorProgramUpdate {
  name?: string;
  degree_level?: string;
  unit_id?: number;
  is_active?: boolean;
  is_heavy?: boolean; // Ngành nghề nặng nhọc, độc hại
  // Note: 'code' cannot be updated (business rule)
}

// =============================================================================
// ORGANIZATION UNIT TYPES
// =============================================================================

/**
 * Organization Unit (Đơn vị tổ chức)
 * Updated to use MajorProgram instead of Major
 */
export interface OrganizationUnit {
  id: number;
  name: string;
  type: string;
  description?: string | null;
  parent_id: number | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  children: OrganizationUnit[];
  major_programs: MajorProgram[]; // ⬅ Changed from 'majors'
  // Relationship fields (computed)
  parent?: OrganizationUnit | null;
  // Aggregated user count (populated by backend)
  user_count?: number;
}

/**
 * Form data for creating organization unit
 */
export interface OrganizationUnitCreate {
  name: string;
  type: string;
  description?: string | null;
  parent_id?: number | null;
}

/**
 * Form data for updating organization unit
 */
export interface OrganizationUnitUpdate {
  name?: string;
  type?: string;
  description?: string | null;
  parent_id?: number | null;
}

/**
 * API Response for organization list
 */
export interface OrganizationListResponse {
  units: OrganizationUnit[];
  total: number;
}

/**
 * Flattened unit for easier rendering (with hierarchy info)
 */
export interface FlattenedUnit {
  unit: OrganizationUnit;
  level: number;
  hasChildren: boolean;
}

// =============================================================================
// TREE WITH AGGREGATION TYPES (UPDATED FOR 3-TIER)
// =============================================================================

/**
 * MajorProgram with aggregated statistics (for tree view)
 */
export interface MajorProgramWithStats {
  id: number;
  name: string;
  code: string;
  degree_level: string;
  total_admission_quota?: number | null; // Aggregated from all offerings
  avg_tuition_fee?: number | null; // Average tuition across offerings
  offerings_count?: number; // Number of active offerings
}

/**
 * Aggregated statistics for a unit (including descendants)
 */
export interface UnitAggregatedStats {
  total_programs: number; // Total MajorPrograms (including descendants)
  direct_programs: number; // Direct MajorPrograms only
  total_offerings: number; // Total ProgramOfferings
  total_admission_quota?: number | null;
  avg_tuition_fee?: number | null;
  min_tuition_fee?: number | null;
  max_tuition_fee?: number | null;
}

/**
 * Organization tree node with majors and aggregated data
 */
export interface OrganizationTreeNodeWithAggregation {
  id: number;
  name: string;
  type: string;
  description?: string | null;
  parent_id: number | null;
  is_active: boolean;
  major_programs: MajorProgramWithStats[]; // ⬅ Changed from 'majors'
  stats: UnitAggregatedStats;
  children: OrganizationTreeNodeWithAggregation[];
}

/**
 * Flattened tree node for rendering
 */
export interface FlattenedTreeNode {
  node: OrganizationTreeNodeWithAggregation;
  level: number;
  isExpanded: boolean;
  hasChildren: boolean;
}

// =============================================================================
// SYSTEM CONFIGURATION TYPES
// =============================================================================

/**
 * ConfigDegreeLevel - Degree level configuration (Trình độ đào tạo)
 * Used for MajorProgram creation dropdown
 */
export interface ConfigDegreeLevel {
  id: number;
  code: string; // e.g., "cao_dang", "dai_hoc"
  name: string; // e.g., "Cao đẳng", "Đại học"
  display_order: number;
  is_active: boolean;
}

export interface ConfigDegreeLevelCreate {
  code: string;
  name: string;
  display_order?: number;
  is_active?: boolean;
}

export interface ConfigDegreeLevelUpdate {
  code?: string;
  name?: string;
  display_order?: number;
  is_active?: boolean;
}

/**
 * ConfigOfferingType - Offering type configuration (Loại hình đào tạo)
 * Used for ProgramOffering creation dropdown
 */
export interface ConfigOfferingType {
  id: number;
  code: string; // e.g., "chinh_quy", "lien_thong"
  name: string; // e.g., "Chính quy", "Liên thông"
  display_order: number;
  is_active: boolean;
}

export interface ConfigOfferingTypeCreate {
  code: string;
  name: string;
  display_order?: number;
  is_active?: boolean;
}

export interface ConfigOfferingTypeUpdate {
  code?: string;
  name?: string;
  display_order?: number;
  is_active?: boolean;
}

// =====================================================================
// CONFIG DOCUMENT TYPE TYPES
// =====================================================================

export interface ConfigDocumentType {
  id: number;
  code: string; // e.g., "hoc_ba", "bang_tot_nghiep"
  name: string; // e.g., "Học bạ", "Bằng tốt nghiệp"
  description?: string | null; // Detailed description
  display_order: number;
  is_active: boolean;
}

export interface ConfigDocumentTypeCreate {
  code: string;
  name: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

export interface ConfigDocumentTypeUpdate {
  code?: string;
  name?: string;
  description?: string;
  display_order?: number;
  is_active?: boolean;
}

// =============================================================================
// ASSIGNMENT CONFIG TYPES
// =============================================================================

/**
 * AssignmentConfigParams - Flexible configuration parameters for lead assignment
 * Stores strategy, rules, and settings as JSON
 */
export interface AssignmentConfigParams {
  strategy?: string; // e.g., "round_robin", "skill_based", "load_balanced"
  max_concurrent?: number; // Maximum concurrent assignments per officer
  auto_assign?: boolean; // Enable automatic assignment
  priority_skills?: string[]; // Skills to prioritize in assignment
  [key: string]: string | number | boolean | string[] | undefined; // Flexible params for future extensions
}

/**
 * AssignmentConfig - Assignment configuration for an organization unit
 * Stores lead distribution and assignment rules
 */
export interface AssignmentConfig {
  params: AssignmentConfigParams;
}

/**
 * Form data for updating AssignmentConfig
 */
export interface AssignmentConfigUpdate {
  params: AssignmentConfigParams;
}

// =============================================================================
// SKILL RULE TYPES
// =============================================================================

/**
 * SkillRule - Skill-based assignment rule
 * Maps lead attributes to required officer skills
 */
export interface SkillRule {
  id: number;
  lead_attribute: string; // Lead attribute to match (e.g., "source", "major")
  attribute_value: string; // Value to match (e.g., "facebook", "Computer Science")
  required_skill: string; // Required officer skill (e.g., "Social Media Marketing")
  priority?: number; // Rule priority (optional, for ordering)
}

/**
 * Form data for creating SkillRule
 */
export interface SkillRuleCreate {
  lead_attribute: string;
  attribute_value: string;
  required_skill: string;
  priority?: number;
}
