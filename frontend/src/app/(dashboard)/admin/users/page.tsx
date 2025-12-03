// src/app/(dashboard)/admin/users/page.tsx
/**
 * ✅ PHASE 1 - WEEK 2 - DAY 1: Admin Users Server Component
 *
 * REFACTOR: Client Component → Server Component
 *
 * Benefits:
 * - SSR: Initial users list rendered on server
 * - Better performance: No client-side fetch waterfall
 * - SEO-friendly (if needed for admin pages)
 *
 * Architecture:
 * - Server Component fetches initial users list
 * - Pass initialData to AdminUsersClient
 * - Client component handles complex interactions:
 *   - TanStack Table (sorting, filtering, pagination)
 *   - Bulk actions
 *   - Dialogs (create, edit, manage roles, set password)
 *   - CSV export
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { serverApi } from '@/lib/api/server';
import { AdminUsersClient } from './_components/AdminUsersClient';
import { Card, CardContent } from '@/components/ui/card';

/**
 * Loading component for Suspense boundary
 */
function AdminUsersLoading() {
  return (
    <div className="space-y-6">
      <header>
        <Skeleton className="h-9 w-64 mb-2" />
        <Skeleton className="h-5 w-96" />
      </header>
      <Card>
        <CardContent className="p-6 space-y-4">
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
async function AdminUsersPageContent() {
  // ✅ Fetch initial users on server (SSR)
  // Default: First page, no filters, sorted by ID
  const initialData = await serverApi.admin.users.getUsers({
    page: 1,
    page_size: 10,
    sort_by: 'id',
    order: 'asc',
  });

  // ✅ Pass data to Client Component
  return <AdminUsersClient initialData={initialData} />;
}

/**
 * Page Component (Server Component)
 */
export default function AdminUsersPage() {
  return (
    <Suspense fallback={<AdminUsersLoading />}>
      <AdminUsersPageContent />
    </Suspense>
  );
}
