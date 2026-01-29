import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TableSkeleton } from '@/components/ui/skeletons'
import { PageContainer } from '@/components/layouts/PageContainer'

/**
 * Admissions/Applications Loading State
 *
 * Shown while fetching admissions data from the API.
 */
export default function AdmissionsLoading() {
  return (
    <PageContainer maxWidth="xl">
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <Skeleton className="h-8 w-40" />
            <div className="flex gap-2">
              <Skeleton className="h-10 w-full sm:w-28" />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={8} />
        </CardContent>
      </Card>
    </PageContainer>
  )
}
