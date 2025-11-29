// src/hooks/useBreadcrumbs.ts
/**
 * Custom hook for generating breadcrumb navigation
 * Automatically creates breadcrumbs from current pathname
 * Labels are resolved from navigation config
 */
import { useMemo } from "react";
import { navigationConfig } from "@/lib/config/navigation";
import type { NavItem } from "@/types/navigation";

/**
 * Breadcrumb item type
 */
export interface BreadcrumbItem {
  label: string;
  href: string;
}

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
 * Capitalizes first letter of each word
 * @param str - String to capitalize
 * @returns Capitalized string
 */
function capitalize(str: string): string {
  return str
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
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
  };

  if (specialCases[segment]) {
    return specialCases[segment];
  }

  // Convert kebab-case to Title Case
  return capitalize(segment.replace(/-/g, " "));
}

/**
 * Custom hook that generates breadcrumbs from current pathname
 * @param pathname - Current URL pathname
 * @param maxItems - Maximum number of breadcrumb items to show (default: unlimited)
 * @returns Array of breadcrumb items
 *
 * @example
 * const breadcrumbs = useBreadcrumbs('/admin/notification-rules');
 * // Returns: [
 * //   { label: 'Dashboard', href: '/dashboard' },
 * //   { label: 'Admin', href: '/admin' },
 * //   { label: 'Notification Rules', href: '/admin/notification-rules' }
 * // ]
 */
export function useBreadcrumbs(pathname: string, maxItems?: number): BreadcrumbItem[] {
  return useMemo(() => {
    // Skip breadcrumbs for root paths
    if (!pathname || pathname === "/" || pathname === "/dashboard") {
      return [];
    }

    const segments = pathname.split("/").filter(Boolean);
    const breadcrumbs: BreadcrumbItem[] = [];

    // Always start with Dashboard (unless we're already on dashboard)
    if (pathname !== "/dashboard") {
      breadcrumbs.push({
        label: "Dashboard",
        href: "/dashboard",
      });
    }

    // Build breadcrumbs from path segments
    let currentPath = "";
    for (let i = 0; i < segments.length; i++) {
      const segment = segments[i];
      currentPath += `/${segment}`;

      // Try to find label from navigation config first
      let label = findLabelInNavigation(currentPath);

      // If not found in config, convert segment to readable label
      if (!label) {
        label = segmentToLabel(segment);
      }

      breadcrumbs.push({
        label,
        href: currentPath,
      });
    }

    // Limit breadcrumbs if maxItems is specified
    if (maxItems && breadcrumbs.length > maxItems) {
      // Keep first and last items, add ellipsis in between
      return [
        breadcrumbs[0],
        { label: "...", href: "#" },
        ...breadcrumbs.slice(-(maxItems - 2)),
      ];
    }

    return breadcrumbs;
  }, [pathname, maxItems]);
}
