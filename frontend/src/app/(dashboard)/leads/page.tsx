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
import { parseSearchParamsToApiParams } from './page.helpers';

/**
 * Loading component for Suspense boundary
 */
function LeadsLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48 sm:w-64" />
        <Skeleton className="h-4 w-64 sm:w-96" />
      </div>
      {/* Stats cards - 2 cols on mobile, 4 cols on desktop */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-20 sm:h-24 rounded-lg" />
        ))}
      </div>
      {/* Main content - single column on mobile, 3 cols on lg */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Skeleton className="h-48 lg:h-full rounded-lg lg:col-span-2" />
        <Skeleton className="h-48 lg:h-full rounded-lg hidden lg:block" />
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 * V12: Reads searchParams so deep-links render correct SSR data.
 */
async function LeadsPageContent({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedParams = await searchParams;
  const apiParams = parseSearchParamsToApiParams(resolvedParams);

  const initialData = await serverApi.leads.getLeads(apiParams);

  return <LeadsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 * V12: Receives searchParams from App Router for SSR context.
 */
export default function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return (
    <Suspense fallback={<LeadsLoading />}>
      <LeadsPageContent searchParams={searchParams} />
    </Suspense>
  );
}
