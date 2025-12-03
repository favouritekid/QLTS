'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { AlertTriangle, RefreshCw } from 'lucide-react'

/**
 * Admissions Section Error Boundary
 *
 * Handles errors specific to admissions/applications management:
 * - Failed to fetch applications
 * - Permission errors
 * - Data validation errors
 */
export default function AdmissionsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Admissions error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6 space-y-4">
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Failed to Load Admissions</AlertTitle>
        <AlertDescription>
          We couldn't load the admissions data. Please try again.
        </AlertDescription>
      </Alert>

      <Card>
        <CardContent className="pt-6 space-y-4">
          <div className="text-center space-y-2">
            <h3 className="font-semibold">What happened?</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              {error.message || 'An unexpected error occurred while loading admissions.'}
            </p>
          </div>

          <div className="flex justify-center gap-3">
            <Button onClick={() => reset()} size="sm">
              <RefreshCw className="h-4 w-4 mr-2" />
              Try Again
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = '/dashboard'}
            >
              Back to Dashboard
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
