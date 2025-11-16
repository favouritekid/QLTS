// src/lib/config/navigation.ts
/**
 * Centralized Navigation Configuration
 * Single source of truth for all sidebar navigation items
 * Supports role-based access control and nested navigation
 */
import {
  Bell,
  Building2,
  Database,
  LayoutDashboard,
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
 */
export const navigationConfig: NavigationConfig = {
  groups: [
    {
      title: "Overview",
      items: [
        {
          label: "Dashboard",
          href: "/dashboard",
          icon: LayoutDashboard,
          roles: [], // Accessible to all roles
        },
        {
          label: "Officer Dashboard",
          href: "/dashboard/officer",
          icon: TrendingUp,
          roles: ["officer"], // Only officers can see this
        },
        {
          label: "Lead Management",
          href: "/leads",
          icon: Database,
          roles: [], // Accessible to all roles
          // excludePaths prevents /leads from being active when on /leads/pipeline
          excludePaths: ["/leads/pipeline"],
          children: [
            {
              label: "Lead List",
              href: "/leads",
              icon: Database,
              roles: [],
            },
            {
              label: "Pipeline Board",
              href: "/leads/pipeline",
              icon: Trello,
              roles: [],
            },
            {
              label: "Pipeline Settings",
              href: "/admin/pipeline",
              icon: Workflow,
              roles: ["admin", "manager"], // Only admin and manager can see this
            },
            {
              label: "Distribution Config",
              href: "/admin/distribution",
              icon: Share2,
              roles: ["admin", "manager"], // Only admin and manager can see this
            },
          ],
        },
      ],
    },
    {
      title: "Management",
      items: [
        {
          label: "Users",
          href: "/admin/users",
          icon: Users,
          roles: ["admin", "manager"],
        },
        {
          label: "Organization",
          href: "/admin/organization",
          icon: Building2,
          roles: ["admin", "manager"],
        },
        {
          label: "Policy Management",
          href: "/admin/policies",
          icon: ShieldCheck,
          roles: ["admin", "manager"],
        },
      ],
    },
    {
      title: "System",
      items: [
        {
          label: "Settings",
          href: "/settings",
          icon: Settings,
          roles: [], // Accessible to all roles
        },
        {
          label: "Notifications",
          href: "/notifications",
          icon: Bell,
          roles: [], // Accessible to all roles
          // Badge will be added dynamically by the component
        },
      ],
    },
  ],
};
