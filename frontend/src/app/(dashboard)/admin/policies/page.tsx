// src/app/(dashboard)/admin/policies/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 4: Policies Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Policy statistics rendered on server
 * - Faster initial load
 * - Better caching
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { PoliciesClient } from './_components/PoliciesClient';

/**
 * Loading component
 */
function PoliciesLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-5 w-96" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-32" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardContent className="p-6">
          <Skeleton className="h-96 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function PoliciesPageContent() {
  // ✅ Fetch policy statistics on server
  const initialData = await serverApi.admin.policies.getStatistics();

  return <PoliciesClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function PolicyManagementPage() {
  return (
    <Suspense fallback={<PoliciesLoading />}>
      <PoliciesPageContent />
    </Suspense>
  );
}
