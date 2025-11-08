// src/app/(dashboard)/admin/layout.tsx
"use client";

import { useEffect } from "react";
import { redirect } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Admin Layout - Client-side Authorization
 *
 * This layout protects all admin routes (/admin/*) by checking user role.
 * Only users with role 'admin' or 'manager' can access admin pages.
 *
 * Security Notes:
 * - This is client-side protection for UX (hide admin UI from regular users)
 * - Backend still enforces authorization via Casbin (defense in depth)
 * - Prevents unauthorized users from seeing admin page structure
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  useEffect(() => {
    // Only redirect after loading is complete and user is confirmed
    if (!isLoading && user) {
      const isAuthorized = user.role === "admin" || user.role === "manager";

      if (!isAuthorized) {
        // Redirect unauthorized users to dashboard
        redirect("/dashboard");
      }
    }
  }, [user, isLoading]);

  // Show loading skeleton while checking authorization
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-9 w-48 rounded-md" />
          <Skeleton className="mt-2 h-5 w-96 rounded-md" />
        </div>
        <div className="space-y-4">
          <Skeleton className="h-32 w-full rounded-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  // Don't render admin content if user is not loaded
  if (!user) {
    redirect("/login");
    return null;
  }

  // Check authorization
  const isAuthorized = user.role === "admin" || user.role === "manager";

  if (!isAuthorized) {
    // This will be handled by useEffect redirect, but we also prevent rendering
    redirect("/dashboard");
    return null;
  }

  // Render admin content for authorized users
  return <>{children}</>;
}
