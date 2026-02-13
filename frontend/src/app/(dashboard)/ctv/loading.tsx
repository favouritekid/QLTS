import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { PageContainer } from "@/components/layouts/PageContainer";

export default function CTVLoading() {
  return (
    <PageContainer maxWidth="xl">
      <div className="space-y-2">
        <Skeleton className="h-8 md:h-9 w-48 sm:w-64" />
        <Skeleton className="h-5 w-64 sm:w-96" />
      </div>
      {/* Stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4 space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      {/* Table */}
      <Card>
        <CardContent className="p-4 md:p-6 space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </CardContent>
      </Card>
    </PageContainer>
  );
}
