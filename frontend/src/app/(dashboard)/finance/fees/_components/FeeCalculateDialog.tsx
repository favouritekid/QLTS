// src/app/(dashboard)/finance/fees/_components/FeeCalculateDialog.tsx
"use client"

import * as React from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { useRouter } from "next/navigation"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Calculator, Loader2 } from "lucide-react"
import { useCalculateFee } from "@/hooks/finance/useFees"
import { useInstallmentPlans } from "@/hooks/finance/useInstallmentPlans"
import { FEE_TYPE_LABELS, type FeeType } from "@/types/finance.types"
import { toast } from "sonner"

// Radix Select forbids value="" on SelectItem — use sentinel internally
const RADIX_NONE = "__radix_none__"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const calculateFormSchema = z.object({
  admission_profile_id: z
    .number({ message: "Vui lòng nhập ID hồ sơ" })
    .positive("ID hồ sơ phải lớn hơn 0"),
  fee_type: z.enum(["tuition", "application", "enrollment", "insurance", "dormitory", "other"] as const, {
    message: "Vui lòng chọn loại phí",
  }),
  installment_plan_code: z.string().optional(),
})

type CalculateFormValues = z.infer<typeof calculateFormSchema>

// =============================================================================
// TYPES
// =============================================================================

interface FeeCalculateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultProfileId?: number
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeCalculateDialog - Dialog to calculate a new fee for an admission profile
 *
 * @example
 * ```tsx
 * <FeeCalculateDialog
 *   open={isOpen}
 *   onOpenChange={setIsOpen}
 *   defaultProfileId={123}
 * />
 * ```
 */
export function FeeCalculateDialog({
  open,
  onOpenChange,
  defaultProfileId,
}: FeeCalculateDialogProps) {
  const router = useRouter()
  const calculateMutation = useCalculateFee()
  const { data: installmentPlans, isLoading: plansLoading } = useInstallmentPlans()

  const activePlans = React.useMemo(() => {
    return installmentPlans?.filter((p) => p.is_active) || []
  }, [installmentPlans])

  const form = useForm<CalculateFormValues>({
    resolver: zodResolver(calculateFormSchema),
    defaultValues: {
      admission_profile_id: defaultProfileId ?? undefined,
      fee_type: "tuition",
      installment_plan_code: RADIX_NONE,
    },
  })

  // Update profile ID when defaultProfileId changes
  React.useEffect(() => {
    if (defaultProfileId) {
      form.setValue("admission_profile_id", defaultProfileId)
    }
  }, [defaultProfileId, form])

  const onSubmit = async (values: CalculateFormValues) => {
    try {
      const result = await calculateMutation.mutateAsync({
        admission_profile_id: values.admission_profile_id,
        fee_type: values.fee_type,
        installment_plan_code: values.installment_plan_code === RADIX_NONE ? undefined : values.installment_plan_code || undefined,
      })
      toast.success("Đã tính phí thành công")
      form.reset()
      onOpenChange(false)
      // Navigate to the new fee detail
      router.push(`/finance/fees/${result.id}`)
    } catch (error) {
      // Error handled by mutation hook
    }
  }

  // Reset form when dialog closes
  React.useEffect(() => {
    if (!open) {
      form.reset({
        admission_profile_id: defaultProfileId ?? undefined,
        fee_type: "tuition",
        installment_plan_code: RADIX_NONE,
      })
    }
  }, [open, form, defaultProfileId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Calculator className="h-5 w-5" />
            Tính phí mới
          </DialogTitle>
          <DialogDescription>
            Tính phí cho hồ sơ tuyển sinh đã được duyệt. Hệ thống sẽ tự động áp dụng các chính sách giảm giá phù hợp.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Profile ID */}
            <FormField
              control={form.control}
              name="admission_profile_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    ID Hồ sơ tuyển sinh <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      {...field}
                      onChange={(e) => field.onChange(parseInt(e.target.value) || undefined)}
                      placeholder="Nhập ID hồ sơ..."
                      className="h-11"
                    />
                  </FormControl>
                  <FormDescription>
                    ID của hồ sơ tuyển sinh đã được duyệt (approved)
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Fee Type */}
            <FormField
              control={form.control}
              name="fee_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Loại phí <span className="text-destructive">*</span>
                  </FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn loại phí..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(Object.entries(FEE_TYPE_LABELS) as [FeeType, string][]).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Installment Plan */}
            <FormField
              control={form.control}
              name="installment_plan_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Kế hoạch trả góp</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={plansLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        {plansLoading ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Đang tải…
                          </span>
                        ) : (
                          <SelectValue placeholder="Chọn kế hoạch (mặc định: Thanh toán 1 lần)" />
                        )}
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value={RADIX_NONE}>Thanh toán 1 lần (mặc định)</SelectItem>
                      {activePlans.map((plan) => (
                        <SelectItem key={plan.id} value={plan.code}>
                          {plan.name} ({plan.installment_count} đợt)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Kế hoạch phân kỳ thanh toán cho học phí
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={calculateMutation.isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={calculateMutation.isPending}>
                {calculateMutation.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                Tính phí
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default FeeCalculateDialog
