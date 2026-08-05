"use client"

import { type FormEvent, type ReactNode, useState } from "react"
import { AlertCircle, CheckCircle2, Clock, Loader2, Receipt } from "lucide-react"

import { AmountDisplay, FeeStatusBadge } from "@/components/finance"
import { todayVN } from "@/lib/utils/vn-date"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useRecordApplicationFeePayment } from "@/hooks/admissions"
import { hasAction } from "@/lib/admission/permissions"
import { formatDateTime } from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ApplicationFeeCollectionPanelProps {
  profile: AdmissionProfileResponse
}

const RECEIPT_MIN_LENGTH = 6
const RECEIPT_MAX_LENGTH = 80

export function suggestReceiptCode(profileId: number, now: Date = new Date()): string {
  // Pre-fill an editable default so the officer isn't stuck on a blank,
  // required field ("không biết nhập gì"). Unique per (hồ sơ, ngày) → thỏa
  // ràng buộc chống trùng biên lai của backend. Officer giữ nguyên khi thu
  // tiền mặt tại quầy, hoặc thay bằng số phiếu thu giấy thực tế.
  //
  // Ngày lấy theo LỊCH VIỆT NAM, không phải `toISOString()`. Máy chủ chạy UTC
  // và giao dịch trước 07:00 sáng rơi vào ngày hôm trước theo UTC — mã sinh ra
  // sẽ mang ngày cũ, và vì ràng buộc chống trùng là theo (hồ sơ, ngày) nên nó
  // có thể đụng đúng biên lai của hôm qua.
  const today = todayVN(now).replace(/-/g, "")
  return `PT-${profileId}-${today}`
}

export function ApplicationFeeCollectionPanel({
  profile,
}: ApplicationFeeCollectionPanelProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const rules = profile.applied_rules
  const requiresFee = rules.requires_application_fee === true
  const feeStatus = rules.fee_status ?? (requiresFee ? "pending" : "exempt")
  const applicationFee = Number(rules.application_fee ?? 0)
  const paymentData = rules.fee_payment_data
  const canRecordFee =
    hasAction(profile, "record_fee_payment") &&
    profile.permissions?.record_fee_payment === true

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Receipt className="h-5 w-5" aria-hidden="true" />
          Lệ phí xét tuyển
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!requiresFee ? (
          <ReadOnlyState
            icon={<CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
            label="Không yêu cầu lệ phí xét tuyển"
          />
        ) : feeStatus === "paid" ? (
          <PaidState
            amount={paymentData?.amount ?? applicationFee}
            feePaidAt={rules.fee_paid_at ?? paymentData?.paid_at ?? null}
            transactionId={paymentData?.transaction_id}
          />
        ) : feeStatus === "exempt" ? (
          <ReadOnlyState
            icon={<CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
            label="Miễn lệ phí xét tuyển"
          />
        ) : (
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="gap-1.5">
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  Chờ thu
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                Số tiền:{" "}
                <AmountDisplay amount={applicationFee} className="font-medium text-foreground" />
              </p>
            </div>

            {canRecordFee && applicationFee > 0 ? (
              <Button onClick={() => setDialogOpen(true)}>
                <Receipt className="mr-2 h-4 w-4" aria-hidden="true" />
                Thu lệ phí
              </Button>
            ) : null}
          </div>
        )}

        {dialogOpen && (
          <ApplicationFeePaymentDialog
            amount={applicationFee}
            open={dialogOpen}
            profileId={profile.id}
            onOpenChange={setDialogOpen}
          />
        )}
      </CardContent>
    </Card>
  )
}

function PaidState({
  amount,
  feePaidAt,
  transactionId,
}: {
  amount: string | number
  feePaidAt: string | null
  transactionId?: string
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FeeStatusBadge status="paid" size="sm" />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <InfoBlock label="Biên lai" value={transactionId ?? "-"} />
        <InfoBlock label="Số tiền" value={<AmountDisplay amount={amount} />} />
        <InfoBlock label="Thời điểm thu" value={formatDateTime(feePaidAt)} />
      </div>
    </div>
  )
}

function ReadOnlyState({
  icon,
  label,
}: {
  icon: ReactNode
  label: string
}) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      {icon}
      <span>{label}</span>
    </div>
  )
}

function InfoBlock({
  label,
  value,
}: {
  label: string
  value: ReactNode
}) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 break-words text-sm font-medium">{value}</div>
    </div>
  )
}

function ApplicationFeePaymentDialog({
  amount,
  open,
  profileId,
  onOpenChange,
}: {
  amount: number
  open: boolean
  profileId: number
  onOpenChange: (open: boolean) => void
}) {
  const [transactionId, setTransactionId] = useState(() =>
    suggestReceiptCode(profileId),
  )
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const mutation = useRecordApplicationFeePayment(profileId)
  const trimmedTransactionId = transactionId.trim()
  const isPending = mutation.isPending

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setErrorMessage(null)

    if (
      trimmedTransactionId.length < RECEIPT_MIN_LENGTH ||
      trimmedTransactionId.length > RECEIPT_MAX_LENGTH
    ) {
      setErrorMessage("Mã biên lai phải từ 6 đến 80 ký tự.")
      return
    }

    try {
      await mutation.mutateAsync({
        transaction_id: trimmedTransactionId,
        amount,
        payment_method_code: "cash",
      })
      onOpenChange(false)
      setTransactionId("")
    } catch (error) {
      setErrorMessage(getMutationErrorMessage(error))
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isPending) onOpenChange(next)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Receipt className="h-5 w-5 text-primary" aria-hidden="true" />
            Thu lệ phí xét tuyển
          </DialogTitle>
          <DialogDescription>
            Ghi nhận lệ phí xét tuyển bằng tiền mặt cho hồ sơ này.
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="application_fee_amount">Số tiền</Label>
            <div
              id="application_fee_amount"
              className="rounded-md border bg-muted/40 px-3 py-2 text-sm"
            >
              <AmountDisplay amount={amount} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="application_fee_receipt">Mã biên lai</Label>
            <Input
              id="application_fee_receipt"
              value={transactionId}
              onChange={(event) => setTransactionId(event.target.value)}
              onFocus={(event) => event.target.select()}
              minLength={RECEIPT_MIN_LENGTH}
              maxLength={RECEIPT_MAX_LENGTH}
              placeholder="VD: số phiếu thu giấy — hoặc giữ mã gợi ý"
              disabled={isPending}
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              Số biên lai/phiếu thu giấy (nếu có). Đã điền sẵn mã gợi ý duy nhất —
              giữ nguyên hoặc thay bằng số biên lai thực tế (6–80 ký tự).
            </p>
          </div>

          <div className="space-y-2">
            <Label>Phương thức</Label>
            <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
              Tiền mặt
            </div>
          </div>

          {errorMessage ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" aria-hidden="true" />
              <AlertDescription>{errorMessage}</AlertDescription>
            </Alert>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={isPending}
              onClick={() => onOpenChange(false)}
            >
              Hủy
            </Button>
            <Button type="submit" disabled={isPending || amount <= 0}>
              {isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              Xác nhận thu
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function getMutationErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === "string" && detail.trim()) {
      return detail
    }
  }
  return "Không thể ghi nhận lệ phí. Vui lòng thử lại."
}
