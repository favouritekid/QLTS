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
 *    TWO_TERM / QUARTERLY; the dialog no longer guesses codes.
 *
 * Lịch thu "đóng trước" (Pha 1, 2026-06-29):
 *  - Khi loại phí là HỌC PHÍ, có thể bật "Đóng trước theo đợt" để chia
 *    số phải thu thành ĐỢT ĐẦU + PHẦN CÒN LẠI (2 hóa đơn). NGHĨA VỤ
 *    (tổng học phí) KHÔNG đổi — chỉ giãn lịch thu; phần còn lại thành
 *    công nợ có hạn. Khác hẳn "giảm học phí" (sẽ làm ở pha sau).
 *  - useTuitionPreview hiển tổng phải thu (final) để chia + kiểm số
 *    đóng trước < tổng trước khi gửi.
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
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Input } from "@/components/ui/input"
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

export function CalculateFeeDialog({ open, onOpenChange, profileId, onSuccess }: Props) {
  const queryClient = useQueryClient()
  const calculateFee = useCalculateFee()
  const plansQuery = useInstallmentPlans({ enabled: open })

  // Local state — simpler than RHF for a few controlled inputs.
  const [feeType, setFeeType] = useState<FeeType>("tuition")
  const [semesterNo, setSemesterNo] = useState<number>(1)
  const [planCode, setPlanCode] = useState<string>("")

  // Lịch thu "đóng trước" — giãn lịch, KHÔNG đổi tổng học phí.
  const [downPaymentMode, setDownPaymentMode] = useState<boolean>(false)
  const [downPayment, setDownPayment] = useState<number | null>(null)
  const [downPaymentDue, setDownPaymentDue] = useState<string>("")
  const [remainderDue, setRemainderDue] = useState<string>("")

  const activePlans = useMemo(
    () => (plansQuery.data ?? []).filter((p) => p.is_active !== false),
    [plansQuery.data]
  )

  // Derived default plan (no useEffect). Prefer FULL, else first active.
  const effectivePlanCode = useMemo(() => {
    if (planCode) return planCode
    if (activePlans.length === 0) return ""
    return (activePlans.find((p) => p.code === "FULL") ?? activePlans[0]).code
  }, [planCode, activePlans])

  const isTuition = feeType === "tuition"
  const isDownPayment = isTuition && downPaymentMode
  const isPending = calculateFee.isPending

  // Giá chuẩn — chỉ fetch khi bật "đóng trước" để hiển tổng phải thu + chia đợt.
  const preview = useTuitionPreview(profileId, semesterNo, {
    enabled: open && isDownPayment && !!profileId,
  })

  // Tổng PHẢI THU (final) — lịch thu chia con số này (Σ hóa đơn = final − waived;
  // waived=0 lúc tạo). NULL khi preview chưa tải / lỗi (ngành chưa xác định).
  const finalAmount = preview.data ? Number(preview.data.final_amount) : null
  const remainder =
    finalAmount != null && downPayment != null ? finalAmount - downPayment : null

  // Hợp lệ khi: có số đóng trước > 0, có cả 2 hạn, hạn đợt 2 >= đợt 1, VÀ đã biết
  // tổng phải thu (preview.data) với số đóng trước < tổng. Bắt buộc có giá chuẩn:
  // chia "đóng trước" cần biết tổng để tính phần còn lại — nếu preview đang tải /
  // lỗi (ngành chưa xác định), chặn submit thay vì để backend từ chối (400).
  const downPaymentValid =
    downPayment != null &&
    downPayment > 0 &&
    !!downPaymentDue &&
    !!remainderDue &&
    remainderDue >= downPaymentDue &&
    finalAmount != null &&
    downPayment < finalAmount

  const canSubmit =
    !isPending &&
    (isDownPayment
      ? downPaymentValid
      : effectivePlanCode !== "" && activePlans.length > 0)

  const reset = () => {
    setFeeType("tuition")
    setSemesterNo(1)
    setPlanCode("")
    setDownPaymentMode(false)
    setDownPayment(null)
    setDownPaymentDue("")
    setRemainderDue("")
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    await calculateFee.mutateAsync({
      admission_profile_id: profileId,
      fee_type: feeType,
      // Only tuition carries semester_no; backend rejects it for non-tuition.
      semester_no: isTuition ? semesterNo : undefined,
      // Lịch thu "đóng trước" GIỮ tổng học phí — chỉ chia 2 đợt; KHÔNG gửi
      // installment_plan_code (backend bỏ plan ở mode này). Ngược lại gửi plan.
      ...(isDownPayment && downPayment != null
        ? {
            collection_schedule_mode: "down_payment" as const,
            down_payment: String(downPayment),
            down_payment_due: downPaymentDue,
            remainder_due: remainderDue,
          }
        : { installment_plan_code: effectivePlanCode }),
    })

    // useCalculateFee already invalidates finance caches + toasts on success.
    // Extend to admission caches + dashboard so the Tuition tab refreshes.
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

  return (
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
              onValueChange={(v) => {
                const next = v as FeeType
                setFeeType(next)
                // Lịch "đóng trước" chỉ cho tuition → đổi sang loại phí khác thì
                // tắt + xóa luôn để toggle không kẹt "bật" khi quay lại tuition.
                if (next !== "tuition") {
                  setDownPaymentMode(false)
                  setDownPayment(null)
                  setDownPaymentDue("")
                  setRemainderDue("")
                }
              }}
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

          {/* Toggle "đóng trước theo đợt" — chỉ cho học phí. */}
          {isTuition && (
            <div className="rounded-lg border p-3 space-y-3">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="down_payment_mode" className="cursor-pointer">
                    Đóng trước theo đợt
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    Chia số phải thu thành đợt đầu + phần còn lại (giữ nguyên tổng
                    học phí). Phần còn lại thành công nợ có hạn.
                  </p>
                </div>
                <Switch
                  id="down_payment_mode"
                  checked={downPaymentMode}
                  onCheckedChange={setDownPaymentMode}
                  disabled={isPending}
                />
              </div>

              {isDownPayment && (
                <div className="space-y-3 pt-1">
                  {/* Tổng phải thu (final) để người dùng chia đợt. */}
                  <div className="text-xs">
                    {preview.isLoading && (
                      <p className="text-muted-foreground">Đang tải tổng phải thu…</p>
                    )}
                    {preview.isError && (
                      <p className="text-destructive">
                        Không tải được giá chuẩn (hồ sơ có thể chưa xác định ngành).
                      </p>
                    )}
                    {preview.data && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Tổng phải thu:</span>
                        <span className="font-semibold text-primary">
                          {formatVND(preview.data.final_amount)}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="down_payment">
                      Số đóng đợt đầu <span className="text-destructive">*</span>
                    </Label>
                    <CurrencyInput
                      id="down_payment"
                      value={downPayment}
                      onChange={setDownPayment}
                      placeholder="Nhập số tiền đóng trước…"
                      disabled={isPending}
                    />
                    {remainder != null && (
                      <p
                        className={
                          remainder <= 0
                            ? "text-destructive text-xs"
                            : "text-muted-foreground text-xs"
                        }
                      >
                        {remainder > 0
                          ? `Phần còn lại (công nợ): ${formatVND(remainder)}`
                          : "Số đóng trước phải nhỏ hơn tổng phải thu."}
                      </p>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="down_payment_due">
                        Hạn đợt đầu <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="down_payment_due"
                        type="date"
                        value={downPaymentDue}
                        onChange={(e) => setDownPaymentDue(e.target.value)}
                        disabled={isPending}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="remainder_due">
                        Hạn phần còn lại <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="remainder_due"
                        type="date"
                        value={remainderDue}
                        onChange={(e) => setRemainderDue(e.target.value)}
                        disabled={isPending}
                      />
                    </div>
                  </div>
                  {!!downPaymentDue &&
                    !!remainderDue &&
                    remainderDue < downPaymentDue && (
                      <p className="text-destructive text-xs">
                        Hạn phần còn lại phải sau hoặc bằng hạn đợt đầu.
                      </p>
                    )}
                </div>
              )}
            </div>
          )}

          {/* Kế hoạch thanh toán — ẩn khi chia "đóng trước" (dùng lịch tùy chỉnh). */}
          {!isDownPayment && (
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
          )}

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
  )
}
