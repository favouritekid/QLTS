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
 */

import { Suspense } from 'react';
import { serverApi } from '@/lib/api/server';
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
 */
async function DashboardPageContent() {
  // ✅ Fetch current user on server
  const initialUser = await serverApi.users.getCurrentUser();

  // ✅ Conditionally fetch statistics for admin/manager
  const isAdmin = initialUser?.role === "admin" || initialUser?.role === "manager";
  const initialStats = isAdmin ? await serverApi.admin.users.getStatistics() : undefined;

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
