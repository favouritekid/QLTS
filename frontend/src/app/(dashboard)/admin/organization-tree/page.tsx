// src/app/(dashboard)/admin/organization-tree/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 4: Organization Tree Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Organization tree rendered on server
 * - Faster initial load with tree data
 * - Better caching of tree structure
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { OrganizationTreeClient } from './_components/OrganizationTreeClient';

/**
 * Loading component
 */
function OrganizationTreeLoading() {
  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-5 w-96" />
      </div>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-48" />
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-6 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function OrganizationTreePageContent() {
  // ✅ Fetch organization tree with aggregation on server (current year, active only)
  const initialData = await serverApi.admin.organization.getTreeWithAggregation();

  return <OrganizationTreeClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function OrganizationTreePage() {
  return (
    <Suspense fallback={<OrganizationTreeLoading />}>
      <OrganizationTreePageContent />
    </Suspense>
  );
}
