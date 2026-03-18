// src/app/(dashboard)/settings/security/page.tsx
/**
 * Unified Security Settings Page
 *
 * Combines:
 * - Suspicious login alerts (anomaly detection)
 * - Active session management (revoke)
 * - Login history audit trail
 *
 * SSR: Pre-fetches active sessions on the server.
 * Login history is fetched client-side (changes frequently).
 */

import { Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { serverApi } from "@/lib/api/server";
import { SecurityClient } from "./_components/SecurityClient";

function SecurityLoading() {
  return (
    <div className="max-w-4xl space-y-8">
      {/* Sessions skeleton */}
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
      {/* Login history skeleton */}
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}

async function fetchInitialSessions() {
  try {
    return await serverApi.sessions.getActiveSessions();
  } catch {
    return undefined;
  }
}

async function SecurityPageContent() {
  const initialSessionsData = await fetchInitialSessions();
  return <SecurityClient initialSessionsData={initialSessionsData} />;
}

export default function SecurityPage() {
  return (
    <Suspense fallback={<SecurityLoading />}>
      <SecurityPageContent />
    </Suspense>
  );
}
