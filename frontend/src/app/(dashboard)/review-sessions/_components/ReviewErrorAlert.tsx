"use client"

import type { ReactNode } from "react"
import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"

/**
 * Lỗi của màn lần xét — câu đã chọn bởi `describeReviewSessionError` (thiết kế §5) hoặc câu riêng của màn; `children` cho phần
 * thêm (vd liên kết "Mở Bảng chỉ tiêu năm …"). Không in gì ra console.
 */
export function ReviewErrorAlert({ message, testId, children }: { message: string; testId: string; children?: ReactNode }) {
  return (
    <Alert variant="destructive" data-testid={testId}>
      <AlertCircle className="h-4 w-4" />
      <AlertDescription className="space-y-2">
        <p className="whitespace-pre-line">{message}</p>
        {children}
      </AlertDescription>
    </Alert>
  )
}
