/**
 * ARCHITECTURE STANDARD: Permission Hook
 * 
 * This hook provides React components with permission checking capabilities.
 * 
 * Usage:
 * ```tsx
 * const { can } = usePermissions(profile)
 * {can('submit') && <SubmitButton />}
 * ```
 * 
 * Rules:
 * - ❌ FORBIDDEN: {profile.can_submit && <Button />}
 * - ✅ REQUIRED: {can('submit') && <Button />}
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.2
 */

import { useMemo } from 'react'
import { 
  getPermissions, 
  hasPermission, 
  hasAnyPermission, 
  hasAllPermissions,
  type PermissionAwareResource,
  type PermissionFlags 
} from '@/lib/permissions'

export interface UsePermissionsResult {
  /**
   * Raw permission flags object
   */
  permissions: PermissionFlags
  
  /**
   * Check if a single action is permitted
   * @example can('edit') → boolean
   */
  can: (action: string) => boolean
  
  /**
   * Check if ANY of the actions is permitted
   * @example canAny('edit', 'delete') → true if either is allowed
   */
  canAny: (...actions: string[]) => boolean
  
  /**
   * Check if ALL actions are permitted
   * @example canAll('edit', 'publish') → true only if both allowed
   */
  canAll: (...actions: string[]) => boolean
}

/**
 * Hook to read permissions from any API resource.
 * 
 * @param resource - API resource with optional `permissions` field
 * @returns Object with permission checking methods
 * 
 * @example
 * function AdmissionActions({ profile }) {
 *   const { can } = usePermissions(profile)
 *   
 *   return (
 *     <>
 *       {can('edit') && <SaveButton />}
 *       {can('submit') && <SubmitButton />}
 *       {can('approve') && <ApproveButton />}
 *     </>
 *   )
 * }
 */
export function usePermissions<T extends PermissionAwareResource>(
  resource: T | null | undefined
): UsePermissionsResult {
  return useMemo(() => ({
    permissions: getPermissions(resource),
    can: (action: string) => hasPermission(resource, action),
    canAny: (...actions: string[]) => hasAnyPermission(resource, ...actions),
    canAll: (...actions: string[]) => hasAllPermissions(resource, ...actions),
  }), [resource])
}
