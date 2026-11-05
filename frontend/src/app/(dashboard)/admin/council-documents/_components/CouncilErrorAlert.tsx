"use client"

import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { describeCouncilDocumentError } from "@/lib/api/council-documents"

/**
 * Lỗi của một thao tác văn bản Hội đồng — câu chính + (lỗi miền) câu nguyên văn
 * của máy chủ, giữ xuống dòng. Không in gì ra console.
 */
export function CouncilErrorAlert({
  error,
  testId,
}: {
  error: unknown
  testId?: string
}) {
  if (!error) return null
  const loi = describeCouncilDocumentError(error)
  return (
    <Alert variant="destructive" data-testid={testId ?? "council-error"} role="alert">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>{loi.title}</AlertTitle>
      {loi.detail ? (
        <AlertDescription className="whitespace-pre-line" data-testid="council-error-detail">
          {loi.detail}
        </AlertDescription>
      ) : null}
    </Alert>
  )
}
