// src/app/(dashboard)/admin/notification-deliveries/page.tsx
/**
 * D5: Notification Delivery Ops — tabbed dashboard.
 *
 * Tabs: Overview (charts + health + alerts) | Deliveries (existing table) | Configuration (breakers + quotas)
 */
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import DeliveryDashboard from "./DeliveryDashboard";

function DashboardLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-5 w-64" />
      </div>
      <Skeleton className="h-10 w-96" />
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
    <Suspense fallback={<DashboardLoading />}>
      <DeliveryDashboard />
    </Suspense>
  );
}
