// src/app/(dashboard)/admin/notification-templates/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 2: Notification Templates Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Templates list rendered on server
 * - Faster initial load
 * - Better SEO
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { TemplateList } from '@/components/admin/notifications/TemplateList';

/**
 * Loading component
 */
function TemplatesLoading() {
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
async function TemplatesPageContent() {
  // ✅ Fetch initial templates on server
  const initialData = await serverApi.admin.notifications.getTemplates({
    page: 1,
    page_size: 50,
  });

  return <TemplateList initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function NotificationTemplatesPage() {
  return (
    <Suspense fallback={<TemplatesLoading />}>
      <TemplatesPageContent />
    </Suspense>
  );
}
