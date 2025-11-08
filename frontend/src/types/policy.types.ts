// src/types/policy.types.ts
/**
 * TypeScript types for Casbin Policy Management System
 */

export interface PolicyRule {
  subject: string;
  object: string;
  action: string;
}

export interface RoleInfo {
  name: string;
  display_name: string;
  description: string;
  is_system_role: boolean;
  template_id: string | null;
  policy_count: number;
}

export interface TemplateInfo {
  id: string;
  display_name: string;
  description: string;
  category: "core" | "custom";
  policies: PolicyRule[];
}

export interface PolicyValidationResult {
  is_valid: boolean;
  is_safe: boolean;
  severity: "info" | "warning" | "critical";
  warnings: string[];
  affected_users: number[];
}

export interface PolicyBatchResult {
  added: number;
  removed: number;
  skipped: number;
  blocked: number;
  errors: string[];
  warnings: string[];
}

export interface PolicyStatistics {
  total_policies: number;
  total_roles: number;
  total_grouping_policies: number;
}

// Request types
export interface PolicyCreateRequest {
  subject: string;
  object: string;
  action: string;
}

export interface PolicyBatchRequest {
  policies: PolicyCreateRequest[];
  validate?: boolean;
  dry_run?: boolean;
}

export interface PolicyValidationRequest {
  subject: string;
  object: string;
  action: string;
  operation: "add" | "remove";
}

export interface TemplateApplicationRequest {
  template_id: string;
  role: string;
  validate?: boolean;
}

// Response types
export interface RolesListResponse {
  roles: RoleInfo[];
}

export interface TemplatesListResponse {
  templates: TemplateInfo[];
}
