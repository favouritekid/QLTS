// src/app/(dashboard)/admin/notification-rules/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 2: Notification Rules Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Rules list rendered on server
 * - Faster initial load
 * - Better caching
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { NotificationRuleList } from '@/components/admin/notifications/NotificationRuleList';

/**
 * Loading component
 */
function RulesLoading() {
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
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-6">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-3">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-32 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial data
 */
async function RulesPageContent() {
  // ✅ Fetch initial rules on server
  const initialData = await serverApi.admin.notifications.getRules({
    page: 1,
    page_size: 100, // Fetch all rules for grouping by category
  });

  return <NotificationRuleList initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function NotificationRulesPage() {
  return (
    <Suspense fallback={<RulesLoading />}>
      <RulesPageContent />
    </Suspense>
  );
}
