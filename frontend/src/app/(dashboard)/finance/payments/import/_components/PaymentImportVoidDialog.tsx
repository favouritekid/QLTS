"use client"

import { Loader2, Undo2 } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useVoidPaymentImport } from "@/hooks/finance/usePaymentImport"
import { paymentImportVoidFormSchema } from "@/lib/zod/payment-import"

interface Props {
  batchId: number
}

export function PaymentImportVoidDialog({ batchId }: Props) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const voidBatch = useVoidPaymentImport()

  // Reset reason/error khi đóng (Esc/overlay/Hủy) → mở lại không dính state cũ.
  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    if (!next) {
      setReason("")
      setError(null)
    }
  }

  const handleConfirm = () => {
    const parsed = paymentImportVoidFormSchema.safeParse({ reason })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Lý do không hợp lệ")
      return
    }
    setError(null)
    voidBatch.mutate(
      { batchId, reason: parsed.data.reason },
      { onSuccess: () => handleOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Undo2 className="mr-1.5 h-4 w-4" />
          Đảo lô
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Đảo (void) lô #{batchId}</DialogTitle>
          <DialogDescription>
            Rút lại toàn bộ khoản thu đã ghi của lô này (hoàn về invoice/học phí)
            và mở lại file để import lại. Chỉ quản lý/admin. Nhập lý do để lưu
            vết.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="void-reason">Lý do đảo lô</Label>
          <Textarea
            id="void-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="VD: import nhầm năm học / sai hồ sơ…"
            rows={3}
          />
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => handleOpenChange(false)}
            disabled={voidBatch.isPending}
          >
            Hủy
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={voidBatch.isPending}
          >
            {voidBatch.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : null}
            Xác nhận đảo lô
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
