// src/components/layouts/dashboard/AppSidebar.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { Bell, BookMarked, Settings, LayoutDashboard, Database, Users, ShieldCheck, Building2, Workflow, Trello } from "lucide-react";
import { NavUser } from "./NavUser";
import { NavGroup } from "./NavGroup";
import type { NavigationLink } from "@/types/layout.types";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useNotifications } from "@/hooks/useNotifications";
import { useAuth } from "@/hooks/useAuth";

const AppTitle = ({ isCollapsed }: { isCollapsed: boolean }) => (
  <TooltipProvider delayDuration={0}>
    <div className="flex h-16 items-center gap-2 border-b px-3">
      {isCollapsed ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" className="flex-shrink-0">
              <BookMarked className="h-6 w-6" />
            </Button>
          </TooltipTrigger>
          <TooltipContent
            side="right"
            className="bg-popover text-popover-foreground border shadow-md"
          >
            QLTS
          </TooltipContent>
        </Tooltip>
      ) : (
        <>
          <Button variant="ghost" size="icon" className="flex-shrink-0">
            <BookMarked className="h-6 w-6" />
          </Button>
          <h1
            className={cn(
              "text-lg font-bold transition-opacity duration-300",
              isCollapsed ? "w-0 opacity-0" : "opacity-100"
            )}
          >
            QLTS
          </h1>
        </>
      )}
    </div>
  </TooltipProvider>
);

export function AppSidebar() {
  const { isSidebarCollapsed } = useUIStore();
  const { user } = useAuth();

  // Fetch unread notification count for badge
  const { data: notificationsData } = useNotifications({
    page: 1,
    page_size: 1, // We only need the count, not the notifications
    unread_only: true,
  });

  const unreadCount = notificationsData?.unread_count || 0;

  // Check if user is admin or manager
  const isAdmin = user?.role === "admin" || user?.role === "manager";

  // Main navigation links - filtered by role
  const mainNavLinks: NavigationLink[] = [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { label: "Leads", href: "/leads", icon: Database },
    { label: "Pipeline Board", href: "/leads/pipeline", icon: Trello },
    // Only show admin links for admin/manager
    ...(isAdmin
      ? [
          { label: "Users", href: "/admin/users", icon: Users },
          { label: "Organization", href: "/admin/organization", icon: Building2 },
          { label: "Pipeline Settings", href: "/admin/pipeline", icon: Workflow },
          { label: "Policy Management", href: "/admin/policies", icon: ShieldCheck },
        ]
      : []),
  ];

  const settingsLinks: NavigationLink[] = [
    { label: "Settings", href: "/settings", icon: Settings },
    {
      label: "Notifications",
      href: "/notifications",
      icon: Bell,
      badge: unreadCount > 0 ? unreadCount : undefined,
    },
  ];

  return (
    <aside
      className={cn(
        // Base styles
        "bg-background fixed inset-y-0 left-0 z-50 flex h-full flex-col border-r",
        // Smooth transition
        "transition-all duration-300 ease-in-out",
        // Width based on collapsed state
        isSidebarCollapsed ? "w-[72px]" : "w-64",
        // Mobile: Slide in/out from left
        "lg:translate-x-0",
        isSidebarCollapsed ? "-translate-x-full lg:translate-x-0" : "translate-x-0"
      )}
    >
      {/* App Title with Tooltip */}
      <AppTitle isCollapsed={isSidebarCollapsed} />

      {/* Navigation */}
      <nav className="scrollbar-thin flex-1 space-y-1 overflow-y-auto px-3 py-4">
        <NavGroup links={mainNavLinks} isCollapsed={isSidebarCollapsed} title="Overview" />
        <div className="bg-border my-4 h-px w-full" />
        <NavGroup links={settingsLinks} isCollapsed={isSidebarCollapsed} title="Management" />
      </nav>

      {/* User Section */}
      <div className="mt-auto border-t p-3">
        <NavUser isCollapsed={isSidebarCollapsed} />
      </div>
    </aside>
  );
}
