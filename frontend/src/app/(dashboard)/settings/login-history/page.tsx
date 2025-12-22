// src/app/(dashboard)/settings/login-history/page.tsx
/**
 * ✅ LOGIN SECURITY: Phase 5 - Login History Page
 *
 * Server Component that renders the login history settings page.
 */

import { Suspense } from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { LoginHistoryClient } from './_components/LoginHistoryClient';

/**
 * Loading component
 */
function LoginHistoryLoading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

/**
 * Page Component (Server Component)
 */
export default function LoginHistoryPage() {
  return (
    <Suspense fallback={<LoginHistoryLoading />}>
      <LoginHistoryClient />
    </Suspense>
  );
}
