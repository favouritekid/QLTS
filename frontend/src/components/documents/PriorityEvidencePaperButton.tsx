"use client"

/**
 * GĐ2-F1 — nút "Đã nhận bản giấy" cho minh chứng ưu tiên (route GĐ2-0
 * `POST /api/v2/admissions/{id}/priority-evidence/{mã}/paper-submitted`, quyết định owner 19-11 câu 2).
 *
 * Người bấm được ghi là NGƯỜI NHẬN bản giấy và KHÔNG được tự duyệt / từ chối minh chứng ấy. Nút chỉ hiện khi máy chủ bật
 * `priority_evidence_documents[*].can_mark_paper_submitted` cho người xem (cùng hàm luật với cổng route — thin client:
 * không kiểm vai / trạng thái ở đây). Dòng đã ghi nhận bản giấy (`status = paper_submitted`) ⇒ hiện trạng thái thay nút.
 */
import { useState } from "react"
import { Building2, Loader2 } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { useMarkPriorityEvidencePaperSubmitted } from "@/lib/hooks/use-priority-evidence"
import { describePriorityEvidenceError } from "@/lib/priority-evidence/messages"
import { findEvidenceDocument } from "@/lib/utils/priority-evidence-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface Props {
  profile: AdmissionProfileResponse
  subCode: string
}

export function PriorityEvidencePaperButton({ profile, subCode }: Props) {
  const item = findEvidenceDocument(profile, subCode)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mark = useMarkPriorityEvidencePaperSubmitted(profile.id, subCode)

  if (item?.status === "paper_submitted") {
    return (
      <p className="text-xs text-muted-foreground" data-testid={`priority-evidence-paper-recorded-${subCode}`}>
        Đã ghi nhận minh chứng bản giấy (không có tệp).
      </p>
    )
  }
  if (item?.can_mark_paper_submitted !== true) return null

  const submit = () => {
    setError(null)
    mark.mutate(undefined, {
      onSuccess: () => {
        toast.success(`Đã ghi nhận bản giấy UT${subCode}`)
        setOpen(false)
      },
      onError: (e) => setError(describePriorityEvidenceError(e, "paper")),
    })
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          setError(null)
          setOpen(true)
        }}
        data-testid={`priority-evidence-paper-${subCode}`}
      >
        <Building2 className="mr-1 h-3 w-3" aria-hidden="true" />
        Đã nhận bản giấy
      </Button>
      <AlertDialog open={open} onOpenChange={(o) => !mark.isPending && setOpen(o)}>
        <AlertDialogContent data-testid={`priority-evidence-paper-dialog-${subCode}`}>
          <AlertDialogHeader>
            <AlertDialogTitle>Ghi nhận đã nhận bản giấy UT{subCode}?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn sẽ được ghi là người nhận bản giấy minh chứng này. Người nhận không được tự duyệt hay từ chối minh chứng
              — Quản lý trong đơn vị hoặc Admin khác sẽ duyệt.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mark.isPending}>Huỷ</AlertDialogCancel>
            <Button
              type="button"
              onClick={submit}
              disabled={mark.isPending}
              data-testid={`priority-evidence-paper-confirm-${subCode}`}
            >
              {mark.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              Ghi nhận
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
