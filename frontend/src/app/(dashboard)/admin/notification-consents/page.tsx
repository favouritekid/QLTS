// src/app/(dashboard)/admin/notification-consents/page.tsx
/**
 * Phase B7: Notification Consent Management — admin page (server component)
 */
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import ConsentManager from "@/components/admin/notifications/ConsentImportDialog";

function ConsentsLoading() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-9 w-80" />
          <Skeleton className="h-5 w-64" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-10 w-32" />
          <Skeleton className="h-10 w-36" />
        </div>
      </div>
      <Card>
        <CardContent className="pt-6">
          <div className="flex gap-4">
            <Skeleton className="h-10 w-36" />
            <Skeleton className="h-10 w-40" />
            <Skeleton className="h-10 w-36" />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-4 pt-6">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function NotificationConsentsPage() {
  return (
    <Suspense fallback={<ConsentsLoading />}>
      <ConsentManager />
    </Suspense>
  );
}
