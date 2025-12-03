import { DashboardSkeleton } from '@/components/ui/skeletons'

/**
 * Dashboard Loading State
 *
 * Automatically shown by Next.js while the dashboard page is loading.
 * Provides immediate visual feedback to users.
 */
export default function DashboardLoading() {
  return <DashboardSkeleton />
}
