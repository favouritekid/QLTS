// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/InvoicePenaltyDialog.tsx
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
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { CurrencyInput } from "@/components/ui/currency-input"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useApplyPenalty } from "@/hooks/finance/useInvoices"
import { toast } from "sonner"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const penaltyFormSchema = z.object({
  penalty_amount: z
    .number({ message: "Vui lòng nhập số tiền phạt" })
    .positive("Số tiền phải lớn hơn 0"),
  reason: z
    .string()
    .max(500, "Lý do không được quá 500 ký tự")
    .optional(),
})

type PenaltyFormValues = z.infer<typeof penaltyFormSchema>

// =============================================================================
// TYPES
// =============================================================================

interface InvoicePenaltyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  invoiceNumber: string
  feeId: number
  daysOverdue?: number
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * InvoicePenaltyDialog - Dialog to apply late payment penalty to an invoice
 *
 * @example
 * ```tsx
 * <InvoicePenaltyDialog
 *   open={isOpen}
 *   onOpenChange={setIsOpen}
 *   invoiceId={123}
 *   invoiceNumber="INV-2024-001"
 *   feeId={456}
 *   daysOverdue={15}
 * />
 * ```
 */
export function InvoicePenaltyDialog({
  open,
  onOpenChange,
  invoiceId,
  invoiceNumber,
  feeId,
  daysOverdue,
}: InvoicePenaltyDialogProps) {
  const penaltyMutation = useApplyPenalty()

  const form = useForm<PenaltyFormValues>({
    resolver: zodResolver(penaltyFormSchema),
    defaultValues: {
      penalty_amount: undefined,
      reason: "",
    },
  })

  const onSubmit = async (values: PenaltyFormValues) => {
    try {
      await penaltyMutation.mutateAsync({
        invoiceId,
        feeId,
        data: {
          penalty_amount: values.penalty_amount.toString(),
          reason: values.reason || undefined,
        },
      })
      toast.success("Đã áp dụng phí trễ hạn thành công")
      form.reset()
      onOpenChange(false)
    } catch (error) {
      // Error handled by mutation hook
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
            <AlertTriangle className="h-5 w-5 text-warning-600" />
            Áp dụng phí trễ hạn
          </DialogTitle>
          <DialogDescription>
            Áp dụng phí trễ hạn cho hóa đơn <strong className="font-mono">{invoiceNumber}</strong>
            {daysOverdue !== undefined && daysOverdue > 0 && (
              <span className="block mt-1 text-destructive">
                Quá hạn {daysOverdue} ngày
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="penalty_amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Số tiền phạt <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <CurrencyInput
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Nhập số tiền phạt..."
                      className="h-11"
                    />
                  </FormControl>
                  <FormDescription>
                    Số tiền phạt sẽ được cộng vào tổng tiền hóa đơn
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
                  <FormLabel>Lý do (tùy chọn)</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Ví dụ: Quá hạn 15 ngày theo quy định..."
                      rows={2}
                      className="resize-none"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={penaltyMutation.isPending}
              >
                Hủy
              </Button>
              <Button
                type="submit"
                disabled={penaltyMutation.isPending}
                className="bg-warning-600 hover:bg-warning-700 text-white"
              >
                {penaltyMutation.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                Áp dụng phí trễ hạn
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default InvoicePenaltyDialog
