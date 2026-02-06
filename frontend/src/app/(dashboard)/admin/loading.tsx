import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TableSkeleton } from '@/components/ui/skeletons'
import { PageContainer } from '@/components/layouts/PageContainer'

/**
 * Admin Panel Loading State
 *
 * Shown while loading admin panel data.
 * Provides loading UI for admin tables and management interfaces.
 */
export default function AdminLoading() {
  return (
    <PageContainer maxWidth="xl">
      {/* Admin Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <Skeleton className="h-10 w-40 sm:w-48" />
        <Skeleton className="h-10 w-full sm:w-32" />
      </div>

      {/* Admin Content */}
      <div className="grid gap-3 md:gap-4 grid-cols-1 sm:grid-cols-2 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-6 w-32" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-20 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Admin Table */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-40" />
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={12} />
        </CardContent>
      </Card>
    </PageContainer>
  )
}
