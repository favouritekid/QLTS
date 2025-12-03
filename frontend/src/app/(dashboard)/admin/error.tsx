'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { ShieldAlert, RefreshCw } from 'lucide-react'

/**
 * Admin Section Error Boundary
 *
 * Handles errors specific to admin operations:
 * - Permission denied errors
 * - Failed admin API calls
 * - Configuration errors
 */
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Admin error:', error)
  }, [error])

  // Check if this is a permission error
  const isPermissionError = error.message?.toLowerCase().includes('permission') ||
                           error.message?.toLowerCase().includes('unauthorized') ||
                           error.message?.toLowerCase().includes('forbidden')

  return (
    <div className="container mx-auto p-6 space-y-4">
      <Alert variant="destructive">
        <ShieldAlert className="h-4 w-4" />
        <AlertTitle>
          {isPermissionError ? 'Access Denied' : 'Admin Panel Error'}
        </AlertTitle>
        <AlertDescription>
          {isPermissionError
            ? 'You do not have permission to access this admin feature.'
            : 'We couldn't load the admin panel. Please try again.'}
        </AlertDescription>
      </Alert>

      <Card>
        <CardContent className="pt-6 space-y-4">
          <div className="text-center space-y-2">
            <h3 className="font-semibold">What happened?</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              {error.message || 'An unexpected error occurred in the admin panel.'}
            </p>
          </div>

          <div className="flex justify-center gap-3">
            {!isPermissionError && (
              <Button onClick={() => reset()} size="sm">
                <RefreshCw className="h-4 w-4 mr-2" />
                Try Again
              </Button>
            )}
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
