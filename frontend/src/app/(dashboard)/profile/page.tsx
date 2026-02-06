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
import { PageContainer } from '@/components/layouts/PageContainer';
import { serverApi } from '@/lib/api/server';
import { ProfileClient } from './_components/ProfileClient';

/**
 * Loading component - matches ProfileClient structure
 */
function ProfileLoading() {
  return (
    <PageContainer maxWidth="md">
      {/* Header skeleton */}
      <div className="space-y-2">
        <Skeleton className="h-8 md:h-9 w-32 sm:w-48 rounded-md" />
        <Skeleton className="h-5 w-56 sm:w-72 rounded-md" />
      </div>
      {/* Form card skeleton */}
      <Card>
        <CardHeader className="space-y-2">
          <Skeleton className="h-7 w-32 rounded-md" />
          <Skeleton className="h-4 w-full sm:w-96 rounded-md" />
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
            <Skeleton className="h-20 w-20 sm:h-24 sm:w-24 rounded-full" />
            <div className="space-y-2 text-center sm:text-left">
              <Skeleton className="h-4 w-32 rounded-md mx-auto sm:mx-0" />
              <Skeleton className="h-3 w-48 sm:w-64 rounded-md" />
            </div>
          </div>
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="mt-4 h-10 w-32 rounded-md" />
        </CardContent>
      </Card>
    </PageContainer>
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
