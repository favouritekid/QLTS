/**
 * Permission Utility Functions
 *
 * ⚠️ SECURITY NOTE: These functions check user.role on the client side.
 * This is NOT a security measure - backend API must enforce actual permissions.
 * Client-side checks are ONLY for UX (showing/hiding UI elements).
 *
 * TODO: Migrate to API permission flags when backend supports it.
 * Backend should return { can_reassign: true, can_edit: true, ... } in responses.
 * Then this file becomes a simple pass-through to those flags.
 *
 * Per Thin Client Philosophy (CLAUDE.md):
 * - Frontend should NOT make authorization decisions
 * - Frontend should trust backend permission flags
 * - Role strings can be manipulated by users in DevTools
 */

import type { User } from "@/types/api.types";

// Valid roles from backend (Casbin RBAC)
export const ADMIN_ROLES = ["admin"] as const;
export const MANAGER_ROLES = ["admin", "manager"] as const;
export const OFFICER_ROLES = ["admin", "manager", "officer"] as const;

type AdminRole = typeof ADMIN_ROLES[number];
type ManagerRole = typeof MANAGER_ROLES[number];
type OfficerRole = typeof OFFICER_ROLES[number];

/**
 * Check if user has admin privileges
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 */
export function isAdmin(user: User | null | undefined): boolean {
  if (!user?.role) return false;
  return ADMIN_ROLES.includes(user.role as AdminRole);
}

/**
 * Check if user has manager or higher privileges
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 */
export function isManagerOrAbove(user: User | null | undefined): boolean {
  if (!user?.role) return false;
  return MANAGER_ROLES.includes(user.role as ManagerRole);
}

/**
 * Check if user has officer or higher privileges
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 */
export function isOfficerOrAbove(user: User | null | undefined): boolean {
  if (!user?.role) return false;
  return OFFICER_ROLES.includes(user.role as OfficerRole);
}

/**
 * Check if user can reassign leads
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 *
 * TODO: Replace with lead.can_reassign from API
 */
export function canReassignLead(user: User | null | undefined): boolean {
  return isManagerOrAbove(user);
}

/**
 * Check if user can select officers for lead assignment
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 *
 * TODO: Replace with API flag from backend
 */
export function canSelectOfficer(user: User | null | undefined): boolean {
  return isManagerOrAbove(user);
}

/**
 * Check if user can view all officers filter
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 *
 * TODO: Replace with API flag from backend
 */
export function canFilterByOfficer(user: User | null | undefined): boolean {
  return isManagerOrAbove(user);
}

/**
 * Check if user can export leads
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 *
 * TODO: Replace with API flag from backend
 */
export function canExportLeads(user: User | null | undefined): boolean {
  return isManagerOrAbove(user);
}

/**
 * Check if user can bulk assign leads
 * ⚠️ FOR UX ONLY - Backend enforces actual permissions
 *
 * TODO: Replace with API flag from backend
 */
export function canBulkAssign(user: User | null | undefined): boolean {
  return isManagerOrAbove(user);
}
