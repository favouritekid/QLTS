// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import { MobileBottomNav } from "./dashboard/MobileBottomNav";
import { SecurityBanner, useShouldShowSecurityBanner, SECURITY_BANNER_HEIGHT } from "./SecurityBanner";
import { Suspense, useCallback, useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import dynamic from "next/dynamic";

const CommandPalette = dynamic(
  () => import("@/components/common/CommandPalette").then(m => ({ default: m.CommandPalette })),
  { ssr: false }
);

function SidebarSkeleton() {
  return (
    <div className="hidden lg:flex fixed inset-y-0 left-0 z-50 w-[var(--sidebar-width-collapsed)] flex-col border-r bg-background">
      <div className="flex h-14 items-center justify-center">
        <div className="h-8 w-8 animate-pulse rounded-md bg-primary/10" />
      </div>
      <div className="flex-1 space-y-2 p-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-10 w-full animate-pulse rounded-md bg-primary/10" />
        ))}
      </div>
    </div>
  );
}

function HeaderSkeleton() {
  return (
    <div className="fixed top-0 right-0 left-0 z-40 flex h-14 items-center justify-between border-b bg-background px-4 lg:left-[var(--sidebar-width-collapsed)]">
      <div className="h-8 w-8 animate-pulse rounded-md bg-primary/10" />
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 animate-pulse rounded-full bg-primary/10" />
        <div className="h-8 w-8 animate-pulse rounded-full bg-primary/10" />
      </div>
    </div>
  );
}

function MobileBottomNavSkeleton() {
  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 flex h-16 items-center justify-around border-t bg-background lg:hidden">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="h-8 w-8 animate-pulse rounded-md bg-primary/10" />
      ))}
    </div>
  );
}

export function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { isSidebarCollapsed, setSidebarCollapsed } = useUIStore();
  const pathname = usePathname();
  const showSecurityBanner = useShouldShowSecurityBanner();

  // ✅ SECURITY FIX: Removed client-side auth guard
  // Authentication is now enforced by server-side middleware
  // This prevents the security vulnerability where HTML/data was sent
  // to the client before redirect

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024) {
        setSidebarCollapsed(true);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [setSidebarCollapsed]);

  // Mobile sidebar: focus management
  const sidebarRef = useRef<HTMLDivElement>(null);
  const mainWrapperRef = useRef<HTMLDivElement>(null);
  const isMobileSidebarOpen = !isSidebarCollapsed;

  const closeSidebar = useCallback(() => setSidebarCollapsed(true), [setSidebarCollapsed]);

  // Auto-close mobile sidebar when the route changes (link click navigates away)
  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setSidebarCollapsed(true);
    }
  }, [pathname, setSidebarCollapsed]);

  // Move focus into sidebar when it opens on mobile, close on Escape
  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;

    if (isMobileSidebarOpen) {
      // Focus the sidebar so keyboard users land inside it
      sidebarRef.current?.focus();

      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape") closeSidebar();
      };
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [isMobileSidebarOpen, closeSidebar]);

  // Mark all non-sidebar content inert while mobile sidebar is open
  // so Tab cannot escape into background (skip link, header, main,
  // command palette, MobileBottomNav).
  useEffect(() => {
    const el = mainWrapperRef.current;
    if (!el || typeof window === "undefined" || window.innerWidth >= 1024) return;

    if (isMobileSidebarOpen) {
      el.setAttribute("inert", "");
    } else {
      el.removeAttribute("inert");
    }
    return () => el.removeAttribute("inert");
  }, [isMobileSidebarOpen]);

  // Calculate total top offset: header + banner if visible
  // Uses CSS variable --header-height (56px) for consistency
  const headerHeight = 56; // var(--header-height)
  const totalTopOffset = headerHeight + (showSecurityBanner ? SECURITY_BANNER_HEIGHT : 0);

  return (
    <>
      {/* Sidebar — outside inert shell so it stays focusable when open */}
      <div ref={sidebarRef} tabIndex={-1} className="outline-none">
        <Suspense fallback={<SidebarSkeleton />}>
          <AppSidebar />
        </Suspense>
      </div>

      {/* Mobile overlay — outside inert shell so hit-testing keeps the
          onClick handler reachable. (When placed inside mainWrapperRef,
          inert disables pointer events for the whole subtree, which
          made tap-to-dismiss silently fail on mobile.) */}
      {!isSidebarCollapsed && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={closeSidebar}
          aria-hidden="true"
        />
      )}

      {/* Non-sidebar shell — entire subtree gets inert when mobile
          sidebar is open so keyboard focus cannot escape the drawer. */}
      <div ref={mainWrapperRef}>
        {/* Skip to main content — visible only on focus (keyboard users) */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow-md focus:ring-2 focus:ring-ring"
        >
          Chuyển đến nội dung chính
        </a>

        {/* Command Palette - Global keyboard shortcut (Cmd/Ctrl+K) */}
        <CommandPalette />

        <div className="bg-muted/40 relative flex min-h-screen w-full overflow-hidden">
          {/* Main content area */}
          <div
            className={cn(
              "flex flex-1 flex-col transition-[margin-left] duration-300 ease-in-out",
              // Uses CSS vars: --sidebar-width-collapsed (72px), --sidebar-width (256px)
              "lg:ml-[var(--sidebar-width-collapsed)]",
              !isSidebarCollapsed && "lg:ml-[var(--sidebar-width)]"
            )}
          >
            {/* Security Banner - Shows when password change required */}
            <SecurityBanner />

            {/* Header */}
            <Suspense fallback={<HeaderSkeleton />}>
              <Header />
            </Suspense>

            {/* Main Content - Dynamic padding top based on header + banner */}
            {/* Added pb-20 on mobile for MobileBottomNav (64px height + safe area) */}
            <div
              className="flex-1 transition-[margin-top] duration-300 ease-in-out pb-20 lg:pb-0"
              style={{ marginTop: `${totalTopOffset}px` }}
            >
              <Main>{children}</Main>
            </div>
          </div>
        </div>

        {/* Mobile Bottom Navigation - Only visible on mobile (< lg) */}
        <Suspense fallback={<MobileBottomNavSkeleton />}>
          <MobileBottomNav />
        </Suspense>
      </div>
    </>
  );
}

