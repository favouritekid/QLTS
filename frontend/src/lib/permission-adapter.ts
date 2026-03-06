/**
 * ARCHITECTURE STANDARD: Permission Adapter (Backward Compatibility)
 * 
 * This module provides a TEMPORARY bridge for when backend doesn't return permissions.
 * It infers permissions from status for backward compatibility.
 * 
 * ⚠️ WARNING: This is a TEMPORARY solution.
 * Once backend fully implements permission fields, this should be removed.
 * 
 * @see ADR-FE-001 Migration Strategy
 */

import { FEATURE_FLAGS } from './feature-flags'
import type { PermissionFlags, PermissionAwareResource } from './permissions'

/**
 * Resource with both permissions and status (for inference).
 */
export interface StatusAwareResource extends PermissionAwareResource {
  status?: string
}

/**
 * Adapt permissions for resources that may not have backend-provided permissions.
 * 
 * Priority:
 * 1. If backend provides permissions → use them
 * 2. If STRICT_PERMISSIONS flag is on → return empty (no fallback)
 * 3. Otherwise → infer from status (temporary)
 * 
 * @param resource - Resource with optional permissions and status
 * @returns Permission flags (from backend or inferred)
 */
export function adaptPermissions<T extends StatusAwareResource>(
  resource: T | null | undefined
): PermissionFlags {
  if (!resource) return {}
  
  // If backend provides permissions, use them directly
  if (resource.permissions && Object.keys(resource.permissions).length > 0) {
    return resource.permissions
  }
  
  // If strict mode, don't infer (require backend permissions)
  if (FEATURE_FLAGS.STRICT_PERMISSIONS) {
    return {}
  }
  
  // Fallback: infer from status (TEMPORARY)
  return inferPermissionsFromStatus(resource.status)
}

/**
 * Infer permissions from status.
 * 
 * ⚠️ This is a TEMPORARY solution for migration.
 * Backend should eventually return actual permissions.
 */
function inferPermissionsFromStatus(status?: string): PermissionFlags {
  if (!status) return {}
  
  // Admission-specific inference
  switch (status) {
    case 'draft':
      return {
        edit: true,
        save: true,
        submit: true,
        delete: true,
        approve: false,
        reject: false,
        enroll: false,
      }
    
    case 'rejected':
      return {
        edit: true,
        save: true,
        submit: false,
        resubmit: true, // Officer can resubmit rejected profiles
        delete: true,
        approve: false,
        reject: false,
        enroll: false,
      }
    
    case 'submitted':
    case 'resubmitted':
      return {
        edit: false,
        save: false,
        submit: false,
        delete: false,
        approve: false, // Only managers can approve, but we can't infer role
        reject: false,
        enroll: false,
      }
    
    case 'approved':
      return {
        edit: false,
        save: false,
        submit: false,
        delete: false,
        approve: false,
        reject: false,
        enroll: true,
      }
    
    case 'enrolled':
      return {
        edit: false,
        save: false,
        submit: false,
        delete: false,
        approve: false,
        reject: false,
        enroll: false,
      }
    
    default:
      return {}
  }
}

/**
 * Check if we're using inferred permissions (for debugging/logging).
 */
export function isUsingInferredPermissions<T extends StatusAwareResource>(
  resource: T | null | undefined
): boolean {
  if (!resource) return false
  const hasBackendPermissions = resource.permissions && Object.keys(resource.permissions).length > 0
  return !hasBackendPermissions && !FEATURE_FLAGS.STRICT_PERMISSIONS
}
