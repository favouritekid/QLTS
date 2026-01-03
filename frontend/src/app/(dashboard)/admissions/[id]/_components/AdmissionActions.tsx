"use client"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Save, Send, GraduationCap, ClipboardCheck, Lock } from "lucide-react"
import { cn } from "@/lib/utils"

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
  onCheckCondition?: () => void
  isEligible?: boolean
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
  onCheckCondition,
  isEligible = false
}: AdmissionActionsProps) {
  
  return (
    <div className="fixed bottom-0 left-0 lg:left-64 right-0 border-t bg-background p-4 z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)]">
        <div className="container max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-4">
                <span className="text-sm font-medium text-muted-foreground hidden sm:inline-block">
                    Trạng thái: 
                </span>
                <StatusBadge status={status} />
            </div>

            <div className="flex items-center gap-3">
                 {isDraft && (
                    <>
                        <Button variant="outline" onClick={onSave} disabled={isSaving}>
                            {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                            Lưu nháp
                        </Button>
                        
                        <Button variant="secondary" onClick={onCheckCondition}>
                            <ClipboardCheck className="w-4 h-4 mr-2" />
                            Kiểm tra điều kiện
                        </Button>

                        <Button 
                            onClick={onSubmit} 
                            disabled={isSubmitting || !isEligible}
                            className={cn(!isEligible && "opacity-80")}
                        >
                            {isSubmitting ? (
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            ) : !isEligible ? (
                                <Lock className="w-4 h-4 mr-2" />
                            ) : (
                                <Send className="w-4 h-4 mr-2" />
                            )}
                            Nộp hồ sơ
                        </Button>
                    </>
                 )}

                 {isApproved && (
                     <Button onClick={onEnroll} disabled={isEnrolling} className="bg-blue-600 hover:bg-blue-700">
                        {isEnrolling ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <GraduationCap className="w-4 h-4 mr-2" />}
                        Xác nhận nhập học
                     </Button>
                 )}
            </div>
        </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
    const map: Record<string, { label: string, className: string }> = {
        draft: { label: "Nháp", className: "bg-gray-100 text-gray-700" },
        submitted: { label: "Chờ duyệt", className: "bg-yellow-100 text-yellow-700" },
        approved: { label: "Đã duyệt", className: "bg-green-100 text-green-700" },
        rejected: { label: "Từ chối", className: "bg-red-100 text-red-700" },
        enrolled: { label: "Đã nhập học", className: "bg-blue-100 text-blue-700" },
    }
    const info = map[status] || { label: status, className: "bg-gray-100" }

    return <Badge className={info.className}>{info.label}</Badge>
}
