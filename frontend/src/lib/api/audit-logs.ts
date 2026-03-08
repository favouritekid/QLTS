// src/lib/api/audit-logs.ts
/**
 * Audit Logs API Client
 *
 * Provides functions to query entity audit logs from the backend.
 */

import { apiClient } from "./client";

// ============================================================================
// TYPES
// ============================================================================

export interface AuditLogActor {
  id: number;
  username: string;
  full_name: string | null;
}

export interface AuditLogEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  actor: AuditLogActor | null;
  field_name: string | null;
  old_value: unknown;
  new_value: unknown;
  changes: Record<string, { old: unknown; new: unknown }> | null;
  reason: string | null;
  source: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface AuditLogFilters {
  entity_type?: string;
  entity_id?: number;
  action?: string;
  actor_id?: number;
  field_name?: string;
  from_date?: string;
  to_date?: string;
  page?: number;
  page_size?: number;
}

export interface AuditLogSummary {
  total: number;
  by_entity_type: Record<string, number>;
  by_action: Record<string, number>;
}

// ============================================================================
// API FUNCTIONS
// ============================================================================

/**
 * List audit logs with optional filters.
 */
export async function listAuditLogs(
  filters: AuditLogFilters = {}
): Promise<AuditLogListResponse> {
  const params = new URLSearchParams();

  if (filters.entity_type) params.append("entity_type", filters.entity_type);
  if (filters.entity_id) params.append("entity_id", String(filters.entity_id));
  if (filters.action) params.append("action", filters.action);
  if (filters.actor_id) params.append("actor_id", String(filters.actor_id));
  if (filters.field_name) params.append("field_name", filters.field_name);
  if (filters.from_date) params.append("from_date", filters.from_date);
  if (filters.to_date) params.append("to_date", filters.to_date);
  if (filters.page) params.append("page", String(filters.page));
  if (filters.page_size) params.append("page_size", String(filters.page_size));

  const queryString = params.toString();
  const url = queryString
    ? `/api/admin/audit-logs?${queryString}`
    : "/api/admin/audit-logs";

  const response = await apiClient.get<AuditLogListResponse>(url);
  return response.data;
}

/**
 * Entity-specific audit log endpoint mapping.
 * Uses IDOR-protected endpoints so officers can view audit logs for their assigned resources.
 */
const ENTITY_AUDIT_ENDPOINTS: Record<string, (id: number) => string> = {
  Lead: (id) => `/api/leads/${id}/audit-logs`,
};

/**
 * Get audit log history for a specific entity.
 * Uses entity-specific endpoints when available (IDOR-protected, accessible by officers).
 * Falls back to admin endpoint for other entity types.
 */
export async function getEntityAuditHistory(
  entityType: string,
  entityId: number,
  options: { page?: number; page_size?: number } = {}
): Promise<AuditLogListResponse> {
  const params = new URLSearchParams();
  if (options.page) params.append("page", String(options.page));
  if (options.page_size) params.append("page_size", String(options.page_size));

  const queryString = params.toString();
  const basePath = ENTITY_AUDIT_ENDPOINTS[entityType]?.(entityId)
    ?? `/api/admin/audit-logs/entity/${entityType}/${entityId}`;
  const url = queryString ? `${basePath}?${queryString}` : basePath;

  const response = await apiClient.get<AuditLogListResponse>(url);
  return response.data;
}

/**
 * Get audit log summary statistics.
 */
export async function getAuditLogSummary(
  options: { from_date?: string; to_date?: string } = {}
): Promise<AuditLogSummary> {
  const params = new URLSearchParams();
  if (options.from_date) params.append("from_date", options.from_date);
  if (options.to_date) params.append("to_date", options.to_date);

  const queryString = params.toString();
  const url = queryString
    ? `/api/admin/audit-logs/summary?${queryString}`
    : "/api/admin/audit-logs/summary";

  const response = await apiClient.get<AuditLogSummary>(url);
  return response.data;
}
