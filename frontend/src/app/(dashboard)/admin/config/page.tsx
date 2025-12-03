// src/app/(dashboard)/admin/config/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 2: System Config Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Config data rendered on server
 * - Faster initial load (3 parallel fetches)
 * - Better caching
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { ConfigClient } from './_components/ConfigClient';

/**
 * Loading component
 */
function ConfigLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-5 w-96" />
      </div>
      <Skeleton className="h-10 w-full max-w-md" />
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function ConfigPageContent() {
  // ✅ Fetch all config types in parallel on server
  const [degreeLevels, offeringTypes, documentTypes] = await Promise.all([
    serverApi.admin.config.getDegreeLevels({ active_only: false }),
    serverApi.admin.config.getOfferingTypes({ active_only: false }),
    serverApi.admin.config.getDocumentTypes({ active_only: false }),
  ]);

  const initialData = {
    degreeLevels,
    offeringTypes,
    documentTypes,
  };

  return <ConfigClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function SystemConfigPage() {
  return (
    <Suspense fallback={<ConfigLoading />}>
      <ConfigPageContent />
    </Suspense>
  );
}
