// src/lib/config/roles.ts
/**
 * Role Configuration for Middleware Authorization
 *
 * IMPORTANT: This config is for UX optimization only (prevent flash of unauthorized content).
 * Backend Casbin is the SINGLE SOURCE OF TRUTH for authorization.
 *
 * When adding new roles:
 * 1. Update this config for frontend middleware
 * 2. Update Casbin policies in backend
 * 3. Verify both are in sync
 */

/**
 * Roles that have access to admin routes
 *
 * These roles can access routes under /admin/*
 * Backend Casbin will perform the final authorization check.
 */
export const ADMIN_ROLES = ["admin", "manager"] as const;

/**
 * Check if a role has admin access
 *
 * @param role - User role from JWT payload
 * @returns true if role has admin access
 */
export function hasAdminAccess(role: string | undefined): boolean {
  if (!role) return false;
  return ADMIN_ROLES.includes(role as any);
}

/**
 * Role hierarchy (for future use)
 *
 * Defines which roles inherit permissions from others.
 * Currently not used by middleware, but can be useful for future features.
 */
export const ROLE_HIERARCHY = {
  admin: ["manager", "user"],
  manager: ["user"],
  user: [],
} as const;

export type Role = (typeof ADMIN_ROLES)[number] | "user";
