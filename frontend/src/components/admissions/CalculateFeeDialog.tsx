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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { useCalculateFee, feesKeys } from "@/hooks/finance/useFees"
import { useInstallmentPlans } from "@/hooks/finance/useInstallmentPlans"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { financeDashboardKeys } from "@/hooks/finance/useFinanceDashboard"

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

  // Local state — simpler than RHF for 3 controlled selects and avoids
  // the strict-tsc friction with zod `z.coerce` + `.default()` generics.
  const [feeType, setFeeType] = useState<FeeType>("tuition")
  const [semesterNo, setSemesterNo] = useState<number>(1)
  const [planCode, setPlanCode] = useState<string>("")

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
  const isPending = calculateFee.isPending
  const canSubmit = effectivePlanCode !== "" && !isPending && activePlans.length > 0

  const reset = () => {
    setFeeType("tuition")
    setSemesterNo(1)
    setPlanCode("")
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    await calculateFee.mutateAsync({
      admission_profile_id: profileId,
      fee_type: feeType,
      // Only tuition carries semester_no; backend validator rejects it
      // for non-tuition fee types, so omit entirely when switching away.
      semester_no: isTuition ? semesterNo : undefined,
      installment_plan_code: effectivePlanCode,
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
  )
}
