// src/app/(dashboard)/finance/fees/[feeId]/_components/FeeRecalculateDialog.tsx
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
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react"
import { useRecalculateFee } from "@/hooks/finance/useFees"
import { toast } from "sonner"

const recalculateFormSchema = z.object({
  new_base_amount: z
    .number({ message: "Vui lòng nhập mức phí gốc mới" })
    .positive("Mức phí gốc phải lớn hơn 0"),
  reason: z
    .string()
    .min(10, "Lý do tính lại phải có ít nhất 10 ký tự")
    .max(500, "Lý do không được quá 500 ký tự"),
})

type RecalculateFormValues = z.infer<typeof recalculateFormSchema>

interface FeeRecalculateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  feeId: number
  feeType: string
  currentBaseAmount: string
  currentBaseAmountFormatted: string
}

export function FeeRecalculateDialog({
  open,
  onOpenChange,
  feeId,
  feeType,
  currentBaseAmount,
  currentBaseAmountFormatted,
}: FeeRecalculateDialogProps) {
  const recalculateMutation = useRecalculateFee()
  const currentBaseAmountNumber = parseFloat(currentBaseAmount) || 0

  const form = useForm<RecalculateFormValues>({
    resolver: zodResolver(recalculateFormSchema),
    defaultValues: {
      new_base_amount: currentBaseAmountNumber || undefined,
      reason: "",
    },
  })

  React.useEffect(() => {
    form.reset({
      new_base_amount: currentBaseAmountNumber || undefined,
      reason: "",
    })
  }, [currentBaseAmountNumber, form, open])

  const onSubmit = async (values: RecalculateFormValues) => {
    try {
      await recalculateMutation.mutateAsync({
        feeId,
        data: {
          new_base_amount: values.new_base_amount.toString(),
          reason: values.reason.trim(),
        },
      })
      toast.success("Đã tính lại phí thành công")
      onOpenChange(false)
    } catch {
      // Error handled by mutation hook
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5" />
            Tính lại học phí
          </DialogTitle>
          <DialogDescription>
            Cập nhật mức phí gốc và lý do để tính lại khoản <strong>{feeType}</strong>.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-warning-200 bg-warning-50 p-3 text-sm text-warning-900">
          <div className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning-600" />
            <div className="space-y-1">
              <p className="font-medium">Lưu ý quan trọng:</p>
              <p>Mức phí gốc hiện tại: {currentBaseAmountFormatted}</p>
              <p>Hệ thống sẽ tính lại giảm giá và có thể tạo lại các hóa đơn chưa thanh toán.</p>
            </div>
          </div>
        </div>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="new_base_amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Mức phí gốc mới <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <CurrencyInput
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Nhập mức phí gốc..."
                      className="h-11"
                    />
                  </FormControl>
                  <FormDescription>Giá trị mặc định đang lấy theo mức phí gốc hiện tại.</FormDescription>
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
                    Lý do tính lại <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Ví dụ: Cập nhật lại mức phí gốc theo quyết định mới..."
                      rows={3}
                      className="resize-none"
                    />
                  </FormControl>
                  <FormDescription>Tối thiểu 10 ký tự, tối đa 500 ký tự.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={recalculateMutation.isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={recalculateMutation.isPending}>
                {recalculateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Tính lại
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default FeeRecalculateDialog
