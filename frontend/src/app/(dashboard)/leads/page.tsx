// src/app/(dashboard)/leads/page.tsx
/**
 * ✅ PHASE 1 - WEEK 1: Server Component for Leads Page
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Faster initial page load (HTML rendered on server)
 * - SEO: Search engines can index lead data
 * - Performance: No client-side fetch waterfall
 * - Progressive Rendering: With Suspense boundaries
 *
 * Architecture:
 * - This Server Component fetches initial data
 * - Passes data to LeadsClient (Client Component)
 * - LeadsClient handles interactivity (filters, mutations, dialogs)
 * - React Query uses initialData for instant render
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { serverApi } from '@/lib/api/server';
import { LeadsClient } from './_components/LeadsClient';

/**
 * Loading component for Suspense boundary
 */
function LeadsLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48 sm:w-64" />
        <Skeleton className="h-4 w-64 sm:w-96" />
      </div>
      {/* Stats cards - 2 cols on mobile, 4 cols on desktop */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-20 sm:h-24 rounded-lg" />
        ))}
      </div>
      {/* Main content - single column on mobile, 3 cols on lg */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Skeleton className="h-48 lg:h-full rounded-lg lg:col-span-2" />
        <Skeleton className="h-48 lg:h-full rounded-lg hidden lg:block" />
      </div>
    </div>
  );
}

/**
 * V12: Parse searchParams into LeadListParams for SSR fetch.
 * This ensures deep-links from dashboard render correct initial data.
 */
function parseSearchParamsToApiParams(
  searchParams: Record<string, string | string[] | undefined>
) {
  const get = (key: string): string | undefined => {
    const v = searchParams[key];
    return typeof v === "string" ? v : Array.isArray(v) ? v[0] : undefined;
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const params: Record<string, any> = {
    page: parseInt(get("page") || "1", 10),
    page_size: 50,
    sort_by: get("sort_by") || "created_at",
    order: get("order") || "desc",
  };

  // Filter params
  if (get("status")) params.status = get("status");
  if (get("officer")) params.assigned_officer_id = get("officer");
  if (get("unit_id")) params.unit_id = parseInt(get("unit_id")!, 10);
  if (get("offering")) params.offering_id = get("offering");
  if (get("source")) params.source = get("source");
  if (get("q")) params.search = get("q");
  if (get("stage")) params.pipeline_stage_id = get("stage");
  // Convert date strings to VN timezone-aware ISO datetimes,
  // matching client-side useLeadsFilter which uses local Date().
  // SSR runs in UTC container; explicit +07:00 ensures parity.
  if (get("from")) params.date_from = `${get("from")}T00:00:00+07:00`;
  if (get("to")) params.date_to = `${get("to")}T23:59:59.999+07:00`;
  if (get("date_field")) params.date_field = get("date_field");
  if (get("score_min")) params.score_min = parseInt(get("score_min")!, 10);
  if (get("score_max")) params.score_max = parseInt(get("score_max")!, 10);
  if (get("validity")) params.validity_status = get("validity");

  // V12: Dashboard scope context
  if (get("nav_source")) params.nav_source = get("nav_source");
  if (get("scope")) params.scope = get("scope") === "team" ? "unit" : get("scope");
  if (get("scope_officer_id")) params.scope_officer_id = parseInt(get("scope_officer_id")!, 10);
  if (get("scope_unit_id")) params.scope_unit_id = parseInt(get("scope_unit_id")!, 10);
  if (get("include_descendants") === "1" || get("include_descendants") === "true") {
    params.include_descendants = true;
  }
  if (get("loss_reason")) params.loss_reason = get("loss_reason");

  // V12: Dashboard drill-down consultation status filters
  if (get("is_final") === "true") params.is_final = true;
  else if (get("is_final") === "false") params.is_final = false;
  if (get("counts_for_funnel") === "true") params.counts_for_funnel = true;
  else if (get("counts_for_funnel") === "false") params.counts_for_funnel = false;

  return params;
}

/**
 * Server Component - Fetches initial data
 * V12: Reads searchParams so deep-links render correct SSR data.
 */
async function LeadsPageContent({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedParams = await searchParams;
  const apiParams = parseSearchParamsToApiParams(resolvedParams);

  const initialData = await serverApi.leads.getLeads(apiParams);

  return <LeadsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 * V12: Receives searchParams from App Router for SSR context.
 */
export default function LeadsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return (
    <Suspense fallback={<LeadsLoading />}>
      <LeadsPageContent searchParams={searchParams} />
    </Suspense>
  );
}
