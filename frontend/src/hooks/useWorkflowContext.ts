/**
 * useWorkflowContext Hook
 * 
 * React Query hook for Phase-Based Workflow context.
 * Used to get allowed statuses for a lead based on current phase.
 */

import { useQuery } from '@tanstack/react-query'
import { leadsApi } from '@/lib/api/leads'
import type { WorkflowContext } from '@/types/lead.types'

/**
 * Query key for workflow context
 */
export const workflowContextKeys = {
  all: ['workflow-context'] as const,
  byLead: (leadId: number) => ['workflow-context', leadId] as const,
}

/**
 * Hook to get workflow context for a lead
 * 
 * @param leadId - Lead ID to get workflow context for
 * @param options - Query options
 * @returns Query result with workflow context data
 * 
 * @example
 * ```tsx
 * const { data: context, isLoading } = useWorkflowContext(lead.id)
 * 
 * // Filter status dropdown
 * const allowedStatusIds = context?.allowed_statuses.map(s => s.id) ?? []
 * 
 * // Check if status change is allowed
 * if (context?.is_terminal_phase) {
 *   // Disable status dropdown
 * }
 * ```
 */
export function useWorkflowContext(
  leadId: number | undefined | null,
  options?: {
    enabled?: boolean
  }
) {
  return useQuery<WorkflowContext>({
    queryKey: workflowContextKeys.byLead(leadId ?? 0),
    queryFn: () => leadsApi.getWorkflowContext(leadId!),
    enabled: !!leadId && options?.enabled !== false,
    staleTime: 5 * 60 * 1000, // 5 minutes - workflow context doesn't change often
    refetchOnWindowFocus: false,
  })
}

/**
 * Utility to check if a status is allowed in current workflow
 */
export function isStatusAllowed(
  context: WorkflowContext | undefined,
  statusId: string
): boolean {
  if (!context) return true // No context = allow all (graceful fallback)
  return context.allowed_statuses.some(s => s.id === statusId)
}

/**
 * Get allowed status IDs as a Set for fast lookup
 */
export function getAllowedStatusIds(
  context: WorkflowContext | undefined
): Set<string> {
  if (!context) return new Set()
  return new Set(context.allowed_statuses.map(s => s.id))
}

export default useWorkflowContext
