"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useCancelCouncilDecisionRecord } from "@/hooks/admin/useCouncilDocuments"
import { councilConfirmNeededFromError, getCouncilDecision } from "@/lib/api/council-documents"
import { classifySubmissionError } from "@/lib/council-submission"
import type { CouncilConfirmNeeded } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { decisionKindLabel, statusLabel } from "./display"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  decisionId: number
  loai: string
  /** SỐ QUYẾT ĐỊNH của văn bản (máy chủ trả) — người dùng gõ lại để xác nhận; máy chủ so bằng nguyên chuỗi với `so_quyet_dinh` */
  decisionNumber: string
  /** sau khi văn bản đã ở trạng thái huỷ ghi nhận (huỷ thành công, hoặc đọc lại thấy đã huỷ) */
  onDone: () => void
}

type Reload = "khong" | "dang_doc" | "con_hieu_luc" | "loi"

/**
 * Huỷ ghi nhận (nhập SAI) — lý do bắt buộc, gõ lại SỐ QUYẾT ĐỊNH của văn bản (`so_go_lai`; đính chính đặc tả 12-11: máy chủ
 * `council_decision_service.huy_ghi_nhan` so với `so_quyet_dinh`, KHÔNG phải số hồ sơ), xác nhận trạng thái theo
 * `CouncilDecisionCancelIn` (đặc tả 5.6). Mất mạng / 5xx: KHÔNG cho bấm lại ngay — đọc lại `GET /decisions/{id}` trước (huỷ ghi nhận luỹ đẳng theo
 * trạng thái văn bản): thấy đã huỷ ⇒ xong; thấy còn hiệu lực ⇒ mới cho bấm lại; không đọc được ⇒ vẫn khoá.
 */
export function CouncilCancelDialog({ open, onOpenChange, decisionId, loai, decisionNumber, onDone }: Props) {
  const huy = useCancelCouncilDecisionRecord()
  const [reason, setReason] = useState("")
  const [removeAgainNumber, setRemoveAgainNumber] = useState("")
  const [canXn, setCanXn] = useState<CouncilConfirmNeeded | null>(null)
  const [typedConfirm, setTypedConfirm] = useState<Record<string, string>>({})
  const [reload, setReload] = useState<Reload>("khong")

  const confirmMatches = canXn === null || Object.entries(canXn.so_ho_so_theo_loai).every(([k, n]) => (typedConfirm[k] ?? "").trim() === String(n))
  const canSubmit = reason.trim() !== "" && removeAgainNumber.trim() !== "" && confirmMatches && reload !== "dang_doc" && reload !== "loi" && !huy.isPending

  const finish = () => {
    onOpenChange(false)
    toast.success("Đã huỷ ghi nhận.")
    onDone()
  }

  const recheck = async () => {
    setReload("dang_doc")
    try {
      const decision = await getCouncilDecision(decisionId)
      if (decision.trang_thai === "huy_ghi_nhan") {
        setReload("khong")
        finish()
      } else {
        setReload("con_hieu_luc")
      }
    } catch {
      setReload("loi")
    }
  }

  const gui = () => {
    setReload("khong")
    huy.mutate(
      {
        decisionId,
        payload: {
          ly_do: reason,
          // Cắt khoảng trắng đầu/cuối (dán thừa dấu cách): máy chủ so NGUYÊN chuỗi (`StrictStr`, không tự cắt), còn số Quyết định
          // lưu ở máy chủ luôn là 1–6 chữ số ASCII (`kiem_so_quyet_dinh`) nên không bao giờ có khoảng trắng đầu/cuối cần giữ.
          so_go_lai: removeAgainNumber.trim(),
          ...(canXn ? { xac_nhan: canXn.so_ho_so_theo_loai } : {}),
        },
      },
      {
        onSuccess: finish,
        onError: (error) => {
          const can = councilConfirmNeededFromError(error)
          if (can) {
            setCanXn(can)
            return
          }
          if (classifySubmissionError(error) === "chua_xac_dinh") void recheck()
        },
      },
    )
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !huy.isPending && onOpenChange(o)}>
      <AlertDialogContent data-testid="huy-ghi-nhan-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Huỷ ghi nhận {decisionKindLabel(loai)} số {decisionNumber}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            Dùng khi nhập SAI: văn bản coi như chưa từng ghi (giữ vết). Sau đó ghi nhận lại được.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="huy-ly-do">Lý do (bắt buộc)</Label>
            <Textarea id="huy-ly-do" data-testid="huy-ly-do" value={reason} disabled={huy.isPending} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="huy-so-quyet-dinh">Gõ lại số Quyết định của văn bản ({decisionNumber})</Label>
            <Input
              id="huy-so-quyet-dinh"
              data-testid="huy-so-quyet-dinh"
              className="max-w-[8rem]"
              inputMode="numeric"
              autoComplete="off"
              value={removeAgainNumber}
              disabled={huy.isPending}
              onChange={(e) => setRemoveAgainNumber(e.target.value)}
            />
          </div>

          {canXn ? (
            <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="huy-xac-nhan">
              <div className="text-sm font-medium">Có hồ sơ đổi trạng thái — gõ số hồ sơ để xác nhận</div>
              {Object.entries(canXn.so_ho_so_theo_loai).map(([k, n]) => (
                <div key={k} className="space-y-1">
                  <Label htmlFor={`huy-xn-${k}`}>
                    {`“${statusLabel(k)}”: ${n} hồ sơ (dòng ${(canXn.dong_theo_loai[k] ?? []).join(", ")})`}
                  </Label>
                  <Input
                    id={`huy-xn-${k}`}
                    data-testid={`huy-xac-nhan-${k}`}
                    className="max-w-[8rem]"
                    inputMode="numeric"
                    autoComplete="off"
                    value={typedConfirm[k] ?? ""}
                    onChange={(e) => setTypedConfirm((g) => ({ ...g, [k]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          ) : null}

          {reload === "dang_doc" ? (
            <p className="text-sm text-muted-foreground" data-testid="huy-doc-lai">
              <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Chưa rõ kết quả — đang đọc lại văn bản từ máy chủ…
            </p>
          ) : null}
          {reload === "con_hieu_luc" ? (
            <p className="text-sm" data-testid="huy-con-hieu-luc">
              Đã đọc lại: văn bản vẫn chưa bị huỷ ghi nhận — bấm lại được.
            </p>
          ) : null}
          {reload === "loi" ? (
            <div className="space-y-2 text-sm" role="alert" data-testid="huy-doc-lai-loi">
              <p>
                Chưa xác định được kết quả huỷ và đọc lại văn bản cũng không được. Chưa bấm lại — thử đọc lại.
              </p>
              <Button type="button" size="sm" variant="outline" onClick={() => void recheck()} data-testid="huy-doc-lai-nut">
                Đọc lại văn bản
              </Button>
            </div>
          ) : null}

          <CouncilErrorAlert error={huy.error} testId="huy-loi" />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={huy.isPending}>Đóng</AlertDialogCancel>
          <Button variant="destructive" disabled={!canSubmit} onClick={gui} data-testid="huy-xac-nhan-nut">
            {huy.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Huỷ ghi nhận
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
