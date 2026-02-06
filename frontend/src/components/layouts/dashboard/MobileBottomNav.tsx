// src/components/layouts/dashboard/MobileBottomNav.tsx
"use client";

/**
 * Mobile Bottom Navigation
 *
 * Fixed bottom navigation bar for mobile devices.
 * Shows main navigation items with icons and unread badges.
 * Only visible on screens < 1024px (lg breakpoint).
 *
 * Uses useAppNavigation() for role-based filtering (consistent with AppSidebar).
 */

import { useMemo } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { User } from "lucide-react";
import { useNotifications } from "@/hooks/useNotifications";
import { useAppNavigation } from "@/hooks/useAppNavigation";

/**
 * Priority-ordered hrefs to show on mobile bottom nav.
 * First 4 matches from the user's role-filtered navigation are displayed,
 * plus Profile as the 5th item.
 */
const MOBILE_PRIORITY_HREFS = [
  "/dashboard/officer",
  "/dashboard",
  "/leads",
  "/admissions",
  "/finance",
  "/notifications",
];

export function MobileBottomNav() {
  const pathname = usePathname();
  const { navigation } = useAppNavigation();

  // Fetch unread notification count for badge
  const { data: notificationsData } = useNotifications({
    page: 1,
    page_size: 1,
    unread_only: true,
  });

  const unreadCount = notificationsData?.unread_count || 0;

  // Flatten role-filtered navigation items
  const allNavItems = useMemo(() => {
    return navigation.flatMap(group => group.items);
  }, [navigation]);

  // Build mobile nav: pick top 4 from priority list + profile
  const mobileItems = useMemo(() => {
    const items: Array<{
      href: string;
      icon: React.ComponentType<{ className?: string }>;
      label: string;
      badge?: number;
    }> = [];

    for (const href of MOBILE_PRIORITY_HREFS) {
      if (items.length >= 4) break;
      const found = allNavItems.find(item => item.href === href);
      if (found?.icon) {
        items.push({
          href: found.href,
          icon: found.icon,
          label: found.label,
          badge: found.href === "/notifications" && unreadCount > 0 ? unreadCount : undefined,
        });
      }
    }

    // Always add profile as the last (5th) item
    items.push({ href: "/profile", icon: User, label: "Hồ sơ" });

    return items;
  }, [allNavItems, unreadCount]);

  const isActive = (href: string) => {
    if (href === "/dashboard" || href === "/dashboard/officer") {
      return pathname === "/dashboard" || pathname === "/dashboard/officer";
    }
    return pathname.startsWith(href);
  };

  return (
    <nav
      className={cn(
        // Base styles
        "fixed bottom-0 left-0 right-0 z-50",
        "bg-background border-t",
        "safe-area-pb", // For iPhone notch
        // Only show on mobile (hide on lg and up)
        "lg:hidden"
      )}
    >
      <div className="flex items-center justify-around h-16 px-2">
        {mobileItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                // Base styles - 44px touch target
                "flex flex-col items-center justify-center",
                "min-w-[56px] min-h-[44px] px-2 py-1",
                "rounded-lg transition-colors",
                // Active/inactive states
                active
                  ? "text-primary bg-primary/10"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              )}
            >
              <div className="relative">
                <Icon className={cn(
                  "h-5 w-5",
                  active && "text-primary"
                )} />
                {/* Badge for notifications */}
                {item.badge && item.badge > 0 && (
                  <span className={cn(
                    "absolute -top-1 -right-1.5",
                    "min-w-[16px] h-4 px-1",
                    "flex items-center justify-center",
                    "text-[10px] font-medium",
                    "bg-destructive text-destructive-foreground",
                    "rounded-full"
                  )}>
                    {item.badge > 99 ? "99+" : item.badge}
                  </span>
                )}
              </div>
              <span className={cn(
                "text-[10px] mt-1 font-medium",
                active && "text-primary"
              )}>
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
