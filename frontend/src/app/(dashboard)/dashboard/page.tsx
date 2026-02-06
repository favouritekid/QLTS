// src/app/(dashboard)/dashboard/page.tsx
/**
 * ✅ PHASE 1 - WEEK 3 - DAY 2: Dashboard Server Component
 *
 * REFACTOR: Client Component → Hybrid Server Component
 *
 * Benefits:
 * - SSR: User data and statistics rendered on server
 * - Faster initial load with authenticated user context
 * - Maintains interactive features (logout button)
 * - Better UX with immediate data display
 *
 * ✅ FIX: Officers are redirected to /dashboard/officer
 * This dashboard is for Admin/Manager only (system administration)
 */

import { Suspense } from 'react';
import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';
import { serverApi } from '@/lib/api/server';
import { getCachedUserStatistics } from '@/lib/api/cached-data';
import { DashboardClient } from './_components/DashboardClient';

/**
 * Loading component
 */
function DashboardLoading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="space-y-4 text-center">
        <div className="border-primary mx-auto h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" />
        <p className="text-muted-foreground text-sm">Đang tải bảng điều khiển...</p>
      </div>
    </div>
  );
}

/**
 * Server Component - Fetches initial user and statistics data
 *
 * ✅ Statistics now use `use cache` for faster subsequent loads
 * ✅ FIX: Redirects non-admin users to Officer Dashboard
 */
async function DashboardPageContent() {
  // ✅ Fetch current user on server (user-specific, not cached)
  const initialUser = await serverApi.users.getCurrentUser();

  // ✅ FIX: Redirect officers to their specialized dashboard
  // This admin dashboard is only for admin/manager roles
  const isAdminOrManager = initialUser?.role === "admin" || initialUser?.role === "manager";
  if (!isAdminOrManager) {
    redirect('/dashboard/officer');
  }

  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  // ✅ Fetch statistics for admin/manager (CACHED)
  const initialStats = await getCachedUserStatistics(cookieHeader);

  return (
    <DashboardClient
      initialUser={initialUser}
      initialStats={initialStats}
    />
  );
}


/**
 * Page Component (Server Component)
 */
export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardLoading />}>
      <DashboardPageContent />
    </Suspense>
  );
}
