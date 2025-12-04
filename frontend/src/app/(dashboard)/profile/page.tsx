// src/app/(dashboard)/profile/page.tsx
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 2: Profile Server Component
 *
 * REFACTOR: Client Component → Hybrid Server Component
 *
 * Benefits:
 * - SSR: User profile data rendered on server
 * - Faster initial load with authenticated user context
 * - Maintains interactive features (edit profile form)
 * - Better UX with immediate profile display
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { ProfileClient } from './_components/ProfileClient';

/**
 * Loading component
 */
function ProfileLoading() {
  return (
    <div className="space-y-6">
      <header>
        <Skeleton className="h-9 w-48 rounded-md" />
        <Skeleton className="mt-2 h-5 w-72 rounded-md" />
      </header>
      <Card className="max-w-2xl">
        <CardHeader className="space-y-2">
          <Skeleton className="h-7 w-32 rounded-md" />
          <Skeleton className="h-4 w-96 rounded-md" />
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center gap-6">
            <Skeleton className="h-24 w-24 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-32 rounded-md" />
              <Skeleton className="h-3 w-64 rounded-md" />
            </div>
          </div>
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="mt-4 h-10 w-32 rounded-md" />
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Server Component - Fetches initial user profile data
 */
async function ProfilePageContent() {
  // ✅ Fetch current user on server
  const initialUser = await serverApi.users.getCurrentUser();

  return <ProfileClient initialUser={initialUser} />;
}

/**
 * Page Component (Server Component)
 */
export default function ProfilePage() {
  return (
    <Suspense fallback={<ProfileLoading />}>
      <ProfilePageContent />
    </Suspense>
  );
}
