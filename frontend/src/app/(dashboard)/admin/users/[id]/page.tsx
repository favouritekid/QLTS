// src/app/(dashboard)/admin/users/[id]/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 5: User Detail Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: User detail data rendered on server
 * - Faster initial load
 * - Better for admin dashboard performance
 */

import { Suspense } from 'react';
import { notFound } from 'next/navigation';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent } from '@/components/ui/card';
import { serverApi } from '@/lib/api/server';
import { UserDetailClient } from './_components/UserDetailClient';

// Placeholder param for Next.js 16 cacheComponents build validation
// Real params are handled at runtime
export function generateStaticParams() {
  return [{ id: '__placeholder__' }];
}

/**
 * Loading component
 */
function UserDetailLoading() {
  return (
    <div className="container mx-auto py-6 space-y-6">
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-6 md:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <Skeleton className="h-32 w-full" />
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
 * Server Component - Fetches initial user data
 */
async function UserDetailPageContent({ userId }: { userId: number }) {
  // ✅ Fetch user detail on server
  const initialData = await serverApi.admin.users.getUser(userId);

  return <UserDetailClient userId={userId} initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 *
 * Next.js 16: params is now a Promise that must be awaited
 */
export default async function UserDetailPage({
  params
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params;
  
  // Handle placeholder used for build validation
  if (id === '__placeholder__') {
    notFound();
  }
  
  const userId = Number(id);

  return (
    <Suspense fallback={<UserDetailLoading />}>
      <UserDetailPageContent userId={userId} />
    </Suspense>
  );
}
