/**
 * Loading Skeleton for Admission Config Page
 */

import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";

export default function AdmissionConfigLoading() {
  return (
    <div className="flex flex-col lg:flex-row min-h-screen">
      {/* Sidebar Skeleton - Hidden on mobile */}
      <div className="hidden lg:block w-64 border-r bg-muted/10 p-4 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Card className="p-3 space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </Card>
        <Card className="p-3 space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </Card>
      </div>

      {/* Main Content Skeleton */}
      <div className="flex-1 px-4 md:px-8 py-4 md:py-8 space-y-4 md:space-y-6">
        <Skeleton className="h-10 md:h-12 w-64 sm:w-96" />
        <Skeleton className="h-48 md:h-64 w-full" />
        <Skeleton className="h-48 md:h-64 w-full" />
      </div>
    </div>
  );
}
