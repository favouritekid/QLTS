// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import { MobileBottomNav } from "./dashboard/MobileBottomNav";
import { SecurityBanner, useShouldShowSecurityBanner, SECURITY_BANNER_HEIGHT } from "./SecurityBanner";
import { Suspense, useEffect } from "react";
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

  // Calculate total top offset: header + banner if visible
  // Uses CSS variable --header-height (56px) for consistency
  const headerHeight = 56; // var(--header-height)
  const totalTopOffset = headerHeight + (showSecurityBanner ? SECURITY_BANNER_HEIGHT : 0);

  return (
    <>
      {/* Command Palette - Global keyboard shortcut (Cmd/Ctrl+K) */}
      <CommandPalette />

      <div className="bg-muted/40 relative flex min-h-screen w-full overflow-hidden">
        {/* Sidebar */}
        <Suspense fallback={<SidebarSkeleton />}>
          <AppSidebar />
        </Suspense>

        {/* Mobile Overlay */}
        {!isSidebarCollapsed && (
          <div
            className="fixed inset-0 z-40 bg-black/50 lg:hidden"
            onClick={() => setSidebarCollapsed(true)}
            aria-hidden="true"
          />
        )}

        {/* Main wrapper - chứa cả Header và Content */}
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
    </>
  );
}

