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
