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

// ⚠️ Tên trường phải là `run_validation`, KHÔNG phải `validate`.
// Pydantic `PolicyBatchRequest` (schemas/permissions.py:98) khai
// `run_validation: bool = Field(True, ...)` và mặc định BỎ QUA khoá lạ, nên một
// body gửi `validate: false` không hề bị từ chối — nó chỉ bị nuốt IM LẶNG và
// backend vẫn chạy với default `True`. Đặt sai tên ở đây là tắt được cờ trên
// giao diện mà server không bao giờ nghe thấy.
export interface PolicyBatchRequest {
  policies: PolicyCreateRequest[];
  run_validation?: boolean;
  dry_run?: boolean;
}

export interface PolicyValidationRequest {
  subject: string;
  object: string;
  action: string;
  operation: "add" | "remove";
}

// Cùng lý do như `PolicyBatchRequest`: backend là
// `TemplateApplicationRequest.run_validation` (schemas/permissions.py:137).
export interface TemplateApplicationRequest {
  template_id: string;
  role: string;
  run_validation?: boolean;
}

// Response types
export interface RolesListResponse {
  roles: RoleInfo[];
}

export interface TemplatesListResponse {
  templates: TemplateInfo[];
}
