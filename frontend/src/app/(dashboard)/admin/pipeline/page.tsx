// src/app/(dashboard)/admin/pipeline/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 1: Admin Pipeline Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Pipeline stages and consultation statuses rendered on server
 * - Faster initial load
 * - Better caching with Suspense
 *
 * Complexity: Low (simple list display with dialogs)
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
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-5 w-96" />
      </div>
      <Skeleton className="h-10 w-full max-w-md" />
      <div className="grid gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function PipelinePageContent() {
  // ✅ Fetch both stages and statuses in parallel on server
  const [stages, statuses] = await Promise.all([
    serverApi.admin.pipeline.getPipelineStages(),
    serverApi.admin.pipeline.getConsultationStatuses(),
  ]);

  const initialData = {
    stages,
    statuses,
  };

  return <PipelineClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function AdminPipelinePage() {
  return (
    <Suspense fallback={<PipelineLoading />}>
      <PipelinePageContent />
    </Suspense>
  );
}
