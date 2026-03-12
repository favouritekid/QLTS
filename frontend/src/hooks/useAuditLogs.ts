// src/hooks/useAuditLogs.ts
/**
 * React Query hooks for Audit Logs
 */

import { useQuery } from "@tanstack/react-query";
import {
  listAuditLogs,
  getEntityAuditHistory,
  getAuditLogSummary,
  type AuditLogFilters,
} from "@/lib/api/audit-logs";

// ============================================================================
// QUERY KEYS
// ============================================================================

export const auditLogKeys = {
  all: ["audit-logs"] as const,
  lists: () => [...auditLogKeys.all, "list"] as const,
  list: (filters: AuditLogFilters) =>
    [...auditLogKeys.lists(), filters] as const,
  entity: (entityType: string, entityId: number, opts?: { page?: number; page_size?: number }) =>
    [...auditLogKeys.all, "entity", entityType, entityId, opts] as const,
  summary: (options?: { from_date?: string; to_date?: string }) =>
    [...auditLogKeys.all, "summary", options] as const,
};

// ============================================================================
// HOOKS
// ============================================================================

/**
 * Hook to list audit logs with filters.
 */
export function useAuditLogs(filters: AuditLogFilters = {}) {
  return useQuery({
    queryKey: auditLogKeys.list(filters),
    queryFn: () => listAuditLogs(filters),
    staleTime: 30 * 1000, // 30 seconds
  });
}

/**
 * Hook to get audit history for a specific entity.
 */
export function useEntityAuditHistory(
  entityType: string,
  entityId: number,
  options: { page?: number; page_size?: number; enabled?: boolean } = {}
) {
  const { enabled = true, ...queryOptions } = options;

  return useQuery({
    queryKey: auditLogKeys.entity(entityType, entityId, queryOptions),
    queryFn: () => getEntityAuditHistory(entityType, entityId, queryOptions),
    enabled: enabled && !!entityType && !!entityId,
    staleTime: 30 * 1000, // 30 seconds
  });
}

/**
 * Hook to get audit log summary statistics.
 */
export function useAuditLogSummary(
  options: { from_date?: string; to_date?: string } = {}
) {
  return useQuery({
    queryKey: auditLogKeys.summary(options),
    queryFn: () => getAuditLogSummary(options),
    staleTime: 60 * 1000, // 1 minute
  });
}
