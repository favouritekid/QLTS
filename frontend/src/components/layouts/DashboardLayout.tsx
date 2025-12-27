// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import { CommandPalette } from "@/components/common/CommandPalette";
import { SecurityBanner } from "./SecurityBanner";
import { useEffect } from "react";

export function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { isSidebarCollapsed, setSidebarCollapsed } = useUIStore();

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
            "lg:ml-[72px]",
            !isSidebarCollapsed && "lg:ml-64"
          )}
        >
          {/* Security Banner - Shows when password change required */}
          <SecurityBanner />

          {/* Header */}
          <Header />

          {/* Main Content - Padding top = chiều cao header (h-14 = 56px) */}
          <div className="mt-14 flex-1">
            <Main>{children}</Main>
          </div>
        </div>
      </div>
    </>
  );
}
