"use client"

/**
 * Admission Actions Component
 * 
 * Action buttons for Save, Submit, and Enroll based on profile status.
 */

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Loader2, Save, Send, GraduationCap } from "lucide-react"

interface AdmissionActionsProps {
  isDraft: boolean
  isApproved: boolean
  isSaving: boolean
  isSubmitting: boolean
  isEnrolling: boolean
  onSave: () => void
  onSubmit: () => void
  onEnroll: () => void
}

export function AdmissionActions({
  isDraft,
  isApproved,
  isSaving,
  isSubmitting,
  isEnrolling,
  onSave,
  onSubmit,
  onEnroll,
}: AdmissionActionsProps) {
  return (
    <Card>
      <CardContent className="pt-6">
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
            <Button disabled variant="secondary">
              Không có hành động
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
