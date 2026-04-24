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
 * Scope decisions (PR #7):
 *  - Controlled dialog (parent owns `open` state) so the trigger can
 *    live in the StatCard area of TuitionTab.
 *  - React-Hook-Form + Zod for parity with other admission dialogs.
 *  - Success path invalidates admission detail + finance caches so
 *    the just-calculated fee appears immediately in the current tab.
 */
import { useMemo } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
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
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { financeDashboardKeys } from "@/hooks/finance/useFinanceDashboard"

// Inline dialog schema — narrower than the backend FeeCalculateRequest
// because `admission_profile_id` is provided by the caller.
const schema = z.object({
  fee_type: z.enum(["tuition", "application", "dormitory", "other"]).default("tuition"),
  semester_no: z.coerce.number().int().min(1).max(12).default(1),
  installment_plan_code: z.enum(["FULL", "INSTALLMENT"]).default("FULL"),
})

type FormValues = z.infer<typeof schema>

interface Props {
  open: boolean
  onOpenChange: (next: boolean) => void
  profileId: number
}

export function CalculateFeeDialog({ open, onOpenChange, profileId }: Props) {
  const queryClient = useQueryClient()
  const calculateFee = useCalculateFee()

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      fee_type: "tuition",
      semester_no: 1,
      installment_plan_code: "FULL",
    },
  })

  const isTuition = form.watch("fee_type") === "tuition"
  const isPending = calculateFee.isPending

  const onSubmit = form.handleSubmit(async (values) => {
    await calculateFee.mutateAsync({
      admission_profile_id: profileId,
      fee_type: values.fee_type,
      // Only tuition uses semester_no; normalise to undefined for the rest
      // so the backend's validate_semester discriminator stays happy.
      semester_no: values.fee_type === "tuition" ? values.semester_no : undefined,
      installment_plan_code: values.installment_plan_code,
    })

    // useCalculateFee already invalidates finance caches + toasts on
    // success. Extend to the admission detail + finance dashboard so
    // the current tab + overview cards refresh without a reload.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: admissionsKeys.detail(profileId) }),
      queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() }),
      queryClient.invalidateQueries({ queryKey: feesKeys.lists() }),
      queryClient.invalidateQueries({ queryKey: feesKeys.byProfile(profileId) }),
      queryClient.invalidateQueries({ queryKey: feesKeys.profileSummary(profileId) }),
      queryClient.invalidateQueries({ queryKey: financeDashboardKeys.all }),
    ])

    form.reset()
    onOpenChange(false)
  })

  // Semester dropdown — keep the default 1..3 visible; backend supports
  // higher numbers but the UI defers that until semester-tuition config
  // exposes per-path semester counts.
  const semesterOptions = useMemo(
    () => [
      { value: 1, label: "Học kỳ 1" },
      { value: 2, label: "Học kỳ 2" },
      { value: 3, label: "Học kỳ 3+" },
    ],
    []
  )

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

        <form onSubmit={onSubmit} className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="fee_type">Loại phí</Label>
            <Select
              value={form.watch("fee_type")}
              onValueChange={(v) => form.setValue("fee_type", v as FormValues["fee_type"])}
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
                value={String(form.watch("semester_no"))}
                onValueChange={(v) => form.setValue("semester_no", parseInt(v, 10))}
                disabled={isPending}
              >
                <SelectTrigger id="semester_no">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {semesterOptions.map((opt) => (
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
              value={form.watch("installment_plan_code")}
              onValueChange={(v) =>
                form.setValue("installment_plan_code", v as FormValues["installment_plan_code"])
              }
              disabled={isPending}
            >
              <SelectTrigger id="installment_plan_code">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="FULL">Thanh toán một lần</SelectItem>
                <SelectItem value="INSTALLMENT">Trả góp nhiều đợt</SelectItem>
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
            <Button type="submit" disabled={isPending}>
              {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Tính học phí
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
