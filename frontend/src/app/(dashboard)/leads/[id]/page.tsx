// src/app/(dashboard)/leads/[id]/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 5: Lead Detail Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Lead detail data rendered on server
 * - Faster initial load
 * - Better SEO for lead details
 */

import { Suspense } from 'react';
import { notFound, unstable_rethrow } from 'next/navigation';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { LeadDetailClient } from './_components/LeadDetailClient';

// Placeholder param for Next.js 16 cacheComponents build validation
// Real params are handled at runtime
export function generateStaticParams() {
  return [{ id: '__placeholder__' }];
}


/**
 * Loading component
 */
function LeadDetailLoading() {
  return (
    <div className="container mx-auto py-6 space-y-6">
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-6 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <Skeleton className="h-24 w-full" />
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
 * Server Component - Fetches initial lead data + timeline + insights in parallel
 */
async function LeadDetailPageContent({ leadId }: { leadId: number }) {
  // Fetch lead data — 404 triggers notFound(), other errors bubble to error boundary
  let initialData: Awaited<ReturnType<typeof serverApi.leads.getLead>> | undefined;
  try {
    initialData = await serverApi.leads.getLead(leadId);
  } catch (err) {
    // Rethrow framework control-flow FIRST: serverFetch calls redirect('/login')
    // on a 401 (throws NEXT_REDIRECT) and cookies() throws the dynamic-render
    // bailout — neither is a fetch error. Swallowing them renders a broken/empty
    // page instead of redirecting to login (or bailing to a dynamic render).
    unstable_rethrow(err);
    // ✅ T9 FIX: Only notFound() for actual 404s; other errors (500, network) go to error boundary
    // serverFetch throws: "API Error (STATUS): message" — match the exact prefix pattern
    const message = err instanceof Error ? err.message : "";
    if (/^API Error \(404\)/.test(message)) {
      notFound();
    }
    // For non-404 errors, let client component re-fetch and show error state
    // initialData remains undefined — client will retry via React Query
  }

  // ✅ Parallel fetch: timeline and insights (non-critical, catch gracefully)
  const [initialTimeline, initialInsights] = await Promise.all([
    serverApi.leads.getLeadTimeline(leadId).catch((e) => { unstable_rethrow(e); return undefined; }),
    serverApi.leads.getLeadInsights(leadId).catch((e) => { unstable_rethrow(e); return undefined; }),
  ]);

  return (
    <LeadDetailClient
      leadId={leadId}
      initialData={initialData}
      initialTimeline={initialTimeline}
      initialInsights={initialInsights}
    />
  );
}

/**
 * Page Component (Server Component)
 *
 * Next.js 16: params is now a Promise that must be awaited
 */
export default async function LeadDetailPage({
  params
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params;
  
  // Handle placeholder used for build validation
  if (id === '__placeholder__') {
    notFound();
  }
  
  const leadId = Number(id);
  if (!Number.isSafeInteger(leadId) || leadId <= 0) {
    notFound();
  }

  return (
    <Suspense fallback={<LeadDetailLoading />}>
      <LeadDetailPageContent leadId={leadId} />
    </Suspense>
  );
}

