// src/app/(dashboard)/settings/sessions/page.tsx
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 1: Sessions Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Active sessions rendered on server
 * - Faster initial load with session data
 * - Better security with server-side session validation
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { serverApi } from '@/lib/api/server';
import { SessionsClient } from './_components/SessionsClient';

/**
 * Loading component
 */
function SessionsLoading() {
  return (
    <div className="container max-w-4xl py-8">
      <div className="space-y-4">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial session data
 */
async function fetchInitialSessions() {
  try {
    return await serverApi.sessions.getActiveSessions();
  } catch {
    return undefined;
  }
}

async function SessionsPageContent() {
  const initialData = await fetchInitialSessions();
  return <SessionsClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function SessionsPage() {
  return (
    <Suspense fallback={<SessionsLoading />}>
      <SessionsPageContent />
    </Suspense>
  );
}
