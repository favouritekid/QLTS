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
import { Button } from "@/components/ui/button"
import { CurrencyInput } from "@/components/ui/currency-input"
import { Textarea } from "@/components/ui/textarea"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useApplyPenalty } from "@/hooks/finance/useInvoices"
import { toast } from "sonner"

const penaltyFormSchema = z.object({
  penalty_amount: z
    .number({ message: "Vui lòng nhập số tiền phạt" })
    .positive("Số tiền phải lớn hơn 0"),
  // Backend route apply-penalty yêu cầu reason (1..500). Không gửi → 422.
  reason: z
    .string()
    .min(1, "Vui lòng nhập lý do áp phạt")
    .max(500, "Lý do không được quá 500 ký tự"),
})

type PenaltyFormValues = z.infer<typeof penaltyFormSchema>

interface InvoicePenaltyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  invoiceNumber: string
  feeId: number
  daysOverdue?: number
}

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
          reason: values.reason.trim(),
        },
      })
      toast.success("Đã áp dụng phí trễ hạn thành công")
      form.reset()
      onOpenChange(false)
    } catch {
      // Error handled by mutation hook
    }
  }

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
              <span className="mt-1 block text-destructive">Quá hạn {daysOverdue} ngày</span>
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
                  <FormDescription>Số tiền phạt sẽ được cộng vào tổng tiền hóa đơn (không vượt số tiền hóa đơn)</FormDescription>
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
                    Lý do <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Ví dụ: Phạt trễ hạn theo quy định..."
                      rows={2}
                      maxLength={500}
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
                className="bg-warning-600 text-white hover:bg-warning-700"
              >
                {penaltyMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
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
