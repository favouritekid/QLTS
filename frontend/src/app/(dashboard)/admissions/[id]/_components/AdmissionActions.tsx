"use client"

/**
 * Admission Actions Component
 * 
 * Action buttons for Save, Submit, and Enroll based on profile status.
 */

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Loader2, Save, Send, GraduationCap, AlertCircle } from "lucide-react"

interface AdmissionActionsProps {
  status: string
  isDraft: boolean
  isApproved: boolean
  isSaving: boolean
  isSubmitting: boolean
  isEnrolling: boolean
  onSave: () => void
  onSubmit: () => void
  onEnroll: () => void
}

const STATUS_INFO: Record<string, { label: string; color: string; description: string }> = {
  draft: {
    label: "Nháp",
    color: "bg-gray-100 text-gray-700",
    description: "Có thể chỉnh sửa và nộp hồ sơ",
  },
  approved: {
    label: "Đã duyệt",
    color: "bg-green-100 text-green-700",
    description: "Hồ sơ đã được phê duyệt, có thể xác nhận nhập học",
  },
  rejected: {
    label: "Từ chối",
    color: "bg-red-100 text-red-700",
    description: "Hồ sơ không đạt yêu cầu",
  },
  enrolled: {
    label: "Đã nhập học",
    color: "bg-blue-100 text-blue-700",
    description: "Học sinh đã hoàn tất nhập học",
  },
}

export function AdmissionActions({
  status,
  isDraft,
  isApproved,
  isSaving,
  isSubmitting,
  isEnrolling,
  onSave,
  onSubmit,
  onEnroll,
}: AdmissionActionsProps) {
  const statusInfo = STATUS_INFO[status] || {
    label: status || "Không xác định",
    color: "bg-gray-100 text-gray-700",
    description: "Trạng thái không xác định",
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Hành động</CardTitle>
          <Badge className={statusInfo.color}>{statusInfo.label}</Badge>
        </div>
        <CardDescription>{statusInfo.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col sm:flex-row gap-3 justify-end">
          {isDraft && (
            <>
              <Button
                variant="outline"
                onClick={onSave}
                disabled={isSaving}
              >
                {isSaving ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                Lưu nháp
              </Button>
              
              <Button
                onClick={onSubmit}
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Send className="h-4 w-4 mr-2" />
                )}
                Nộp hồ sơ
              </Button>
            </>
          )}

          {isApproved && (
            <Button
              onClick={onEnroll}
              disabled={isEnrolling}
              className="bg-green-600 hover:bg-green-700"
            >
              {isEnrolling ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <GraduationCap className="h-4 w-4 mr-2" />
              )}
              Xác nhận nhập học
            </Button>
          )}

          {!isDraft && !isApproved && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm">Không có hành động khả dụng cho trạng thái này</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

