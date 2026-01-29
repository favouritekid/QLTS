// src/app/(dashboard)/leads/pipeline/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 5: Pipeline Board Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Pipeline with leads rendered on server
 * - Faster initial board load
 * - Better for drag-and-drop UX
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { PageContainer } from '@/components/layouts/PageContainer';
import { serverApi } from '@/lib/api/server';
import { PipelineClient } from './_components/PipelineClient';

/**
 * Loading component - matches PipelineClient structure
 */
function PipelineLoading() {
  return (
    <PageContainer>
      {/* Header skeleton */}
      <Skeleton className="h-10 w-48 sm:w-64" />
      {/* Stats grid skeleton */}
      <div className="grid grid-cols-2 gap-3 md:gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      {/* Pipeline board skeleton */}
      <Skeleton className="h-[400px] md:h-[600px]" />
    </PageContainer>
  );
}

/**
 * Server Component - Fetches initial pipeline data
 */
async function PipelinePageContent() {
  // ✅ Fetch full pipeline with leads and stats on server
  const initialData = await serverApi.pipeline.getFullPipeline({
    include_leads: true,
    include_stats: true,
  });

  return <PipelineClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function PipelinePage() {
  return (
    <Suspense fallback={<PipelineLoading />}>
      <PipelinePageContent />
    </Suspense>
  );
}
