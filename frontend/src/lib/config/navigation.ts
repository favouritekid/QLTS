// src/lib/config/navigation.ts
/**
 * Centralized Navigation Configuration
 * Single source of truth for all sidebar navigation items
 * Supports role-based access control and nested navigation
 *
 * Updated: Added Notifications group, Automation & Rules group
 * Restructured for better UX following industry best practices
 */
import {
  Activity,
  Bell,
  Building2,
  Cog,
  Database,
  FileText,
  FolderTree,
  LayoutDashboard,
  Percent,
  Settings,
  Share2,
  ShieldCheck,
  TrendingUp,
  Trello,
  Users,
  Workflow,
} from "lucide-react";
import type { NavigationConfig } from "@/types/navigation";

/**
 * Main navigation configuration
 * Groups are displayed in order, items are filtered by user role
 *
 * Navigation structure follows best practices:
 * 1. Overview - Dashboards and high-level views
 * 2. Lead Operations - Daily operational tasks
 * 3. Notifications - All notification-related features (NEW)
 * 4. Organization - Structure and programs
 * 5. User Management - People and access control
 * 6. Automation & Rules - Workflows and configurations (NEW)
 * 7. System - System-level settings and monitoring
 *
 * ENHANCED BADGE SUPPORT (Phase 3):
 * Badges can be simple values or enhanced configurations:
 *
 * Simple badge (backward compatible):
 *   badge: 5
 *   badge: "New"
 *
 * Enhanced badge (NEW):
 *   badge: {
 *     type: "count",         // count | dot | pulse | text
 *     value: 5,              // number or string
 *     variant: "danger",     // default | primary | success | warning | danger | info
 *     tooltip: "5 pending"   // optional tooltip
 *   }
 *
 * Examples:
 *   // Simple count
 *   badge: 10
 *
 *   // Status dot
 *   badge: { type: "dot", variant: "success" }
 *
 *   // Pulsing alert
 *   badge: { type: "pulse", variant: "danger", tooltip: "Requires attention" }
 *
 *   // Custom text
 *   badge: { type: "text", value: "Beta", variant: "info" }
 */
export const navigationConfig: NavigationConfig = {
  groups: [
    // =========================================================================
    // 1. OVERVIEW - High-level dashboards
    // =========================================================================
    {
      title: "Overview",
      items: [
        {
          label: "Dashboard",
          href: "/dashboard",
          icon: LayoutDashboard,
          roles: [], // Accessible to all roles EXCEPT officers
          excludeRoles: ["officer"], // Officers have their own dashboard
        },
        {
          label: "Officer Dashboard",
          href: "/dashboard/officer",
          icon: TrendingUp,
          roles: ["officer"], // Only officers can see this
        },
      ],
    },

    // =========================================================================
    // 2. LEAD OPERATIONS - Daily operational tasks
    // =========================================================================
    {
      title: "Lead Operations",
      items: [
        {
          label: "Lead List",
          href: "/leads",
          icon: Database,
          roles: [], // Accessible to all roles
          excludePaths: ["/leads/pipeline"], // Don't highlight when on pipeline
        },
        {
          label: "Pipeline Board",
          href: "/leads/pipeline",
          icon: Trello,
          roles: [], // Accessible to all roles
        },
      ],
    },

    // =========================================================================
    // 3. NOTIFICATIONS - All notification features (NEW)
    // =========================================================================
    {
      title: "Notifications",
      items: [
        {
          label: "Inbox",
          href: "/notifications",
          icon: Bell,
          roles: [], // Accessible to all roles
          // Badge count will be added dynamically by component
        },
        {
          label: "Notification Rules",
          href: "/admin/notification-rules",
          icon: Workflow,
          roles: ["admin", "manager"], // Admin configuration
        },
        {
          label: "Templates",
          href: "/admin/notification-templates",
          icon: FileText,
          roles: ["admin", "manager"], // Admin configuration
        },
      ],
    },

    // =========================================================================
    // 4. ORGANIZATION - Structure and programs
    // =========================================================================
    {
      title: "Organization",
      items: [
        {
          label: "Units & Programs",
          href: "/admin/organization",
          icon: Building2,
          roles: ["admin", "manager"],
          excludePaths: ["/admin/organization-tree"],
        },
        {
          label: "Organization Tree",
          href: "/admin/organization-tree",
          icon: FolderTree,
          roles: ["admin", "manager"],
        },
        {
          label: "Tuition & Discounts",
          href: "/admin/tuition-discount",
          icon: Percent,
          roles: ["admin", "manager"],
        },
      ],
    },

    // =========================================================================
    // 5. USER MANAGEMENT - People and access control
    // =========================================================================
    {
      title: "User Management",
      items: [
        {
          label: "Users",
          href: "/admin/users",
          icon: Users,
          roles: ["admin", "manager"],
        },
        {
          label: "Policies & Permissions",
          href: "/admin/policies",
          icon: ShieldCheck,
          roles: ["admin", "manager"],
        },
      ],
    },

    // =========================================================================
    // 6. AUTOMATION & RULES - Workflows and configurations (NEW)
    // =========================================================================
    {
      title: "Automation & Rules",
      items: [
        {
          label: "Pipeline Stages",
          href: "/admin/pipeline",
          icon: Workflow,
          roles: ["admin", "manager"],
        },
        {
          label: "Distribution Rules",
          href: "/admin/distribution",
          icon: Share2,
          roles: ["admin", "manager"],
        },
      ],
    },

    // =========================================================================
    // 7. SYSTEM - System-level settings and monitoring
    // =========================================================================
    {
      title: "System",
      items: [
        {
          label: "System Config",
          href: "/admin/config",
          icon: Cog,
          roles: ["admin"], // Only admin can access system configuration
        },
        {
          label: "Monitoring",
          href: "/admin/monitoring",
          icon: Activity,
          roles: ["admin"], // Only admin can access monitoring
        },
        {
          label: "Settings",
          href: "/settings",
          icon: Settings,
          roles: [], // Accessible to all roles
        },
      ],
    },
  ],
};
