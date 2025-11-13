// src/app/(dashboard)/admin/organization/page.tsx
import { Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { OrganizationServerWrapper } from "@/components/admin/organization/OrganizationServerWrapper";

/**
 * ⚡ PERFORMANCE: Organization Management Page with Server Components
 *
 * Architecture:
 * 1. Server Component (this page) - Fetches initial data on server
 * 2. OrganizationServerWrapper (Server) - Coordinates server-side data fetch
 * 3. OrganizationClientPage (Client) - Handles interactivity with pre-fetched data
 *
 * Benefits:
 * - Faster FCP (First Contentful Paint) - data ready before hydration
 * - Reduced client-side bundle size - fetch logic stays on server
 * - Better perceived performance - no loading spinner on first render
 * - SEO-friendly (if needed in future)
 *
 * Performance Metrics Expected:
 * - FCP: ~300-500ms faster (depends on network)
 * - TTI: Unchanged (interactivity still client-side)
 * - Bundle size: ~5-10KB smaller (server fetch code removed from client)
 */
export default function OrganizationPage() {
  return (
    <div className="h-[calc(100vh-4rem)]">
      <Suspense
        fallback={
          // Skeleton loading fallback (only shown during streaming)
          <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
            <Skeleton className="w-80 border-r" />
            <div className="flex-1 p-6">
              <Skeleton className="h-16 w-1/3" />
            </div>
          </div>
        }
      >
        {/* ⚡ Server Component wrapper fetches data on server */}
        <OrganizationServerWrapper />
      </Suspense>
    </div>
  );
}
