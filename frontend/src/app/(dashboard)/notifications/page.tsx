// src/app/(dashboard)/notifications/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 6: Notifications Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Initial notifications rendered on server
 * - Faster initial load
 * - Better UX for notification center
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { PageContainer } from '@/components/layouts/PageContainer';
import { serverApi } from '@/lib/api/server';
import { NotificationsClient } from './_components/NotificationsClient';

/**
 * Loading component - matches NotificationsClient structure
 */
function NotificationsLoading() {
  return (
    <PageContainer maxWidth="md">
      {/* Header skeleton */}
      <div className="space-y-2">
        <Skeleton className="h-9 w-48 sm:w-64" />
        <Skeleton className="h-5 w-64 sm:w-96" />
      </div>
      {/* Tabs skeleton */}
      <Skeleton className="h-12 w-full max-w-md" />
      {/* Content skeleton */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </CardContent>
      </Card>
    </PageContainer>
  );
}

/**
 * Server Component - Fetches initial notifications
 */
async function NotificationsPageContent() {
  // ✅ Fetch initial notifications on server (all, page 1)
  const initialData = await serverApi.notifications.getNotifications({
    page: 1,
    page_size: 20,
    unread_only: false,
  });

  return <NotificationsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function NotificationsPage() {
  return (
    <Suspense fallback={<NotificationsLoading />}>
      <NotificationsPageContent />
    </Suspense>
  );
}
