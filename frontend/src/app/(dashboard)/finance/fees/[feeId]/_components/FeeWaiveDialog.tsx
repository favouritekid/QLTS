// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeWaiveDialog.tsx
"use client"

import * as React from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
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
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { CurrencyInput } from "@/components/ui/currency-input"
import { Percent, Loader2 } from "lucide-react"
import { useWaiveFee } from "@/hooks/finance/useFees"
import { toast } from "sonner"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const waiveFormSchema = z.object({
  waive_amount: z
    .number({ message: "Vui lòng nhập số tiền miễn giảm" })
    .positive("Số tiền phải lớn hơn 0"),
  reason: z
    .string()
    .min(10, "Lý do phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

type WaiveFormValues = z.infer<typeof waiveFormSchema>

// =============================================================================
// TYPES
// =============================================================================

interface FeeWaiveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  feeId: number
  maxAmount: string          // raw string, e.g. "5000000.00"
  maxAmountFormatted: string // display string, e.g. "5.000.000 ₫"
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeWaiveDialog - Dialog to waive (reduce) a fee amount
 *
 */
export function FeeWaiveDialog({
  open,
  onOpenChange,
  feeId,
  maxAmount,
  maxAmountFormatted,
}: FeeWaiveDialogProps) {
  const waiveMutation = useWaiveFee()

  const form = useForm<WaiveFormValues>({
    resolver: zodResolver(waiveFormSchema),
    defaultValues: {
      waive_amount: undefined,
      reason: "",
    },
  })

  const maxAmountNum = parseFloat(maxAmount) || 0

  const onSubmit = async (values: WaiveFormValues) => {
    if (values.waive_amount > maxAmountNum) {
      form.setError("waive_amount", {
        type: "manual",
        message: "Số tiền miễn giảm không được vượt quá số dư còn lại",
      })
      return
    }
    form.clearErrors("waive_amount")
    try {
      await waiveMutation.mutateAsync({
        feeId,
        data: {
          waive_amount: values.waive_amount.toString(),
          reason: values.reason,
        },
      })
      toast.success("Đã miễn giảm thành công")
      form.reset()
      onOpenChange(false)
    } catch (error) {
      // Error toast is handled by the mutation hook
    }
  }

  // Reset form when dialog closes
  React.useEffect(() => {
    if (!open) {
      form.reset()
    }
  }, [open, form])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Percent className="h-5 w-5" />
            Miễn giảm học phí
          </DialogTitle>
          <DialogDescription>
            Nhập số tiền và lý do miễn giảm. Số tiền tối đa có thể miễn giảm: {maxAmountFormatted}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="waive_amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Số tiền miễn giảm <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <CurrencyInput
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Nhập số tiền..."
                      className="h-11"
                    />
                  </FormControl>
                  <FormDescription>
                    Số tiền còn lại: {maxAmountFormatted}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Lý do miễn giảm <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Nhập lý do miễn giảm (ví dụ: Học bổng, Hoàn cảnh khó khăn...)"
                      rows={3}
                      className="resize-none"
                    />
                  </FormControl>
                  <FormDescription>
                    Tối thiểu 10 ký tự, tối đa 500 ký tự
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
                disabled={waiveMutation.isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={waiveMutation.isPending}>
                {waiveMutation.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                Xác nhận miễn giảm
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default FeeWaiveDialog
