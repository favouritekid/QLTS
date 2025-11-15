/**
 * Navigation Routes Configuration
 * Centralized route definitions with metadata for breadcrumbs and back navigation
 */

export interface RouteConfig {
  path: string;
  label: string;
  parent?: string;
  backTo?: string; // Explicit back navigation override
}

/**
 * Route definitions with hierarchy information
 * Used for breadcrumbs and back button navigation
 */
export const routes: Record<string, RouteConfig> = {
  // Dashboard
  dashboard: {
    path: "/dashboard",
    label: "Dashboard",
  },

  // Leads
  leads: {
    path: "/leads",
    label: "Lead List",
    parent: "dashboard",
  },
  leadDetail: {
    path: "/leads/[id]",
    label: "Lead Details",
    parent: "leads",
    backTo: "/leads",
  },
  leadsPipeline: {
    path: "/leads/pipeline",
    label: "Pipeline Board",
    parent: "dashboard",
  },

  // Admin - Pipeline Management
  adminPipeline: {
    path: "/admin/pipeline",
    label: "Pipeline Settings",
    parent: "dashboard",
  },

  // Admin - Users
  adminUsers: {
    path: "/admin/users",
    label: "User Management",
    parent: "dashboard",
  },

  // Admin - Organization
  adminOrganization: {
    path: "/admin/organization",
    label: "Organization",
    parent: "dashboard",
  },

  // Admin - Policies
  adminPolicies: {
    path: "/admin/policies",
    label: "Policy Management",
    parent: "dashboard",
  },

  // Settings
  settings: {
    path: "/settings",
    label: "Settings",
    parent: "dashboard",
  },

  // Notifications
  notifications: {
    path: "/notifications",
    label: "Notifications",
    parent: "dashboard",
  },
};

/**
 * Get route config by pathname
 * Handles dynamic routes with parameters
 */
export function getRouteConfig(pathname: string): RouteConfig | null {
  // Exact match first
  const exactMatch = Object.values(routes).find((route) => route.path === pathname);
  if (exactMatch) return exactMatch;

  // Match dynamic routes (e.g., /leads/123 matches /leads/[id])
  const dynamicMatch = Object.values(routes).find((route) => {
    if (!route.path.includes("[")) return false;

    const pattern = route.path.replace(/\[([^\]]+)\]/g, "[^/]+");
    const regex = new RegExp(`^${pattern}$`);
    return regex.test(pathname);
  });

  return dynamicMatch || null;
}

/**
 * Get breadcrumb trail for a given pathname
 */
export function getBreadcrumbs(pathname: string): RouteConfig[] {
  const current = getRouteConfig(pathname);
  if (!current) return [];

  const breadcrumbs: RouteConfig[] = [current];

  let parentKey = current.parent;
  while (parentKey) {
    const parent = routes[parentKey];
    if (!parent) break;

    breadcrumbs.unshift(parent);
    parentKey = parent.parent;
  }

  return breadcrumbs;
}

/**
 * Get back navigation path for a given pathname
 */
export function getBackPath(pathname: string): string | null {
  const current = getRouteConfig(pathname);
  if (!current) return null;

  // Use explicit backTo if defined
  if (current.backTo) return current.backTo;

  // Otherwise, use parent route
  if (current.parent) {
    const parent = routes[current.parent];
    return parent?.path || null;
  }

  return null;
}
