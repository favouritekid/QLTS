// src/types/navigation.ts
/**
 * Configuration-driven navigation types for AppSidebar
 * Supports RBAC filtering, nested children, and advanced active state logic
 */
import { type LucideIcon } from "lucide-react";

/**
 * Navigation item configuration
 * @property label - Display text for the navigation item
 * @property href - Route path
 * @property icon - Lucide icon component
 * @property roles - Array of roles allowed to see this item (empty array = all roles)
 * @property matchPath - Optional custom paths that should activate this item
 * @property excludePaths - Optional paths to exclude from parent active state
 * @property children - Nested navigation items
 * @property badge - Optional badge value (string or number)
 */
export interface NavItem {
  label: string;
  href: string;
  icon?: LucideIcon;
  roles?: string[]; // Empty array or undefined = accessible to all roles
  matchPath?: string[]; // Additional paths that should activate this item
  excludePaths?: string[]; // Paths to exclude from parent active state checking
  children?: NavItem[];
  badge?: string | number;
}

/**
 * Navigation group configuration
 * @property title - Group title displayed in sidebar
 * @property items - Array of navigation items in this group
 */
export interface NavGroup {
  title: string;
  items: NavItem[];
}

/**
 * Complete navigation configuration structure
 */
export interface NavigationConfig {
  groups: NavGroup[];
}
