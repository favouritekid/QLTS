/**
 * ARCHITECTURE STANDARD: Permission System
 * 
 * This module defines the permission contract between Backend and Frontend.
 * 
 * Rules:
 * - Backend returns `permissions: Record<string, boolean>` in API responses
 * - Frontend NEVER reads `can_*` properties directly
 * - Frontend ALWAYS uses `usePermissions()` hook or `hasPermission()` function
 * 
 * @see FRONTEND_ARCHITECTURE_V3.md Section 2.2
 */

/**
 * Permission flags object returned by backend.
 * Keys are action names, values indicate if action is allowed.
 * 
 * @example
 * { edit: true, submit: true, approve: false }
 */
export type PermissionFlags = Record<string, boolean>

/**
 * Interface for API resources that include permissions.
 * All workflow-based resources MUST implement this interface.
 */
export interface PermissionAwareResource {
  permissions?: PermissionFlags
}

/**
 * Extract permissions from any API resource.
 * Provides type-safe access with fallback to empty object.
 * 
 * @param resource - Any API resource that may have permissions
 * @returns Permission flags object (empty if not present)
 */
export function getPermissions<T extends PermissionAwareResource>(
  resource: T | null | undefined
): PermissionFlags {
  return resource?.permissions ?? {}
}

/**
 * Check if a specific action is permitted.
 * 
 * @param resource - Any API resource that may have permissions
 * @param action - The action to check (e.g., 'edit', 'submit', 'approve')
 * @returns true if action is explicitly allowed, false otherwise
 * 
 * @example
 * if (hasPermission(profile, 'submit')) {
 *   // Show submit button
 * }
 */
export function hasPermission(
  resource: PermissionAwareResource | null | undefined,
  action: string
): boolean {
  return getPermissions(resource)[action] === true
}

/**
 * Check if ANY of the specified actions is permitted.
 * 
 * @param resource - Any API resource that may have permissions
 * @param actions - List of actions to check
 * @returns true if at least one action is allowed
 */
export function hasAnyPermission(
  resource: PermissionAwareResource | null | undefined,
  ...actions: string[]
): boolean {
  const permissions = getPermissions(resource)
  return actions.some(action => permissions[action] === true)
}

/**
 * Check if ALL specified actions are permitted.
 * 
 * @param resource - Any API resource that may have permissions
 * @param actions - List of actions to check
 * @returns true only if all actions are allowed
 */
export function hasAllPermissions(
  resource: PermissionAwareResource | null | undefined,
  ...actions: string[]
): boolean {
  const permissions = getPermissions(resource)
  return actions.every(action => permissions[action] === true)
}
