// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import { MobileBottomNav } from "./dashboard/MobileBottomNav";
import { CommandPalette } from "@/components/common/CommandPalette";
import { SecurityBanner, useShouldShowSecurityBanner, SECURITY_BANNER_HEIGHT } from "./SecurityBanner";
import { useEffect } from "react";

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
        <AppSidebar />

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
            "flex flex-1 flex-col transition-all duration-300 ease-in-out",
            // Uses CSS vars: --sidebar-width-collapsed (72px), --sidebar-width (256px)
            "lg:ml-[var(--sidebar-width-collapsed)]",
            !isSidebarCollapsed && "lg:ml-[var(--sidebar-width)]"
          )}
        >
          {/* Security Banner - Shows when password change required */}
          <SecurityBanner />

          {/* Header */}
          <Header />

          {/* Main Content - Dynamic padding top based on header + banner */}
          {/* Added pb-20 on mobile for MobileBottomNav (64px height + safe area) */}
          <div 
            className="flex-1 transition-all duration-300 ease-in-out pb-20 lg:pb-0"
            style={{ marginTop: `${totalTopOffset}px` }}
          >
            <Main>{children}</Main>
          </div>
        </div>
      </div>

      {/* Mobile Bottom Navigation - Only visible on mobile (< lg) */}
      <MobileBottomNav />
    </>
  );
}

