'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { AlertTriangle, RefreshCw } from 'lucide-react'

/**
 * Leads Section Error Boundary
 *
 * Handles errors specific to lead management:
 * - Failed to fetch leads list
 * - Permission errors
 * - Network timeouts
 */
const getFriendlyErrorMessage = (error: Error) => {
  const msg = error.message.toLowerCase()
  if (msg.includes('fetch failed')) {
    return 'Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng hoặc thử lại sau.'
  }
  if (msg.includes('timeout')) {
    return 'Yêu cầu hết thời gian chờ. Máy chủ có thể đang bận.'
  }
  return error.message || 'Đã xảy ra lỗi không mong muốn khi tải danh sách lead.'
}

export default function LeadsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Leads error:', error)
  }, [error])

  return (
    <div className="container mx-auto p-6 space-y-4">
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Không thể tải dữ liệu</AlertTitle>
        <AlertDescription>
          {getFriendlyErrorMessage(error)}
        </AlertDescription>
      </Alert>

      <Card>
        <CardContent className="pt-6 space-y-4">
          <div className="text-center space-y-2">
            <h3 className="font-semibold">Chi tiết lỗi</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto bg-muted p-2 rounded font-mono">
              {error.message}
            </p>
          </div>

          <div className="flex justify-center gap-3">
            <Button onClick={() => reset()} size="sm">
              <RefreshCw className="h-4 w-4 mr-2" />
              Thử lại
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.location.href = '/dashboard'}
            >
              Về trang chủ
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
