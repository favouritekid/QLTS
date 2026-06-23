import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { AdmissionsWeeklyClient } from "./_components/AdmissionsWeeklyClient";

function Loading() {
  return (
    <div className="space-y-4 p-4 sm:p-6">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

export default function AdmissionsWeeklyReportPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AdmissionsWeeklyClient />
    </Suspense>
  );
}
