import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { AdmissionOverviewClient } from "./_components/AdmissionOverviewClient";

function Loading() {
  return (
    <div className="space-y-4 p-4 sm:p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

export default function AdmissionOverviewPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AdmissionOverviewClient />
    </Suspense>
  );
}
