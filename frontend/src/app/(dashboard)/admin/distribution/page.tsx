// src/app/(dashboard)/admin/distribution/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 3: Distribution Rules Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Rules table rendered on server
 * - Faster initial load
 * - Better caching
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { DistributionClient } from './_components/DistributionClient';

/**
 * Loading component
 */
function DistributionLoading() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-9 w-80" />
          <Skeleton className="h-5 w-96" />
        </div>
        <Skeleton className="h-10 w-36" />
      </div>
      <Card>
        <CardContent className="space-y-4 p-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function DistributionPageContent() {
  // ✅ Fetch initial distribution rules on server
  const initialData = await serverApi.admin.distributionRules.getRules();

  return <DistributionClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function DistributionPage() {
  return (
    <Suspense fallback={<DistributionLoading />}>
      <DistributionPageContent />
    </Suspense>
  );
}
