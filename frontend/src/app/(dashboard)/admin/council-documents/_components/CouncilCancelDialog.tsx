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
import { phanLoaiLoiGui } from "@/lib/council-submission"
import type { CouncilConfirmNeeded } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { nhanLoaiQuyetDinh, nhanTrangThai } from "./hien-thi"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  decisionId: number
  loai: string
  soQuyetDinh: string
  /** số hồ sơ của văn bản (máy chủ trả) — người dùng gõ lại để xác nhận */
  soHoSo: number
  /** sau khi văn bản đã ở trạng thái huỷ ghi nhận (huỷ thành công, hoặc đọc lại thấy đã huỷ) */
  onXong: () => void
}

type DocLai = "khong" | "dang_doc" | "con_hieu_luc" | "loi"

/**
 * Huỷ ghi nhận (nhập SAI) — lý do bắt buộc, gõ lại số hồ sơ, xác nhận trạng thái theo `CouncilDecisionCancelIn` (đặc tả
 * 5.6). Mất mạng / 5xx: KHÔNG cho bấm lại ngay — đọc lại `GET /decisions/{id}` trước (huỷ ghi nhận luỹ đẳng theo
 * trạng thái văn bản): thấy đã huỷ ⇒ xong; thấy còn hiệu lực ⇒ mới cho bấm lại; không đọc được ⇒ vẫn khoá.
 */
export function CouncilCancelDialog({ open, onOpenChange, decisionId, loai, soQuyetDinh, soHoSo, onXong }: Props) {
  const huy = useCancelCouncilDecisionRecord()
  const [lyDo, setLyDo] = useState("")
  const [soGoLai, setSoGoLai] = useState("")
  const [canXn, setCanXn] = useState<CouncilConfirmNeeded | null>(null)
  const [goXn, setGoXn] = useState<Record<string, string>>({})
  const [docLai, setDocLai] = useState<DocLai>("khong")

  const xnKhop = canXn === null || Object.entries(canXn.so_ho_so_theo_loai).every(([k, n]) => (goXn[k] ?? "").trim() === String(n))
  const duDieuKien = lyDo.trim() !== "" && soGoLai.trim() !== "" && xnKhop && docLai !== "dang_doc" && docLai !== "loi" && !huy.isPending

  const ketThuc = () => {
    onOpenChange(false)
    toast.success("Đã huỷ ghi nhận.")
    onXong()
  }

  const kiemLai = async () => {
    setDocLai("dang_doc")
    try {
      const qd = await getCouncilDecision(decisionId)
      if (qd.trang_thai === "huy_ghi_nhan") {
        setDocLai("khong")
        ketThuc()
      } else {
        setDocLai("con_hieu_luc")
      }
    } catch {
      setDocLai("loi")
    }
  }

  const gui = () => {
    setDocLai("khong")
    huy.mutate(
      {
        decisionId,
        payload: {
          ly_do: lyDo,
          so_go_lai: soGoLai,
          ...(canXn ? { xac_nhan: canXn.so_ho_so_theo_loai } : {}),
        },
      },
      {
        onSuccess: ketThuc,
        onError: (loi) => {
          const can = councilConfirmNeededFromError(loi)
          if (can) {
            setCanXn(can)
            return
          }
          if (phanLoaiLoiGui(loi) === "chua_xac_dinh") void kiemLai()
        },
      },
    )
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !huy.isPending && onOpenChange(o)}>
      <AlertDialogContent data-testid="huy-ghi-nhan-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Huỷ ghi nhận {nhanLoaiQuyetDinh(loai)} số {soQuyetDinh}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            Dùng khi nhập SAI: văn bản coi như chưa từng ghi (giữ vết). Sau đó ghi nhận lại được.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="huy-ly-do">Lý do (bắt buộc)</Label>
            <Textarea id="huy-ly-do" data-testid="huy-ly-do" value={lyDo} disabled={huy.isPending} onChange={(e) => setLyDo(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="huy-so-ho-so">Gõ lại số hồ sơ của văn bản ({soHoSo})</Label>
            <Input
              id="huy-so-ho-so"
              data-testid="huy-so-ho-so"
              className="max-w-[8rem]"
              inputMode="numeric"
              autoComplete="off"
              value={soGoLai}
              disabled={huy.isPending}
              onChange={(e) => setSoGoLai(e.target.value)}
            />
          </div>

          {canXn ? (
            <div className="space-y-2 rounded border border-warning-500/50 p-3" data-testid="huy-xac-nhan">
              <div className="text-sm font-medium">Có hồ sơ đổi trạng thái — gõ số hồ sơ để xác nhận</div>
              {Object.entries(canXn.so_ho_so_theo_loai).map(([k, n]) => (
                <div key={k} className="space-y-1">
                  <Label htmlFor={`huy-xn-${k}`}>
                    {`“${nhanTrangThai(k)}”: ${n} hồ sơ (dòng ${(canXn.dong_theo_loai[k] ?? []).join(", ")})`}
                  </Label>
                  <Input
                    id={`huy-xn-${k}`}
                    data-testid={`huy-xac-nhan-${k}`}
                    className="max-w-[8rem]"
                    inputMode="numeric"
                    autoComplete="off"
                    value={goXn[k] ?? ""}
                    onChange={(e) => setGoXn((g) => ({ ...g, [k]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          ) : null}

          {docLai === "dang_doc" ? (
            <p className="text-sm text-muted-foreground" data-testid="huy-doc-lai">
              <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Chưa rõ kết quả — đang đọc lại văn bản từ máy chủ…
            </p>
          ) : null}
          {docLai === "con_hieu_luc" ? (
            <p className="text-sm" data-testid="huy-con-hieu-luc">
              Đã đọc lại: văn bản vẫn chưa bị huỷ ghi nhận — bấm lại được.
            </p>
          ) : null}
          {docLai === "loi" ? (
            <div className="space-y-2 text-sm" role="alert" data-testid="huy-doc-lai-loi">
              <p>
                Chưa xác định được kết quả huỷ và đọc lại văn bản cũng không được. Chưa bấm lại — thử đọc lại.
              </p>
              <Button type="button" size="sm" variant="outline" onClick={() => void kiemLai()} data-testid="huy-doc-lai-nut">
                Đọc lại văn bản
              </Button>
            </div>
          ) : null}

          <CouncilErrorAlert error={huy.error} testId="huy-loi" />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={huy.isPending}>Đóng</AlertDialogCancel>
          <Button variant="destructive" disabled={!duDieuKien} onClick={gui} data-testid="huy-xac-nhan-nut">
            {huy.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Huỷ ghi nhận
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
