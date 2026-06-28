"use client"

/**
 * CalculateFeeDialog — inline fee calculation from the admission detail.
 *
 * Replaces the legacy `Link → /finance/fees?action=calculate` for
 * officer-scoped fee creation. Rendered from TuitionTab inside the
 * admission detail page; officers with `available_actions` including
 * `calculate_fee` see the trigger button and can generate the
 * official Fee + invoices without leaving the admissions module.
 *
 * PR #7 review (2026-04-24):
 *  - Installment plan codes now come from `useInstallmentPlans` rather
 *    than a hard-coded list. Backend seed currently ships FULL /
 *    TWO_TERM / QUARTERLY; the dialog no longer guesses codes that
 *    might not exist. Backend also now rejects unknown codes with 400
 *    so a drift gets surfaced instead of silently creating a
 *    single-payment invoice.
 *  - Form schema no longer uses z.coerce + default() defaults so the
 *    RHF<Values> generic resolves cleanly under strict tsc.
 *
 * Manual tuition override (2026-06-28):
 *  - Khi loại phí là HỌC PHÍ, accountant/officer có thể bật toggle "Nhập
 *    học phí thủ công" để đặt mức học phí đặc biệt (học bổng / chuyển
 *    trường / theo quyết định). Số gõ là BASE (TRƯỚC giảm giá): backend
 *    VẪN áp discount hiện hành → invoice khớp final (≠ số gõ nếu có giảm).
 *  - Add-on: (1) toggle, (2) hiện giá chuẩn + chênh lệch + dự kiến phải
 *    thu (useTuitionPreview), (3) dialog xác nhận tóm tắt, (4) chip lý do.
 */
import { useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Loader2, Calculator } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { CurrencyInput } from "@/components/ui/currency-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { useCalculateFee, useTuitionPreview, feesKeys } from "@/hooks/finance/useFees"
import { useInstallmentPlans } from "@/hooks/finance/useInstallmentPlans"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { financeDashboardKeys } from "@/hooks/finance/useFinanceDashboard"
import { formatVND } from "@/lib/zod/finance"

type FeeType = "tuition" | "application" | "dormitory" | "other"

interface Props {
  open: boolean
  onOpenChange: (next: boolean) => void
  profileId: number
  /** Fired after a successful calculate (caller can open the result drawer). */
  onSuccess?: () => void
}

const SEMESTER_OPTIONS = [
  { value: 1, label: "Học kỳ 1" },
  { value: 2, label: "Học kỳ 2" },
  { value: 3, label: "Học kỳ 3+" },
]

const MANUAL_REASON_MIN = 10
const MANUAL_REASON_MAX = 500

// (#4) Chip lý do mẫu — label ngắn để bấm nhanh, value đầy đủ (≥10 ký tự để
// thỏa ràng buộc reason) set vào ô lý do.
const REASON_CHIPS: { label: string; value: string }[] = [
  { label: "Học bổng", value: "Học bổng theo quyết định của nhà trường" },
  { label: "Chuyển trường", value: "Điều chỉnh học phí do chuyển trường" },
  { label: "Theo quyết định", value: "Áp dụng học phí theo quyết định riêng" },
  { label: "Điều chỉnh khác", value: "Điều chỉnh học phí trường hợp đặc biệt" },
]

export function CalculateFeeDialog({ open, onOpenChange, profileId, onSuccess }: Props) {
  const queryClient = useQueryClient()
  const calculateFee = useCalculateFee()
  const plansQuery = useInstallmentPlans({ enabled: open })

  // Local state — simpler than RHF for 3 controlled selects and avoids
  // the strict-tsc friction with zod `z.coerce` + `.default()` generics.
  const [feeType, setFeeType] = useState<FeeType>("tuition")
  const [semesterNo, setSemesterNo] = useState<number>(1)
  const [planCode, setPlanCode] = useState<string>("")

  // Manual tuition override state.
  const [manualMode, setManualMode] = useState<boolean>(false)
  const [manualAmount, setManualAmount] = useState<number | null>(null)
  const [manualReason, setManualReason] = useState<string>("")
  const [confirmOpen, setConfirmOpen] = useState<boolean>(false)

  const activePlans = useMemo(
    () => (plansQuery.data ?? []).filter((p) => p.is_active !== false),
    [plansQuery.data]
  )

  // Derived default (no useEffect — avoids react-hooks/incompatible-library
  // setState-in-effect lint error). When user hasn't explicitly picked,
  // prefer FULL (matches backend FeeCalculateRequest.installment_plan_code
  // default), otherwise the first active option. setPlanCode only fires on
  // explicit user choice, so derived value flips back to default if the
  // plan list reloads after a reset.
  const effectivePlanCode = useMemo(() => {
    if (planCode) return planCode
    if (activePlans.length === 0) return ""
    return (activePlans.find((p) => p.code === "FULL") ?? activePlans[0]).code
  }, [planCode, activePlans])

  const isTuition = feeType === "tuition"
  const isManual = isTuition && manualMode
  const isPending = calculateFee.isPending

  // (#2) Giá chuẩn — chỉ fetch khi bật nhập tay (read-only preview). Refetch
  // khi đổi học kỳ (semesterNo nằm trong queryKey của hook).
  const preview = useTuitionPreview(profileId, semesterNo, {
    enabled: open && isManual && !!profileId,
  })

  const reasonLen = manualReason.trim().length
  const manualValid =
    !!manualAmount && manualAmount > 0 && reasonLen >= MANUAL_REASON_MIN && reasonLen <= MANUAL_REASON_MAX

  const canSubmit =
    effectivePlanCode !== "" &&
    !isPending &&
    activePlans.length > 0 &&
    (!isManual || manualValid)

  // Dẫn xuất hiển thị cho (#2)/(#3). Tất cả là NULL khi chưa có giá chuẩn
  // (preview đang tải / lỗi vì ngành chưa xác định) → KHÔNG hiện số 0 gây hiểu
  // nhầm "không giảm giá". "Ước tính phải thu" = số gõ − giảm giá hiện hành; backend
  // là nguồn sự thật CUỐI — với discount %, backend tính lại trên SỐ GÕ nên ước
  // tính có thể lệch hóa đơn. Vì vậy nhãn ghi rõ "ước tính" + không khẳng định.
  const canonicalBase = preview.data ? Number(preview.data.base_amount) : null
  const currentDiscount = preview.data ? Number(preview.data.total_discount) : null
  const diffFromCanonical =
    manualAmount != null && canonicalBase != null ? manualAmount - canonicalBase : null
  const estimatedPayable =
    manualAmount != null && currentDiscount != null
      ? Math.max(0, manualAmount - currentDiscount)
      : null

  const reset = () => {
    setFeeType("tuition")
    setSemesterNo(1)
    setPlanCode("")
    setManualMode(false)
    setManualAmount(null)
    setManualReason("")
    setConfirmOpen(false)
  }

  /** Thực thi mutate + invalidate cache + đóng dialog (sau khi đã xác nhận). */
  const doSubmit = async () => {
    if (!canSubmit) return

    await calculateFee.mutateAsync({
      admission_profile_id: profileId,
      fee_type: feeType,
      // Only tuition carries semester_no; backend validator rejects it
      // for non-tuition fee types, so omit entirely when switching away.
      semester_no: isTuition ? semesterNo : undefined,
      installment_plan_code: effectivePlanCode,
      // Manual override chỉ gửi khi toggle bật (và là tuition). Decimal-as-string.
      ...(isManual && manualAmount != null
        ? { manual_base_amount: String(manualAmount), manual_reason: manualReason.trim() }
        : {}),
    })

    // useCalculateFee already invalidates finance caches + toasts on
    // success. Extend to the admission caches + dashboard so the
    // Tuition tab refreshes without a reload. Use admissionsKeys.all
    // (root) so status-counts + stats refetch alongside list/detail —
    // calculating a fee flips the row's payment-status tab, so the
    // tab badges on /admissions need to update too.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all }),
      queryClient.invalidateQueries({ queryKey: feesKeys.lists() }),
      queryClient.invalidateQueries({ queryKey: feesKeys.byProfile(profileId) }),
      queryClient.invalidateQueries({ queryKey: feesKeys.profileSummary(profileId) }),
      queryClient.invalidateQueries({ queryKey: financeDashboardKeys.all }),
    ])

    reset()
    onSuccess?.()
    onOpenChange(false)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    // (#3) Khi nhập tay → mở dialog xác nhận tóm tắt trước khi tạo. Luồng cũ
    // (không nhập tay) submit thẳng.
    if (isManual) {
      setConfirmOpen(true)
      return
    }
    await doSubmit()
  }

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => (isPending ? null : onOpenChange(next))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Calculator className="h-5 w-5 text-primary" />
              Tính học phí
            </DialogTitle>
            <DialogDescription>
              Tạo bản ghi học phí chính thức cho hồ sơ. Hệ thống sẽ tự tạo
              hóa đơn theo kế hoạch thanh toán đã chọn.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="fee_type">Loại phí</Label>
              <Select
                value={feeType}
                onValueChange={(v) => setFeeType(v as FeeType)}
                disabled={isPending}
              >
                <SelectTrigger id="fee_type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tuition">Học phí</SelectItem>
                  <SelectItem value="application">Lệ phí xét tuyển</SelectItem>
                  <SelectItem value="dormitory">Phí ký túc xá</SelectItem>
                  <SelectItem value="other">Khác</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {isTuition && (
              <div className="space-y-2">
                <Label htmlFor="semester_no">Học kỳ</Label>
                <Select
                  value={String(semesterNo)}
                  onValueChange={(v) => setSemesterNo(parseInt(v, 10))}
                  disabled={isPending}
                >
                  <SelectTrigger id="semester_no">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEMESTER_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={String(opt.value)}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* (#1) Toggle nhập học phí thủ công — chỉ cho học phí. */}
            {isTuition && (
              <div className="rounded-lg border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label htmlFor="manual_mode" className="cursor-pointer">
                      Nhập học phí thủ công
                    </Label>
                    <p className="text-muted-foreground text-xs">
                      Đặt mức học phí đặc biệt (học bổng / chuyển trường / theo quyết định).
                    </p>
                  </div>
                  <Switch
                    id="manual_mode"
                    checked={manualMode}
                    onCheckedChange={setManualMode}
                    disabled={isPending}
                  />
                </div>

                {isManual && (
                  <div className="space-y-3 pt-1">
                    <div className="space-y-1.5">
                      <Label htmlFor="manual_amount">
                        Mức học phí (trước giảm giá){" "}
                        <span className="text-destructive">*</span>
                      </Label>
                      <CurrencyInput
                        id="manual_amount"
                        value={manualAmount}
                        onChange={setManualAmount}
                        placeholder="Nhập mức học phí…"
                        disabled={isPending}
                      />

                      {/* (#2) Giá chuẩn + chênh lệch + dự kiến phải thu. */}
                      <div className="text-xs space-y-1 pt-1">
                        {preview.isLoading && (
                          <p className="text-muted-foreground">Đang tải giá chuẩn…</p>
                        )}
                        {preview.isError && (
                          <p className="text-destructive">
                            Không tải được giá chuẩn (hồ sơ có thể chưa xác định ngành).
                          </p>
                        )}
                        {preview.data && (
                          <>
                            <div className="flex items-center justify-between">
                              <span className="text-muted-foreground">Giá chuẩn (base):</span>
                              <span className="font-medium">
                                {formatVND(preview.data.base_amount)}
                              </span>
                            </div>
                            {diffFromCanonical != null && diffFromCanonical !== 0 && (
                              <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Chênh lệch:</span>
                                <Badge
                                  variant={diffFromCanonical > 0 ? "destructive" : "secondary"}
                                  className="font-normal"
                                >
                                  {diffFromCanonical > 0 ? "+" : "−"}
                                  {formatVND(Math.abs(diffFromCanonical))}
                                </Badge>
                              </div>
                            )}
                            <div className="flex items-center justify-between">
                              <span className="text-muted-foreground">
                                Giảm giá (theo giá chuẩn):
                              </span>
                              <span className="font-medium">
                                {formatVND(preview.data.total_discount)}
                              </span>
                            </div>
                            {estimatedPayable != null && (
                              <div className="flex items-center justify-between border-t pt-1">
                                <span className="text-muted-foreground">
                                  Ước tính phải thu:
                                </span>
                                <span className="font-semibold text-primary">
                                  {formatVND(estimatedPayable)}
                                </span>
                              </div>
                            )}
                            {Number(preview.data.total_discount) > 0 && (
                              <p className="text-muted-foreground pt-0.5">
                                Số phải thu chính xác do hệ thống tính lại theo
                                chính sách giảm giá khi tạo.
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="manual_reason">
                        Lý do nhập tay <span className="text-destructive">*</span>
                      </Label>
                      {/* (#4) Chip lý do mẫu. */}
                      <div className="flex flex-wrap gap-1.5">
                        {REASON_CHIPS.map((chip) => (
                          <Button
                            key={chip.label}
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={isPending}
                            onClick={() => setManualReason(chip.value)}
                          >
                            {chip.label}
                          </Button>
                        ))}
                      </div>
                      <Textarea
                        id="manual_reason"
                        value={manualReason}
                        onChange={(e) => setManualReason(e.target.value)}
                        placeholder="Ví dụ: Học bổng theo quyết định số…"
                        rows={2}
                        maxLength={MANUAL_REASON_MAX}
                        disabled={isPending}
                        className="resize-none"
                      />
                      <p
                        className={
                          reasonLen > 0 && reasonLen < MANUAL_REASON_MIN
                            ? "text-destructive text-xs"
                            : "text-muted-foreground text-xs"
                        }
                      >
                        Tối thiểu {MANUAL_REASON_MIN} ký tự, tối đa {MANUAL_REASON_MAX} ({reasonLen}).
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="installment_plan_code">Kế hoạch thanh toán</Label>
              <Select
                value={effectivePlanCode}
                onValueChange={setPlanCode}
                disabled={isPending || plansQuery.isLoading || activePlans.length === 0}
              >
                <SelectTrigger id="installment_plan_code">
                  <SelectValue
                    placeholder={
                      plansQuery.isLoading
                        ? "Đang tải kế hoạch…"
                        : activePlans.length === 0
                        ? "Chưa có kế hoạch nào"
                        : "Chọn kế hoạch"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {activePlans.map((plan) => (
                    <SelectItem key={plan.code} value={plan.code}>
                      {plan.name}
                      <span className="text-muted-foreground ml-2 text-xs">
                        ({plan.code})
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={!canSubmit}>
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Tính học phí
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* (#3) Dialog xác nhận nhập tay — tóm tắt 3 dòng trước khi tạo. */}
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận nhập học phí thủ công</AlertDialogTitle>
            <AlertDialogDescription>
              Kiểm tra lại trước khi tạo bản ghi học phí. Hệ thống sẽ tính
              <strong> số phải thu chính xác</strong> theo chính sách giảm giá
              hiện hành khi tạo — số dưới đây là <strong>ước tính</strong>.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="rounded-lg border p-3 text-sm space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Số gõ (base):</span>
              <span className="font-medium">
                {manualAmount != null ? formatVND(manualAmount) : "—"}
              </span>
            </div>
            {/* Ước tính giảm giá/phải thu CHỈ hiện khi đã có giá chuẩn — tránh
                hiện "0 ₫" gây hiểu nhầm khi preview chưa tải / lỗi. */}
            {currentDiscount != null ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Giảm giá (theo giá chuẩn):</span>
                  <span className="font-medium">{formatVND(currentDiscount)}</span>
                </div>
                <div className="flex items-center justify-between border-t pt-1.5">
                  <span className="text-muted-foreground">Ước tính phải thu:</span>
                  <span className="font-semibold text-primary">
                    {estimatedPayable != null ? formatVND(estimatedPayable) : "—"}
                  </span>
                </div>
              </>
            ) : (
              <div className="border-t pt-1.5 text-muted-foreground text-xs">
                Chưa tải được giá chuẩn — hệ thống sẽ tính số phải thu (theo giảm
                giá hiện hành) khi tạo.
              </div>
            )}
            <div className="border-t pt-1.5">
              <span className="text-muted-foreground">Lý do: </span>
              <span className="break-words">{manualReason.trim()}</span>
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPending}>Quay lại</AlertDialogCancel>
            <AlertDialogAction
              disabled={isPending}
              onClick={(e) => {
                // Đóng AlertDialog (mặc định) rồi submit. doSubmit tự đóng dialog
                // chính khi thành công; lỗi → toast + giữ nguyên giá trị đã nhập.
                e.preventDefault()
                setConfirmOpen(false)
                void doSubmit()
              }}
            >
              {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Xác nhận tạo
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
