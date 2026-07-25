import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { AdmissionOverviewClient } from "./_components/AdmissionOverviewClient";

function Loading() {
  return (
    <div role="status" aria-live="polite" aria-busy className="space-y-4 p-4 sm:p-6">
      <span className="sr-only">Đang tải trang tổng quan tuyển sinh…</span>
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
