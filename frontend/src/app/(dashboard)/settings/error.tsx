'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertTriangle, Settings } from 'lucide-react'

/**
 * Settings Error Boundary
 *
 * Catches errors in the settings route group.
 * Provides contextual error UI for settings failures.
 */
export default function SettingsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Settings error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6">
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <div className="flex items-center gap-4">
            <div className="relative">
              <Settings className="h-10 w-10 text-muted-foreground" />
              <AlertTriangle className="h-5 w-5 text-destructive absolute -bottom-1 -right-1" />
            </div>
            <CardTitle>Lỗi Cài Đặt</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">
            Không thể tải dữ liệu cài đặt. Vui lòng thử lại.
          </p>

          <div className="bg-muted p-3 rounded-md">
            <code className="text-sm">{error.message}</code>
          </div>

          <div className="flex gap-3">
            <Button onClick={() => reset()}>
              Thử lại
            </Button>
            <Button variant="outline" onClick={() => window.location.reload()}>
              Tải lại trang
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
