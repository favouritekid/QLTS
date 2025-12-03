'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertTriangle } from 'lucide-react'

/**
 * Dashboard Error Boundary
 *
 * Catches errors specifically in the dashboard route group.
 * Provides a more contextual error UI for dashboard failures.
 *
 * Common causes:
 * - API connection failures
 * - Data loading errors
 * - Permission issues
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Dashboard error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6">
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <div className="flex items-center gap-4">
            <AlertTriangle className="h-10 w-10 text-destructive" />
            <CardTitle>Dashboard Error</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">
            Failed to load dashboard data. This might be a temporary issue.
          </p>

          <div className="bg-muted p-3 rounded-md">
            <code className="text-sm">{error.message}</code>
          </div>

          <div className="flex gap-3">
            <Button onClick={() => reset()}>
              Retry
            </Button>
            <Button variant="outline" onClick={() => window.location.reload()}>
              Refresh Page
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
