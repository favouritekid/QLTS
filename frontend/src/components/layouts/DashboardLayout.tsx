// src/components/layouts/DashboardLayout.tsx
"use client";

import { useUIStore } from "@/lib/stores/ui.store";
import { useAuthStore } from "@/lib/stores/auth.store";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./dashboard/AppSidebar";
import { Header } from "./dashboard/Header";
import { Main } from "./dashboard/Main";
import React, { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import axios from "axios";

export function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { isSidebarCollapsed, setSidebarCollapsed } = useUIStore();
  const { isAuthenticated, token } = useAuthStore();
  const router = useRouter();

  // Track if component has mounted (client-side only)
  // This ensures Zustand has rehydrated from localStorage before checking auth
  const [isMounted, setIsMounted] = React.useState(false);

  // ✅ SECURITY FIX: Cache heartbeat result for 30 seconds
  const lastHeartbeatCheck = useRef<number>(0);
  const HEARTBEAT_CACHE_MS = 10000; // ✅ FIX: Reduced from 30s to 10s for faster revoke detection

  // Set mounted flag on client-side mount
  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  // ✅ SECURITY FIX: AUTH GUARD with heartbeat check
  useEffect(() => {
    // Only check auth after component has mounted (ensures hydration is complete)
    if (!isMounted) return;

    // STEP 1: Check local auth state
    if (!isAuthenticated || !token) {
      console.warn("[DashboardLayout] User not authenticated, redirecting to login");
      router.push("/login");
      return;
    }

    // STEP 2: Heartbeat check - verify session is still valid on server
    const checkSession = async () => {
      const now = Date.now();

      // Skip if checked within last 30 seconds
      if (now - lastHeartbeatCheck.current < HEARTBEAT_CACHE_MS) {
        console.log("[DashboardLayout] Skipping heartbeat (cached)");
        return;
      }

      try {
        const response = await apiClient.get(API_ENDPOINTS.AUTH.CHECK_STATUS);
        console.log("[DashboardLayout] Session valid:", response.data);
        lastHeartbeatCheck.current = now;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          console.warn("[DashboardLayout] Session revoked on server, logging out");
          useAuthStore.getState().logout();
          router.push("/login");
        } else {
          // Network error or other issue - don't logout
          console.error("[DashboardLayout] Session check failed:", error);
        }
      }
    };

    checkSession();
  }, [isMounted, isAuthenticated, token, router]);

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

  // Show loading state while mounting (waiting for hydration)
  if (!isMounted) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
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
        {/* Header */}
        <Header />

        {/* Main Content - Padding top = chiều cao header (h-14 = 56px) */}
        <div className="mt-14 flex-1">
          <Main>{children}</Main>
        </div>
      </div>
    </div>
  );
}
