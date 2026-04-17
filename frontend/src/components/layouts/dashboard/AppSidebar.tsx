// src/components/layouts/dashboard/AppSidebar.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { BookMarked } from "lucide-react";
import { NavUser } from "./NavUser";
import { NavGroup } from "./NavGroup";
import { RecentPages } from "./RecentPages";
import type { NavigationLink } from "@/types/layout.types";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useNotifications } from "@/hooks/useNotifications";
import { useAppNavigation } from "@/hooks/useAppNavigation";
import { useFinanceDashboard } from "@/hooks/finance/useFinanceDashboard";

const AppTitle = ({ isCollapsed }: { isCollapsed: boolean }) => (
  <TooltipProvider delayDuration={0}>
    <div className="flex h-16 items-center gap-2 border-b px-3">
      {isCollapsed ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" asChild className="flex-shrink-0" aria-label="QLTS - Trang chủ">
              <Link href="/dashboard">
                <BookMarked className="h-6 w-6" />
              </Link>
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
          <Button variant="ghost" size="icon" asChild className="flex-shrink-0" aria-label="QLTS - Trang chủ">
            <Link href="/dashboard">
              <BookMarked className="h-6 w-6" />
            </Link>
          </Button>
          <h1
            className={cn(
              "text-lg font-bold font-display transition-opacity duration-300",
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
  const { navigation } = useAppNavigation();

  // Fetch unread notification count for badge
  const { data: notificationsData } = useNotifications({
    page: 1,
    page_size: 1, // We only need the count, not the notifications
    unread_only: true,
  });

  // Fetch finance dashboard stats for pending payments badge
  // Only fetch if finance navigation group is visible (role-based)
  const hasFinanceAccess = navigation.some((group) => group.title === "Finance");
  const { data: financeStats } = useFinanceDashboard({ enabled: hasFinanceAccess });

  const unreadCount = notificationsData?.unread_count || 0;
  const pendingPaymentsCount = financeStats?.pending_payments_count || 0;

  // Add dynamic badges to navigation
  // - Notifications group: unread count on "Inbox"
  // - Finance group: pending payments count on "Pending Payments"
  const navigationWithBadges = navigation.map((group) => {
    if (group.title === "Notifications") {
      return {
        ...group,
        items: group.items.map((item) => {
          if (item.href === "/notifications") {
            return {
              ...item,
              badge: unreadCount > 0 ? unreadCount : undefined,
            } as NavigationLink;
          }
          return item as NavigationLink;
        }),
      };
    }

    if (group.title === "Finance") {
      return {
        ...group,
        items: group.items.map((item) => {
          if (item.href === "/finance/payments") {
            return {
              ...item,
              badge: pendingPaymentsCount > 0 ? pendingPaymentsCount : undefined,
            } as NavigationLink;
          }
          return item as NavigationLink;
        }),
      };
    }

    return {
      ...group,
      items: group.items as NavigationLink[],
    };
  });

  return (
    <aside
      className={cn(
        // Base styles
        "bg-background fixed inset-y-0 left-0 z-50 flex h-full flex-col border-r",
        // Smooth transition
        "transition-[width,transform] duration-300 ease-in-out",
        // Width based on collapsed state - uses CSS vars
        isSidebarCollapsed ? "w-[var(--sidebar-width-collapsed)]" : "w-[var(--sidebar-width)]",
        // Mobile: Slide in/out from left
        "lg:translate-x-0",
        isSidebarCollapsed ? "-translate-x-full lg:translate-x-0" : "translate-x-0"
      )}
    >
      {/* App Title with Tooltip */}
      <AppTitle isCollapsed={isSidebarCollapsed} />

      {/* Navigation - Config-driven */}
      <nav className="scrollbar-thin flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {navigationWithBadges.map((group, index) => (
          <div key={group.title}>
            {/* Add divider between groups (except before first group) */}
            {index > 0 && <div className="bg-border my-4 h-px w-full" />}
            <NavGroup
              links={group.items}
              isCollapsed={isSidebarCollapsed}
              title={group.title}
            />
          </div>
        ))}

        {/* Recent Pages - below main navigation */}
        <div className="mt-4">
          <RecentPages isCollapsed={isSidebarCollapsed} />
        </div>
      </nav>

      {/* User Section */}
      <div className="mt-auto border-t p-3">
        <NavUser isCollapsed={isSidebarCollapsed} />
      </div>
    </aside>
  );
}
