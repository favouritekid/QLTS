// src/app/(dashboard)/admissions/[id]/page.tsx
/**
 * ✅ Admission Detail Server Component
 *
 * REFACTOR: Follows Lead Detail page pattern (SSR + Suspense + Client Hydration)
 *
 * Benefits:
 * - SSR: Admission data rendered on server
 * - Faster initial load
 * - Proper Suspense boundaries for Next.js 16 caching
 */

import { Suspense } from 'react';
import { notFound } from 'next/navigation';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { AdmissionDetailClient } from './_components/AdmissionDetailClient';

// Placeholder param for Next.js 16 cacheComponents build validation
// Real params are handled at runtime
export function generateStaticParams() {
  return [{ id: '__placeholder__' }];
}

/**
 * Loading component (inline skeleton)
 */
function AdmissionDetailLoading() {
  return (
    <div className="px-4 md:px-6 py-4 md:py-6 space-y-4 md:space-y-6">
      {/* Header Skeleton */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:justify-between gap-3">
            <div className="space-y-2">
              <Skeleton className="h-6 w-40 sm:w-48" />
              <Skeleton className="h-4 w-28 sm:w-32" />
            </div>
            <Skeleton className="h-8 w-20 sm:w-24" />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        </CardContent>
      </Card>

      {/* Content Skeleton */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial admission data
 */
async function AdmissionDetailPageContent({ profileId }: { profileId: number }) {
  // ✅ Fetch admission profile on server
  const initialData = await serverApi.admissions.getProfile(profileId);

  // Phase 4 Fix: Add key prop to force form remount when ID changes
  // This ensures clean form state between different profiles
  // @see ADMISSION_ARCHITECTURE_VIOLATION_REPORT.md Violation #12
  return <AdmissionDetailClient key={profileId} profileId={profileId} initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 *
 * Next.js 16: params is now a Promise that must be awaited
 */
export default async function AdmissionProfilePage({
  params
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params;
  
  // Handle placeholder used for build validation
  if (id === '__placeholder__') {
    notFound();
  }
  
  const profileId = Number(id);

  return (
    <Suspense fallback={<AdmissionDetailLoading />}>
      <AdmissionDetailPageContent profileId={profileId} />
    </Suspense>
  );
}
