// src/app/(dashboard)/admissions/page.tsx
/**
 * Admissions List Page - Server Component
 *
 * SSR prefetch: Fetches initial admissions data on server,
 * passes to AdmissionsClient via initialData for instant render.
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { AdmissionsClient } from './_components/AdmissionsClient';

/**
 * Loading component for Suspense boundary
 */
function AdmissionsLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48 sm:w-64" />
        <Skeleton className="h-4 w-64 sm:w-96" />
      </div>
      {/* Toolbar skeleton */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Skeleton className="h-10 flex-1" />
        <Skeleton className="h-10 w-32" />
        <Skeleton className="h-10 w-32" />
      </div>
      {/* Table skeleton */}
      <div className="hidden md:block rounded-md border p-4 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
      {/* Mobile skeleton */}
      <div className="md:hidden grid gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-4 w-full mb-2" />
              <Skeleton className="h-2 w-3/4" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial admissions data
 */
async function AdmissionsPageContent() {
  const initialData = await serverApi.admissions.listProfiles({
    page: 1,
    page_size: 20,
  });

  return <AdmissionsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function AdmissionsPage() {
  return (
    <Suspense fallback={<AdmissionsLoading />}>
      <AdmissionsPageContent />
    </Suspense>
  );
}
