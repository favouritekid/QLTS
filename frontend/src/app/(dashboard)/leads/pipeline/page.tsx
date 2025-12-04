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
import { serverApi } from '@/lib/api/server';
import { PipelineClient } from './_components/PipelineClient';

/**
 * Loading component
 */
function PipelineLoading() {
  return (
    <div className="container mx-auto py-6 space-y-6">
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-[600px]" />
    </div>
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
