// src/types/organization.types.ts

/**
 * Organization Unit (Đơn vị tổ chức)
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
  majors: Major[];
  // Relationship fields (computed)
  parent?: OrganizationUnit | null;
}

/**
 * Major (Ngành học)
 */
export interface Major {
  id: number;
  name: string;
  code: string;
  description?: string | null;
  unit_id: number;
  unit?: OrganizationUnit;
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
 * Form data for creating major
 */
export interface MajorCreate {
  name: string;
  code: string;
  description?: string | null;
  unit_id: number;
}

/**
 * Form data for updating major
 */
export interface MajorUpdate {
  name?: string;
  code?: string;
  description?: string | null;
  unit_id?: number;
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

/**
 * Major Academic Info (Year-versioned data)
 */
export interface MajorAcademicInfo {
  id: number;
  major_id: number;
  academic_year: number;
  target_audience?: string | null;
  detailed_info?: string | null;
  current_year_benefits?: string | null;
  tuition_fee_per_year?: number | null;
  annual_admission_quota?: number | null;
  is_published: boolean;
  created_by_user_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Form data for creating major academic info
 */
export interface MajorAcademicInfoCreate {
  major_id: number;
  academic_year: number;
  target_audience?: string | null;
  detailed_info?: string | null;
  current_year_benefits?: string | null;
  tuition_fee_per_year?: number | null;
  annual_admission_quota?: number | null;
  is_published?: boolean;
}

/**
 * Form data for updating major academic info
 */
export interface MajorAcademicInfoUpdate {
  target_audience?: string | null;
  detailed_info?: string | null;
  current_year_benefits?: string | null;
  tuition_fee_per_year?: number | null;
  annual_admission_quota?: number | null;
  is_published?: boolean;
}
