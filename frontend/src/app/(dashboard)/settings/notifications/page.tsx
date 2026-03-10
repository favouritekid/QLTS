// src/app/(dashboard)/settings/notifications/page.tsx
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Notification Settings Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Notification preferences rendered on server
 * - Faster initial load with user preferences
 * - Better UX for settings page
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { NotificationSettingsClient } from './_components/NotificationSettingsClient';

/**
 * Loading component
 */
function NotificationSettingsLoading() {
  return (
    <div className="space-y-6">
      <Card className="max-w-4xl">
        <CardHeader>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-64" />
        </CardHeader>
        <CardContent className="p-6 space-y-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="flex items-center justify-between">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-6 w-12" />
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="max-w-4xl">
        <CardContent className="p-6 space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

async function fetchNotificationPreferences() {
  try {
    return await serverApi.notifications.getPreferences();
  } catch {
    return undefined;
  }
}

async function fetchEventGroupPreferences() {
  try {
    return await serverApi.notifications.getEventGroupPreferences();
  } catch {
    return undefined;
  }
}

/**
 * Server Component - Fetches initial notification preferences
 */
async function NotificationSettingsPageContent() {
  const [initialPreferences, initialEventGroups] = await Promise.all([
    fetchNotificationPreferences(),
    fetchEventGroupPreferences(),
  ]);

  return (
    <NotificationSettingsClient
      initialPreferences={initialPreferences}
      initialEventGroups={initialEventGroups}
    />
  );
}

/**
 * Page Component (Server Component)
 */
export default function NotificationSettingsPage() {
  return (
    <Suspense fallback={<NotificationSettingsLoading />}>
      <NotificationSettingsPageContent />
    </Suspense>
  );
}
