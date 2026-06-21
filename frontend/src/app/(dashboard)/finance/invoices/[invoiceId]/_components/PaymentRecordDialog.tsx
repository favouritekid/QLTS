// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/PaymentRecordDialog.tsx
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { CurrencyInput } from "@/components/ui/currency-input"
import { DatePicker } from "@/components/common/form/DatePicker"
import { CreditCard, Loader2 } from "lucide-react"
import { useCreatePayment } from "@/hooks/finance/usePayments"
import { usePaymentMethods } from "@/hooks/finance/usePaymentMethods"
import { parseVNDDisplayAmount } from "@/lib/zod/finance"
import { toast } from "sonner"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const paymentFormSchema = z.object({
  method_id: z.number({ message: "Vui lòng chọn phương thức thanh toán" }),
  amount: z
    .number({ message: "Vui lòng nhập số tiền" })
    .positive("Số tiền phải lớn hơn 0"),
  payment_date: z.date().optional(),
  reference_code: z.string().optional(),
  payer_name: z.string().optional(),
  payer_account: z.string().optional(),
  notes: z.string().max(500, "Ghi chú không được quá 500 ký tự").optional(),
})

type PaymentFormValues = z.infer<typeof paymentFormSchema>

// =============================================================================
// TYPES
// =============================================================================

interface PaymentRecordDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  maxAmount: string
  feeId?: number
  /** Prefill the payer name (student/parent, known from the collection drawer). */
  defaultPayerName?: string
  /**
   * Prefill the reference — a reconciliation HINT (the profile code "HS-…"),
   * NOT the literal VietQR note: the bank statement shows the de-accented note
   * "… HS000131 …" (no hyphen). The accountant edits it if they have the exact
   * bank reference.
   */
  defaultReference?: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * PaymentRecordDialog - Dialog to record a new payment (Maker step)
 *
 * Creates a payment with status "pending" which needs verification.
 */
export function PaymentRecordDialog({
  open,
  onOpenChange,
  invoiceId,
  maxAmount,
  feeId,
  defaultPayerName,
  defaultReference,
}: PaymentRecordDialogProps) {
  const createMutation = useCreatePayment()
  const { data: paymentMethods, isLoading: methodsLoading } = usePaymentMethods()

  // Filter to offline methods only (online has separate flow)
  const offlineMethods = React.useMemo(() => {
    return paymentMethods?.filter((m) => !m.is_online && m.is_active) || []
  }, [paymentMethods])

  const form = useForm<PaymentFormValues>({
    resolver: zodResolver(paymentFormSchema),
    defaultValues: {
      method_id: undefined,
      amount: undefined,
      payment_date: new Date(),
      reference_code: defaultReference ?? "",
      payer_name: defaultPayerName ?? "",
      payer_account: "",
      notes: "",
    },
  })

  const onSubmit = async (values: PaymentFormValues) => {
    const maxAmountNum = parseVNDDisplayAmount(maxAmount)
    if (!isNaN(maxAmountNum) && values.amount > maxAmountNum) {
      form.setError("amount", { message: `Số tiền không được vượt quá số dư (${maxAmount})` });
      return;
    }
    try {
      await createMutation.mutateAsync({
        invoiceId,
        feeId,
        data: {
          invoice_id: invoiceId,
          method_id: values.method_id,
          amount: values.amount.toString(),
          payment_date: values.payment_date?.toISOString().split("T")[0],
          reference_code: values.reference_code || undefined,
          payer_name: values.payer_name || undefined,
          payer_account: values.payer_account || undefined,
          notes: values.notes || undefined,
        },
      })
      toast.success("Đã ghi nhận thanh toán, chờ xác minh")
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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Ghi nhận thanh toán
          </DialogTitle>
          <DialogDescription>
            Nhập thông tin thanh toán. Sau khi ghi nhận, thanh toán sẽ chờ xác minh từ người quản lý.
            <br />
            <span className="font-medium">Số tiền còn lại: {maxAmount}</span>
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Payment Method */}
            <FormField
              control={form.control}
              name="method_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Phương thức thanh toán <span className="text-destructive">*</span>
                  </FormLabel>
                  <Select
                    value={field.value?.toString()}
                    onValueChange={(v) => field.onChange(parseInt(v))}
                    disabled={methodsLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        {methodsLoading ? (
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Đang tải…
                          </span>
                        ) : (
                          <SelectValue placeholder="Chọn phương thức..." />
                        )}
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {offlineMethods.length === 0 && !methodsLoading && (
                        <div className="py-2 px-3 text-sm text-muted-foreground">
                          Không có phương thức nào khả dụng
                        </div>
                      )}
                      {offlineMethods.map((method) => (
                        <SelectItem key={method.id} value={method.id.toString()}>
                          {method.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Amount */}
            <FormField
              control={form.control}
              name="amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Số tiền <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <CurrencyInput
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Nhập số tiền..."
                      className="h-11"
                    />
                  </FormControl>
                  <FormDescription>Số tiền còn lại: {maxAmount}</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Payment Date */}
            <FormField
              control={form.control}
              name="payment_date"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ngày thanh toán</FormLabel>
                  <FormControl>
                    <DatePicker
                      value={field.value}
                      onChange={field.onChange}
                      placeholder="Chọn ngày..."
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Reference Code */}
            <FormField
              control={form.control}
              name="reference_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Mã tham chiếu / Số biên lai{" "}
                    <span className="font-normal text-muted-foreground">(tùy chọn)</span>
                  </FormLabel>
                  <FormControl>
                    <Input {...field} placeholder="VD: PT001234, UNC-123456..." />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Payer Info */}
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="payer_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tên người nộp</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="Họ tên..." />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="payer_account"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số tài khoản</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="STK (nếu có)..." />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Notes */}
            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ghi chú</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Ghi chú thêm (tùy chọn)..."
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
                disabled={createMutation.isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                Ghi nhận thanh toán
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default PaymentRecordDialog
