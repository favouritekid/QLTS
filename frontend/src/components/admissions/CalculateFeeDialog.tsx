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
import { Textarea } from "@/components/ui/textarea"
import { CurrencyInput } from "@/components/ui/currency-input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { useAuth } from "@/hooks/useAuth"
import { useCalculateFee, useTuitionPreview, feesKeys } from "@/hooks/finance/useFees"
import { useInstallmentPlans } from "@/hooks/finance/useInstallmentPlans"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { financeDashboardKeys } from "@/hooks/finance/useFinanceDashboard"
import { formatVND } from "@/lib/zod/finance"

const DISCOUNT_REASON_MIN = 10
const DISCOUNT_REASON_MAX = 500
// Vai trò được miễn/giảm học phí (giảm NGHĨA VỤ tiền). UX-gating; backend enforce
// 403 ở route (field-level authz). Cùng tinh thần AdvancedTab (user.role + server
// enforce) — dialog Tính phí chưa có resource để gắn cờ permission API.
const FINANCE_ADJUST_ROLES = ["admin", "manager", "accountant"]

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
  const { user } = useAuth()
  const calculateFee = useCalculateFee()
  const plansQuery = useInstallmentPlans({ enabled: open })

  // Quyền miễn/giảm học phí (UX-gating — backend enforce 403). Chỉ tài chính.
  const canManualDiscount = !!user && FINANCE_ADJUST_ROLES.includes(user.role)

  // Local state — simpler than RHF for a few controlled inputs.
  const [feeType, setFeeType] = useState<FeeType>("tuition")
  const [semesterNo, setSemesterNo] = useState<number>(1)
  const [planCode, setPlanCode] = useState<string>("")

  // Lịch thu "đóng trước" — giãn lịch, KHÔNG đổi tổng học phí.
  const [downPaymentMode, setDownPaymentMode] = useState<boolean>(false)
  const [downPayment, setDownPayment] = useState<number | null>(null)
  const [downPaymentDue, setDownPaymentDue] = useState<string>("")
  const [remainderDue, setRemainderDue] = useState<string>("")

  // Miễn/giảm học phí THẬT — GIẢM nghĩa vụ (final). Loại trừ lẫn nhau với
  // "đóng trước" (mỗi lần chỉ 1; có thể kết hợp ở thao tác sau).
  const [discountMode, setDiscountMode] = useState<boolean>(false)
  const [targetFinal, setTargetFinal] = useState<number | null>(null)
  const [discountReason, setDiscountReason] = useState<string>("")

  // Ưu đãi theo CHÍNH SÁCH của ngành. null = chưa đụng vào ⇒ để backend áp toàn
  // bộ cấu hình (hành vi cũ). Mảng = lựa chọn tường minh, KỂ CẢ mảng rỗng
  // ("không áp ưu đãi nào"). Officer/kế toán chỉ chọn được trong tập cấu hình —
  // server là hàng rào thật, đây chỉ là giao diện.
  const [selectedPolicyIds, setSelectedPolicyIds] = useState<number[] | null>(null)

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
  const isDiscount = isTuition && canManualDiscount && discountMode
  const isPending = calculateFee.isPending

  // Giá chuẩn + danh sách ưu đãi của ngành. Fetch cho MỌI khoản học phí (không
  // chỉ khi bật "đóng trước"/"miễn giảm") vì ưu đãi là thứ người dùng cần thấy
  // trước khi bấm Tính phí — và con số phải thu phải phản ánh đúng ô đang tích.
  const preview = useTuitionPreview(profileId, semesterNo, {
    enabled: open && isTuition && !!profileId,
    discountPolicyIds: selectedPolicyIds ?? undefined,
  })

  // Danh sách ưu đãi đã cấu hình cho ngành. Cờ selectable/lý do do SERVER tính
  // bằng chính predicate của luồng thu thật — FE không tự suy theo ngày/cờ.
  const policyOptions = preview.data?.discount_policies ?? []
  const selectablePolicies = policyOptions.filter((p) => p.selectable)
  // Tập đang áp: chưa đụng vào ⇒ theo server trả về (mặc định cấu hình).
  const effectiveSelectedIds =
    selectedPolicyIds ??
    policyOptions.filter((p) => p.selected).map((p) => p.id)

  const togglePolicy = (id: number, checked: boolean) => {
    const base = effectiveSelectedIds
    setSelectedPolicyIds(
      checked ? [...base, id] : base.filter((pid) => pid !== id)
    )
  }

  // Mức PHẢI THU hiện hành (final = base − giảm policy) — "đóng trước" chia con số
  // này; "miễn/giảm" yêu cầu target NHỎ HƠN nó. NULL khi preview chưa tải / lỗi.
  const finalAmount = preview.data ? Number(preview.data.final_amount) : null
  const remainder =
    finalAmount != null && downPayment != null ? finalAmount - downPayment : null

  // Đóng trước hợp lệ: có số > 0, đủ 2 hạn, hạn đợt 2 >= đợt 1, và đã biết mức phải
  // thu (preview) với số đóng trước < mức đó. Chặn submit nếu preview chưa có.
  const downPaymentValid =
    downPayment != null &&
    downPayment > 0 &&
    !!downPaymentDue &&
    !!remainderDue &&
    remainderDue >= downPaymentDue &&
    finalAmount != null &&
    downPayment < finalAmount

  // Mức giảm tay (hiển thị) = mức-sau-giảm-policy − học-phí-áp-dụng.
  const manualReduction =
    finalAmount != null && targetFinal != null ? finalAmount - targetFinal : null

  // Miễn/giảm hợp lệ: target >= 0, biết mức phải thu (preview), target < mức đó
  // (phải thực sự giảm), lý do >= min. Bắt buộc có preview để biết mức nền.
  const discountReasonLen = discountReason.trim().length
  const discountValid =
    targetFinal != null &&
    targetFinal >= 0 &&
    finalAmount != null &&
    targetFinal < finalAmount &&
    discountReasonLen >= DISCOUNT_REASON_MIN &&
    discountReasonLen <= DISCOUNT_REASON_MAX

  const scheduleValid = isDownPayment
    ? downPaymentValid
    : effectivePlanCode !== "" && activePlans.length > 0

  const canSubmit = !isPending && scheduleValid && (!isDiscount || discountValid)

  const reset = () => {
    setFeeType("tuition")
    setSemesterNo(1)
    setPlanCode("")
    setDownPaymentMode(false)
    setDownPayment(null)
    setDownPaymentDue("")
    setRemainderDue("")
    setDiscountMode(false)
    setTargetFinal(null)
    setDiscountReason("")
    setSelectedPolicyIds(null)
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
      // Miễn/giảm học phí THẬT (GIẢM nghĩa vụ) — "Học phí áp dụng" = final sau MỌI
      // giảm. Chỉ gửi khi bật + có quyền (backend cũng enforce 403).
      ...(isDiscount && targetFinal != null
        ? {
            target_final_amount: String(targetFinal),
            manual_discount_reason: discountReason.trim(),
          }
        : {}),
      // Ưu đãi theo chính sách: CHỈ gửi khi người dùng thực sự đụng vào ô tích.
      // Không đụng ⇒ bỏ field ⇒ backend áp toàn bộ cấu hình như trước.
      ...(isTuition && selectedPolicyIds !== null
        ? { discount_policy_ids: selectedPolicyIds }
        : {}),
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
                // Đóng trước / miễn-giảm chỉ cho tuition → đổi sang loại phí khác
                // thì tắt + xóa để toggle không kẹt "bật" khi quay lại tuition.
                if (next !== "tuition") {
                  setDownPaymentMode(false)
                  setDownPayment(null)
                  setDownPaymentDue("")
                  setRemainderDue("")
                  setDiscountMode(false)
                  setTargetFinal(null)
                  setDiscountReason("")
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

          {/* Ưu đãi theo CHÍNH SÁCH đã cấu hình cho ngành. Chỉ hiện khi ngành có
              cấu hình — trường chưa gắn ưu đãi nào thì đừng thêm ô trống gây rối.
              Ô tích không chọn được kèm LÝ DO (server trả), vì "ưu đãi có mà
              không bấm được" là câu hỏi kế toán sẽ hỏi ngay. */}
          {isTuition && policyOptions.length > 0 && (
            <div className="rounded-lg border p-3 space-y-2">
              <div className="space-y-0.5">
                <Label>Ưu đãi học phí</Label>
                <p className="text-muted-foreground text-xs">
                  Chỉ chọn được trong danh sách đã cấu hình cho ngành này.
                </p>
              </div>

              <div className="space-y-2 pt-1">
                {policyOptions.map((policy) => {
                  const checked = effectiveSelectedIds.includes(policy.id)
                  return (
                    <div key={policy.id} className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        id={`discount_policy_${policy.id}`}
                        className="mt-1 size-4 shrink-0 accent-primary disabled:opacity-50"
                        checked={policy.selectable && checked}
                        disabled={isPending || !policy.selectable}
                        onChange={(e) => togglePolicy(policy.id, e.target.checked)}
                      />
                      <div className="min-w-0 flex-1">
                        <Label
                          htmlFor={`discount_policy_${policy.id}`}
                          className={
                            policy.selectable
                              ? "cursor-pointer text-sm font-normal"
                              : "text-muted-foreground text-sm font-normal"
                          }
                        >
                          {policy.name}
                          {policy.selectable && (
                            <span className="text-primary ml-1 font-medium">
                              −{formatVND(policy.amount)}
                            </span>
                          )}
                        </Label>
                        {!policy.selectable && policy.reason_text && (
                          <p className="text-muted-foreground text-xs">
                            {policy.reason_text}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {preview.data && (
                <div className="border-t pt-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Giá chuẩn:</span>
                    <span>{formatVND(preview.data.base_amount)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Tổng ưu đãi:</span>
                    <span>−{formatVND(preview.data.total_discount)}</span>
                  </div>
                  <div className="flex items-center justify-between font-semibold">
                    <span>Phải thu:</span>
                    <span className="text-primary">
                      {formatVND(preview.data.final_amount)}
                    </span>
                  </div>
                </div>
              )}
              {selectablePolicies.length === 0 && (
                <p className="text-muted-foreground text-xs">
                  Không có ưu đãi nào áp dụng được cho hồ sơ này ở thời điểm hiện tại.
                </p>
              )}
            </div>
          )}

          {/* Toggle "đóng trước theo đợt" — chỉ cho học phí; ẩn khi đang miễn/giảm
              (loại trừ lẫn nhau để tránh nhập nhằng mức nền). */}
          {isTuition && !discountMode && (
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

          {/* Miễn/giảm học phí THẬT — GIẢM nghĩa vụ. Chỉ admin/manager/accountant
              (UX-gating; backend enforce 403). Ẩn khi đang "đóng trước". */}
          {isTuition && canManualDiscount && !downPaymentMode && (
            <div className="rounded-lg border p-3 space-y-3">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="discount_mode" className="cursor-pointer">
                    Miễn/giảm học phí
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    Đặt mức học phí áp dụng thấp hơn (học bổng / chuyển trường / theo
                    quyết định). GIẢM tổng nghĩa vụ — khác với đóng trước.
                  </p>
                </div>
                <Switch
                  id="discount_mode"
                  checked={discountMode}
                  onCheckedChange={setDiscountMode}
                  disabled={isPending}
                />
              </div>

              {isDiscount && (
                <div className="space-y-3 pt-1">
                  <div className="text-xs">
                    {preview.isLoading && (
                      <p className="text-muted-foreground">Đang tải mức phải thu…</p>
                    )}
                    {preview.isError && (
                      <p className="text-destructive">
                        Không tải được giá chuẩn (hồ sơ có thể chưa xác định ngành).
                      </p>
                    )}
                    {preview.data && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Mức phải thu hiện hành:
                        </span>
                        <span className="font-medium">
                          {formatVND(preview.data.final_amount)}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="target_final_amount">
                      Học phí áp dụng <span className="text-destructive">*</span>
                    </Label>
                    <CurrencyInput
                      id="target_final_amount"
                      value={targetFinal}
                      onChange={setTargetFinal}
                      placeholder="Mức học phí sau miễn/giảm…"
                      disabled={isPending}
                    />
                    {manualReduction != null && (
                      <p
                        className={
                          manualReduction <= 0
                            ? "text-destructive text-xs"
                            : "text-muted-foreground text-xs"
                        }
                      >
                        {manualReduction > 0
                          ? `Mức giảm: ${formatVND(manualReduction)}`
                          : "Học phí áp dụng phải nhỏ hơn mức phải thu hiện hành."}
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="discount_reason">
                      Lý do <span className="text-destructive">*</span>
                    </Label>
                    <Textarea
                      id="discount_reason"
                      value={discountReason}
                      onChange={(e) => setDiscountReason(e.target.value)}
                      placeholder="Ví dụ: Học bổng theo quyết định số…"
                      rows={2}
                      maxLength={DISCOUNT_REASON_MAX}
                      disabled={isPending}
                      className="resize-none"
                    />
                    <p
                      className={
                        discountReasonLen > 0 && discountReasonLen < DISCOUNT_REASON_MIN
                          ? "text-destructive text-xs"
                          : "text-muted-foreground text-xs"
                      }
                    >
                      Tối thiểu {DISCOUNT_REASON_MIN} ký tự, tối đa {DISCOUNT_REASON_MAX} ({discountReasonLen}).
                    </p>
                  </div>
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
