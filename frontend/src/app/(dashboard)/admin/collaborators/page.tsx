import { Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { PageContainer } from "@/components/layouts/PageContainer";
import { serverApi } from "@/lib/api/server";
import { CollaboratorsClient } from "./_components/CollaboratorsClient";
import { Card, CardContent } from "@/components/ui/card";

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

async function CollaboratorsPageContent() {
  const initialData = await serverApi.admin.collaborators.getCollaborators({
    skip: 0,
    limit: 10,
    sort_by: "created_at",
    order: "desc",
  });

  return <CollaboratorsClient initialData={initialData} />;
}

export default function CollaboratorsPage() {
  return (
    <Suspense fallback={<CollaboratorsLoading />}>
      <CollaboratorsPageContent />
    </Suspense>
  );
}
