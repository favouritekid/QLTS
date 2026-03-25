// src/app/(dashboard)/admin/notification-deliveries/page.tsx
/**
 * Phase B8: Notification Delivery Ops — admin page (server component)
 */
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import DeliveryOpsTable from "@/components/admin/notifications/DeliveryOpsTable";

function DeliveriesLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-5 w-64" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

export default function NotificationDeliveriesPage() {
  return (
    <Suspense fallback={<DeliveriesLoading />}>
      <DeliveryOpsTable />
    </Suspense>
  );
}
