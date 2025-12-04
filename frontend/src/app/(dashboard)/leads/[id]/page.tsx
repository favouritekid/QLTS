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
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { LeadDetailClient } from './_components/LeadDetailClient';

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
 * Server Component - Fetches initial lead data
 */
async function LeadDetailPageContent({ leadId }: { leadId: number }) {
  // ✅ Fetch lead detail on server
  // Note: Timeline and Insights will be fetched client-side when tabs are accessed
  const initialData = await serverApi.leads.getLead(leadId);

  return <LeadDetailClient leadId={leadId} initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 *
 * Next.js automatically provides params for dynamic routes
 */
export default function LeadDetailPage({ params }: { params: { id: string } }) {
  const leadId = Number(params.id);

  return (
    <Suspense fallback={<LeadDetailLoading />}>
      <LeadDetailPageContent leadId={leadId} />
    </Suspense>
  );
}
