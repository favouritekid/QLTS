// src/app/(dashboard)/admin/tuition-discount/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 3: Tuition Discount Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Policies rendered on server
 * - Faster initial load
 * - Better caching
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { TuitionDiscountClient } from './_components/TuitionDiscountClient';

/**
 * Loading component
 */
function TuitionDiscountLoading() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-9 w-96" />
          <Skeleton className="h-5 w-64" />
        </div>
        <Skeleton className="h-10 w-40" />
      </div>
      <Card>
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
async function TuitionDiscountPageContent() {
  // ✅ Fetch initial policies on server
  const initialData = await serverApi.admin.tuitionDiscount.getPolicies({
    page: 1,
    page_size: 20,
  });

  return <TuitionDiscountClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function TuitionDiscountPage() {
  return (
    <Suspense fallback={<TuitionDiscountLoading />}>
      <TuitionDiscountPageContent />
    </Suspense>
  );
}
