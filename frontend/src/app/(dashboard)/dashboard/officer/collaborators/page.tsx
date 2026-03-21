import { Suspense } from "react";
import { redirect } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { PageContainer } from "@/components/layouts/PageContainer";
import { Card, CardContent } from "@/components/ui/card";
import { serverApi } from "@/lib/api/server";
import { OfficerCollaboratorsClient } from "./_components/OfficerCollaboratorsClient";

function CollaboratorsLoading() {
  return (
    <PageContainer maxWidth="xl">
      <div className="space-y-2">
        <Skeleton className="h-8 md:h-9 w-48 sm:w-64" />
        <Skeleton className="h-5 w-64 sm:w-96" />
      </div>
      <Card>
        <CardContent className="p-4 md:p-6 space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </CardContent>
      </Card>
    </PageContainer>
  );
}

async function PageContent() {
  // Role guard: only officers can access this page
  const user = await serverApi.users.getCurrentUser();
  if (user?.role !== "officer") {
    redirect(user?.role === "collaborator" ? "/ctv" : "/dashboard");
  }

  // SSR prefetch: backend auto-applies officer scope (managed_by_officer_id=self)
  const initialData = await serverApi.admin.collaborators.getCollaborators({
    skip: 0,
    limit: 10,
    sort_by: "created_at",
    order: "desc",
  });

  return <OfficerCollaboratorsClient initialData={initialData} />;
}

export default function OfficerCollaboratorsPage() {
  return (
    <Suspense fallback={<CollaboratorsLoading />}>
      <PageContent />
    </Suspense>
  );
}
