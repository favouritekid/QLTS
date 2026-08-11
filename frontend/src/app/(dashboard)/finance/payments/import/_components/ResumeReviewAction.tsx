"use client"

/**
 * "Ghi tiếp các dòng nghi trùng" — mở lại từ LỊCH SỬ LÔ.
 *
 * Vì sao cần: một lô còn dòng bị hàng rào giữ lại vẫn ở `preview`, và trước
 * đây đường ghi tiếp CHỈ tồn tại trên màn kết quả ngay sau commit. Người dùng
 * refresh hay đóng tab là lô mắc kẹt — backend vẫn nhận `confirmed_rows` nhưng
 * giao diện không còn chỗ nào gửi chúng.
 *
 * Ba điều component này cố ý KHÔNG làm:
 *
 * 1. **Không tự suy quyền.** Nó chỉ được render khi `batch.can_resume_commit`,
 *    cờ do máy chủ cấp. `status` + counter có sẵn ở client nhưng không mang
 *    thông tin quyền; suy từ chúng là vẽ một nút dẫn tới 403.
 * 2. **Không cho phiếu vào React Query / Zustand / storage.** Phiếu lấy bằng
 *    một lời gọi API TRỰC TIẾP mỗi lần mở, sống trong state cục bộ, và chết khi
 *    đóng. Cache 30 giây của `usePaymentImportBatchDetail` là thứ phải tránh ở
 *    đây: phiếu nói về một tập ứng viên tại một thời điểm, dùng lại bản cũ là
 *    xin xác nhận cho một câu hỏi khác.
 * 3. **Không dựng máy trạng thái thứ hai.** Việc gửi đi vẫn là
 *    `useCommitPaymentImport` với `confirmedRows` — đúng đường mà màn kết quả
 *    đang dùng.
 */

import { useState } from "react"
import { AlertTriangle, Loader2, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { toast } from "sonner"

import { paymentImportApi } from "@/lib/api/payment-import"
import { coPhieuHetHieuLuc, LOI_TAP_DA_DOI } from "@/lib/finance/import-review"
import { useCommitPaymentImport } from "@/hooks/finance/usePaymentImport"
import type { PaymentImportRow } from "@/lib/zod/payment-import"
import { ImportRowsTable } from "./ImportRowsTable"

interface Props {
  batchId: number
  /** Số dòng đang chờ soát — dùng để nói rõ trên nhãn nút. */
  reviewRequiredCount: number
}

export function ResumeReviewAction({ batchId, reviewRequiredCount }: Props) {
  const [open, setOpen] = useState(false)
  const [dangTai, setDangTai] = useState(false)
  const [dongChoSoat, setDongChoSoat] = useState<PaymentImportRow[] | null>(null)
  // Máy chủ đã từ chối phiếu vừa gửi vì tập ứng viên đổi giữa chừng, và cấp
  // phiếu MỚI. `daTick` là xác nhận cho tập mới ấy — luôn bắt đầu từ false, kể
  // cả khi người dùng vừa tick cho tập cũ vài giây trước.
  const [tapDaDoi, setTapDaDoi] = useState(false)
  const [daTick, setDaTick] = useState(false)
  const commit = useCommitPaymentImport()

  const dangBan = dangTai || commit.isPending

  async function moVaNapPhieu() {
    // Chặn lượt thứ hai của một cú double-click: `dangTai` bật TRƯỚC await.
    if (dangBan) return
    setDangTai(true)
    try {
      const detail = await paymentImportApi.getBatchDetail(batchId)

      // FAIL-CLOSED. Một dòng chờ soát mà thiếu phiếu thì không có gì để xác
      // nhận, và mở hộp thoại với nút bấm vô hiệu còn tệ hơn một lời từ chối
      // thẳng thắn. Cũng KHÔNG lọc bỏ dòng thiếu phiếu rồi gửi phần còn lại:
      // như vậy là âm thầm bỏ sót đúng thứ người dùng định xử lý.
      const rows = detail.rows.filter(
        (r) => r.commit_status === "duplicate_review_required",
      )
      if (rows.length === 0) {
        toast.info("Lô này không còn dòng nào chờ soát.")
        return
      }
      if (rows.some((r) => !r.review_token)) {
        toast.error(
          "Dữ liệu lô không đầy đủ (thiếu phiếu xác nhận cho một dòng). " +
            "Hãy tải lại trang; nếu vẫn vậy thì lô cần được xử lý lại từ đầu.",
        )
        return
      }

      // Mở lại = một câu hỏi mới: cảnh báo và tick của lượt trước không được
      // sống sót qua đây.
      setTapDaDoi(false)
      setDaTick(false)
      setDongChoSoat(rows)
      setOpen(true)
    } catch {
      toast.error("Không tải được chi tiết lô để ghi tiếp.")
    } finally {
      setDangTai(false)
    }
  }

  function ghiTiep() {
    if (dangBan || !dongChoSoat) return
    if (tapDaDoi && !daTick) return
    const daGui = dongChoSoat.map((r) => ({
      row_no: r.row_no,
      review_token: r.review_token as string,
    }))
    commit.mutate(
      // Gửi ĐÚNG phiếu của từng dòng, không phải một cờ cho cả lô.
      { batchId, confirmedRows: daGui },
      {
        onSuccess: (ketQua) => {
          // Máy chủ trả 200 cho cả ca "đã ghi" lẫn ca "phiếu hết hiệu lực".
          // Ca sau: tập ứng viên đã đổi giữa lúc phiếu được cấp và lúc gửi,
          // không dòng nào vào sổ, và máy chủ vừa cấp phiếu MỚI. Đóng hộp
          // thoại ở đây là biến việc cấp lại phiếu thành "bấm thử lần nữa" —
          // trong khi đó là một câu hỏi khác, về một tập ứng viên khác.
          const conCho = ketQua.rows.filter(
            (r) => r.commit_status === "duplicate_review_required" && r.review_token,
          )
          if (coPhieuHetHieuLuc(daGui, ketQua.rows) && conCho.length > 0) {
            setDongChoSoat(conCho) // thay TOÀN BỘ danh sách + phiếu bằng bản mới
            setTapDaDoi(true)
            setDaTick(false) // xác nhận cũ nói về tập cũ ⇒ vứt
            return
          }
          // Đóng và VỨT phiếu. Hook đã invalidate danh sách + chi tiết, nên
          // `can_resume_commit` được tính lại và nút tự biến mất khi hết dòng
          // chờ — không tự suy ở client.
          setOpen(false)
          setDongChoSoat(null)
          setTapDaDoi(false)
          setDaTick(false)
        },
      },
    )
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={dangBan}
        aria-label={`Ghi tiếp ${reviewRequiredCount} dòng nghi trùng của lô ${batchId}`}
        onClick={moVaNapPhieu}
        className="border-amber-400 text-amber-900 hover:bg-amber-100 dark:text-amber-200"
      >
        {dangTai ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <RotateCcw className="h-4 w-4" />
        )}
        <span className="ml-1.5 hidden sm:inline">
          Ghi tiếp ({reviewRequiredCount})
        </span>
      </Button>

      <Dialog
        open={open}
        onOpenChange={(v) => {
          // Đóng là VỨT phiếu — không giữ lại cho lần mở sau. Lần sau nạp mới.
          if (!v) {
            setDongChoSoat(null)
            setTapDaDoi(false)
            setDaTick(false)
          }
          setOpen(v)
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-600" />
              Ghi tiếp các dòng nghi trùng — lô #{batchId}
            </DialogTitle>
            <DialogDescription>
              Những dòng dưới đây bị giữ lại vì trùng với phiếu đã ghi. Đối
              chiếu với phiếu nêu trong cột lý do; nếu đúng là khoản thu riêng
              thì ghi tiếp. Các dòng đã vào sổ sẽ không bị ghi hai lần.
            </DialogDescription>
          </DialogHeader>

          {/* Phiếu vừa gửi bị từ chối: nói thẳng rằng CHƯA gì vào sổ và bảng
              dưới đây là tập MỚI. Không có khối này thì màn hình trông y hệt
              lúc chưa bấm, và cú bấm lại thành "thử lần nữa". */}
          {tapDaDoi && (
            <div
              role="alert"
              className="rounded-md border border-red-300 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950/40"
            >
              <p className="text-sm font-medium text-red-900 dark:text-red-200">
                {LOI_TAP_DA_DOI}
              </p>
            </div>
          )}

          {dongChoSoat ? <ImportRowsTable rows={dongChoSoat} /> : null}

          {tapDaDoi && (
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={daTick}
                onCheckedChange={(v) => setDaTick(v === true)}
                disabled={commit.isPending}
                aria-label="Tôi đã soát lại danh sách ứng viên mới"
              />
              <span>Tôi đã soát lại danh sách ứng viên mới ở trên.</span>
            </label>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={commit.isPending}
            >
              Để sau
            </Button>
            <Button
              onClick={ghiTiep}
              disabled={dangBan || !dongChoSoat || (tapDaDoi && !daTick)}
            >
              {commit.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  Đang ghi…
                </>
              ) : (
                `Đã soát — ghi tiếp ${dongChoSoat?.length ?? 0} dòng`
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
