/**
 * Navigation Routes Configuration
 * Centralized route definitions with metadata for breadcrumbs and back navigation
 *
 * ENHANCED: Now auto-generates breadcrumbs from navigation.ts config
 * Falls back to manual route definitions for backward compatibility
 */

import { navigationConfig } from "@/lib/config/navigation";
import type { NavItem } from "@/types/navigation";

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
 * NEW: Helper functions to search navigation config
 */

/**
 * Recursively searches navigation config for a label matching the given path
 * @param path - The path to find label for
 * @param items - Navigation items to search through
 * @returns The label if found, null otherwise
 */
function findLabelInNavigation(path: string, items?: NavItem[]): string | null {
  if (!items) {
    // Search all groups if no items provided
    for (const group of navigationConfig.groups) {
      const label = findLabelInNavigation(path, group.items);
      if (label) return label;
    }
    return null;
  }

  for (const item of items) {
    // Exact match
    if (item.href === path) {
      return item.label;
    }

    // Search in children
    if (item.children && item.children.length > 0) {
      const childLabel = findLabelInNavigation(path, item.children);
      if (childLabel) return childLabel;
    }
  }

  return null;
}

/**
 * Converts URL segment to readable label
 * @param segment - URL segment (e.g., "notification-rules")
 * @returns Readable label (e.g., "Notification Rules")
 */
function segmentToLabel(segment: string): string {
  // Handle special cases
  const specialCases: Record<string, string> = {
    admin: "Admin",
    dashboard: "Dashboard",
    leads: "Leads",
    notifications: "Notifications",
    settings: "Settings",
    organization: "Organization",
    users: "Users",
    policies: "Policies",
    config: "Config",
    monitoring: "Monitoring",
    pipeline: "Pipeline",
  };

  if (specialCases[segment]) {
    return specialCases[segment];
  }

  // Convert kebab-case to Title Case
  return segment
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// ✅ PERFORMANCE: Pre-compile RegExp patterns for dynamic routes (created once, reused)
interface DynamicRouteMatch {
  route: RouteConfig;
  regex: RegExp;
}

const dynamicRoutePatterns: DynamicRouteMatch[] = Object.values(routes)
  .filter((route) => route.path.includes("["))
  .map((route) => ({
    route,
    regex: new RegExp(`^${route.path.replace(/\[([^\]]+)\]/g, "[^/]+")}$`),
  }));

// ✅ PERFORMANCE: Pre-built Map for O(1) exact route lookups
const exactRouteMap = new Map<string, RouteConfig>(
  Object.values(routes)
    .filter((route) => !route.path.includes("["))
    .map((route) => [route.path, route])
);

/**
 * Get route config by pathname
 * Handles dynamic routes with parameters
 */
export function getRouteConfig(pathname: string): RouteConfig | null {
  // O(1) exact match first via Map
  const exactMatch = exactRouteMap.get(pathname);
  if (exactMatch) return exactMatch;

  // Match dynamic routes using pre-compiled RegExp patterns
  const dynamicMatch = dynamicRoutePatterns.find(({ regex }) => regex.test(pathname));

  return dynamicMatch?.route || null;
}

/**
 * Get breadcrumb trail for a given pathname
 * ENHANCED: Auto-generates breadcrumbs from pathname if not in routes config
 */
export function getBreadcrumbs(pathname: string): RouteConfig[] {
  // Skip breadcrumbs for root paths
  if (!pathname || pathname === "/" || pathname === "/dashboard") {
    return [];
  }

  // Try to get from manual route config first (backward compatibility)
  const current = getRouteConfig(pathname);
  if (current) {
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

  // AUTO-GENERATION: Build breadcrumbs from pathname segments
  const segments = pathname.split("/").filter(Boolean);
  const breadcrumbs: RouteConfig[] = [];

  // Always start with Dashboard (unless we're already on dashboard)
  if (pathname !== "/dashboard") {
    breadcrumbs.push({
      path: "/dashboard",
      label: "Dashboard",
    });
  }

  // Build breadcrumbs from path segments
  // Skip first segment if it's "dashboard" since we already added it above
  let currentPath = "";
  const startIndex = segments[0] === "dashboard" ? 1 : 0;
  
  for (let i = startIndex; i < segments.length; i++) {
    const segment = segments[i];
    currentPath = i === 0 ? `/${segment}` : `${currentPath}/${segment}`;
    
    // For dashboard subpaths, build the full path correctly
    if (segments[0] === "dashboard" && i >= 1) {
      currentPath = `/dashboard/${segments.slice(1, i + 1).join("/")}`;
    }

    // Try to find label from navigation config first
    let label = findLabelInNavigation(currentPath);

    // If not found in config, convert segment to readable label
    if (!label) {
      label = segmentToLabel(segment);
    }

    breadcrumbs.push({
      path: currentPath,
      label,
    });
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
