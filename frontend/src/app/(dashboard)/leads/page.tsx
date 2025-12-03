// src/app/(dashboard)/leads/page.tsx
/**
 * ✅ PHASE 1 - WEEK 1: Server Component for Leads Page
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Faster initial page load (HTML rendered on server)
 * - SEO: Search engines can index lead data
 * - Performance: No client-side fetch waterfall
 * - Progressive Rendering: With Suspense boundaries
 *
 * Architecture:
 * - This Server Component fetches initial data
 * - Passes data to LeadsClient (Client Component)
 * - LeadsClient handles interactivity (filters, mutations, dialogs)
 * - React Query uses initialData for instant render
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { serverApi } from '@/lib/api/server';
import { LeadsClient } from './_components/LeadsClient';

/**
 * Loading component for Suspense boundary
 */
function LeadsLoading() {
  return (
    <div className="h-full flex flex-col p-6 space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
      </div>
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <div className="flex-1 grid grid-cols-3 gap-4">
        <Skeleton className="h-full rounded-lg" />
        <Skeleton className="h-full rounded-lg" />
        <Skeleton className="h-full rounded-lg" />
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 *
 * This runs on the server for every request.
 * Data is fetched and serialized into HTML.
 */
async function LeadsPageContent() {
  // ✅ Fetch initial data on server (SSR)
  // Default: First page, no filters
  const initialData = await serverApi.leads.getLeads({
    page: 1,
    page_size: 50,
  });

  // ✅ Pass data to Client Component
  return <LeadsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 *
 * Next.js 16 automatically treats this as Server Component
 * (no "use client" directive)
 */
export default function LeadsPage() {
  return (
    <Suspense fallback={<LeadsLoading />}>
      <LeadsPageContent />
    </Suspense>
  );
}
