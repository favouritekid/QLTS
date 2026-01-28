'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle } from 'lucide-react'

/**
 * Root Error Boundary for Next.js App
 *
 * Catches unhandled errors in the entire application.
 * This is a Next.js convention - error.tsx files create error boundaries.
 *
 * Security Note: Never expose sensitive error details to users in production
 *
 * @see https://nextjs.org/docs/app/building-your-application/routing/error-handling
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log error to console in development
    console.error('Application error:', error)

    // ✅ TECHNICAL DEBT FIX: Send to Sentry if configured
    // To enable: Set NEXT_PUBLIC_SENTRY_DSN in your .env file
    // Then install: npm install @sentry/nextjs
    const sentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    if (sentryDsn) {
      // Dynamic import to avoid loading Sentry if not configured
      import('@sentry/nextjs').then((Sentry) => {
        Sentry.captureException(error, {
          tags: {
            errorBoundary: 'global',
            digest: error.digest || 'unknown',
          },
          extra: {
            errorMessage: error.message,
            errorStack: error.stack,
          },
        });
      }).catch(() => {
        // Sentry not installed - this is expected in dev without @sentry/nextjs
        console.warn('Sentry is configured but @sentry/nextjs is not installed');
      });
    }
  }, [error])

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="max-w-md w-full space-y-6 text-center">
        <AlertCircle className="h-16 w-16 text-destructive mx-auto" />

        <div className="space-y-2">
          <h1 className="text-2xl font-bold font-display">Something went wrong!</h1>
          <p className="text-muted-foreground">
            {error.message || 'An unexpected error occurred'}
          </p>
          {error.digest && (
            <p className="text-xs text-muted-foreground">
              Error ID: {error.digest}
            </p>
          )}
        </div>

        <div className="flex gap-4 justify-center">
          <Button
            onClick={() => reset()}
            variant="default"
          >
            Try again
          </Button>
          <Button
            onClick={() => window.location.href = '/dashboard'}
            variant="outline"
          >
            Go to Dashboard
          </Button>
        </div>
      </div>
    </div>
  )
}
