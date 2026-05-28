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

import { useMemo, useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { User } from "lucide-react";
import { useNotifications } from "@/hooks/useNotifications";
import { useAppNavigation } from "@/hooks/useAppNavigation";
import { useUIStore } from "@/lib/stores/ui.store";

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
  const requestCloseMobileOverlays = useUIStore((s) => s.requestCloseMobileOverlays);
  const isSidebarCollapsed = useUIStore((s) => s.isSidebarCollapsed);

  // Track whether a dialog/sheet overlay is open, so the bar can hide for it
  // (bottom sheets, side sheets, centered dialogs) — matching Material 3 where
  // an overlay replaces the nav bar.
  //
  // Radix sets `data-scroll-locked` on <body> for ANY modal overlay — but that
  // INCLUDES <Select> (listbox) and <DropdownMenu> (menu), which do NOT occlude
  // the bar and must not hide it (else the bar flickers on every dropdown). So
  // we use the cheap attribute as the trigger but gate it on an actually-open
  // dialog/sheet (role=dialog|alertdialog). react-remove-scroll renders INSIDE
  // the overlay content, so the role node is already mounted when the attribute
  // appears — no ordering race.
  const [isOverlayOpen, setIsOverlayOpen] = useState(false);
  useEffect(() => {
    const sync = () =>
      setIsOverlayOpen(
        document.body.hasAttribute("data-scroll-locked") &&
          document.querySelector(
            '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]'
          ) !== null
      );
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { attributes: true, attributeFilter: ["data-scroll-locked"] });
    return () => observer.disconnect();
  }, []);

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

  // Hide the bar while ANY full-screen overlay owns the screen: the main
  // sidebar drawer (!isSidebarCollapsed) OR any Radix sheet/dialog
  // (isOverlayOpen). The bar sits at z-[60] — above every overlay (z-50) — so
  // keeping it visible paints it OVER the overlay's lowest content (drawer's
  // "Settings" item, a bottom sheet's footer, a sheet's last fields). The open
  // overlay already owns navigation/actions, so the bar is redundant there.
  if (!isSidebarCollapsed || isOverlayOpen) return null;

  return (
    <nav
      className={cn(
        // Base styles
        // z-[60] + pointer-events-auto keep the bar tappable ABOVE an open
        // Radix modal drawer (overlay/content sit at z-50 and set the rest of
        // the page to pointer-events:none). Without this, tapping a tab while
        // a mobile detail drawer is open does nothing — see LeadsClient sheet.
        "fixed bottom-0 left-0 right-0 z-[60] pointer-events-auto",
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
              // Tapping any tab dismisses any open mobile drawer/sheet. This
              // also covers re-tapping the already-active tab (same-route nav
              // does NOT change pathname, so a route-based close never fires).
              onClick={() => requestCloseMobileOverlays()}
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
