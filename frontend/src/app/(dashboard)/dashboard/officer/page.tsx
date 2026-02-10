// src/app/(dashboard)/dashboard/officer/page.tsx
/**
 * Officer Dashboard - Server Component
 *
 * SSR prefetch: Fetches initial dashboard stats on server with default
 * 7-day range, passes to OfficerDashboardClient via initialData.
 */

import { Suspense } from 'react';
import { connection } from 'next/server';
import { subDays, startOfDay, endOfDay } from 'date-fns';
import { Skeleton } from '@/components/ui/skeleton';
import { serverApi } from '@/lib/api/server';
import { OfficerDashboardClient } from './_components/OfficerDashboardClient';

/**
 * Loading component for Suspense boundary
 */
function DashboardLoading() {
  return (
    <div className="container mx-auto px-4 py-4 md:p-6 space-y-4 md:space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <Skeleton className="h-10 w-full sm:w-64" />
        <Skeleton className="h-10 w-full sm:w-80" />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    </div>
  );
}

/**
 * Compute default date range matching DashboardDateProvider "7d" preset
 */
function getDefaultDateRange() {
  const today = new Date();
  const from = subDays(today, 6);
  return {
    start_date: startOfDay(from).toISOString().split("T")[0],
    end_date: endOfDay(today).toISOString().split("T")[0],
  };
}

/**
 * Server Component - Fetches initial dashboard stats
 */
async function DashboardPageContent() {
  // Signal dynamic rendering before using new Date()
  await connection();
  const { start_date, end_date } = getDefaultDateRange();

  // Fetch with default params: 7d range, personal scope
  const initialStats = await serverApi.officer.getDashboardStats({
    start_date,
    end_date,
    scope: "personal",
  }).catch(() => undefined);

  return <OfficerDashboardClient initialStats={initialStats} />;
}

/**
 * Page Component (Server Component)
 */
export default function OfficerDashboardPage() {
  return (
    <Suspense fallback={<DashboardLoading />}>
      <DashboardPageContent />
    </Suspense>
  );
}
