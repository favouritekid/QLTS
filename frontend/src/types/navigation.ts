// src/types/navigation.ts
/**
 * Configuration-driven navigation types for AppSidebar
 * Supports RBAC filtering, nested children, and advanced active state logic
 *
 * ENHANCED: Support for multiple badge types (count, dot, pulse, text)
 */
import { type LucideIcon } from "lucide-react";

/**
 * Badge configuration for navigation items
 */
export interface NavBadge {
  /**
   * Badge type determines the visual style
   * - count: Shows numeric count (e.g., "5")
   * - dot: Shows small dot indicator
   * - pulse: Shows animated pulsing dot
   * - text: Shows custom text label
   */
  type?: "count" | "dot" | "pulse" | "text";
  /**
   * Badge value (number for count, string for text)
   */
  value?: number | string;
  /**
   * Badge variant/color
   */
  variant?: "default" | "primary" | "success" | "warning" | "danger" | "info";
  /**
   * Optional tooltip to show on hover
   */
  tooltip?: string;
}

/**
 * Navigation item configuration
 * @property label - Display text for the navigation item
 * @property href - Route path
 * @property icon - Lucide icon component
 * @property roles - Array of roles allowed to see this item (empty array = all roles)
 * @property matchPath - Optional custom paths that should activate this item
 * @property excludePaths - Optional paths to exclude from parent active state
 * @property children - Nested navigation items
 * @property badge - Optional badge (simple value or enhanced config)
 */
export interface NavItem {
  label: string;
  href: string;
  icon?: LucideIcon;
  roles?: string[]; // Empty array or undefined = accessible to all roles
  matchPath?: string[]; // Additional paths that should activate this item
  excludePaths?: string[]; // Paths to exclude from parent active state checking
  children?: NavItem[];
  badge?: string | number | NavBadge; // Enhanced: Support both simple and complex badges
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
