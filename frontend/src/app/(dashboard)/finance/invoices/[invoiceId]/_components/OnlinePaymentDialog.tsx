// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/OnlinePaymentDialog.tsx
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
import { Button } from "@/components/ui/button"
import { CurrencyInput } from "@/components/ui/currency-input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Wifi, Loader2, CreditCard, ExternalLink, AlertTriangle } from "lucide-react"
import { useCreatePaymentIntent } from "@/hooks/finance/usePayments"
import { usePaymentMethods } from "@/hooks/finance/usePaymentMethods"
import { toast } from "sonner"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const onlinePaymentSchema = z.object({
  method_id: z.number({ message: "Vui lòng chọn cổng thanh toán" }),
  amount: z
    .number({ message: "Vui lòng nhập số tiền" })
    .positive("Số tiền phải lớn hơn 0"),
})

type OnlinePaymentFormValues = z.infer<typeof onlinePaymentSchema>

// =============================================================================
// TYPES
// =============================================================================

interface OnlinePaymentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  maxAmount: string
  invoiceNumber?: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * OnlinePaymentDialog - Dialog to initiate online payment via gateway
 *
 * Creates a PaymentIntent and redirects user to payment gateway.
 * Callback URL: /finance/payments/return
 */
export function OnlinePaymentDialog({
  open,
  onOpenChange,
  invoiceId,
  maxAmount,
  invoiceNumber,
}: OnlinePaymentDialogProps) {
  const createIntentMutation = useCreatePaymentIntent()
  const { data: paymentMethods, isLoading: methodsLoading } = usePaymentMethods()

  // Filter to online methods only
  const onlineMethods = React.useMemo(() => {
    return paymentMethods?.filter((m) => m.is_online && m.is_active) || []
  }, [paymentMethods])

  // Parse max amount for default value
  const maxAmountNumber = React.useMemo(() => {
    const parsed = parseFloat(maxAmount.replace(/[^0-9.-]/g, ""))
    return isNaN(parsed) ? 0 : parsed
  }, [maxAmount])

  const form = useForm<OnlinePaymentFormValues>({
    resolver: zodResolver(onlinePaymentSchema),
    defaultValues: {
      method_id: undefined,
      amount: maxAmountNumber > 0 ? maxAmountNumber : undefined,
    },
  })

  // Reset form when dialog opens with new amount
  React.useEffect(() => {
    if (open && maxAmountNumber > 0) {
      form.setValue("amount", maxAmountNumber)
    }
  }, [open, maxAmountNumber, form])

  const selectedMethodId = form.watch("method_id")
  const selectedMethod = React.useMemo(() => {
    return onlineMethods.find((m) => m.id === selectedMethodId)
  }, [onlineMethods, selectedMethodId])

  const onSubmit = async (values: OnlinePaymentFormValues) => {
    try {
      // Generate idempotency key
      const idempotencyKey = crypto.randomUUID()
      const returnUrl = `${window.location.origin}/finance/payments/return`

      await createIntentMutation.mutateAsync({
        data: {
          invoice_id: invoiceId,
          method_id: values.method_id,
          amount: values.amount.toString(),
          idempotency_key: idempotencyKey,
          return_url: returnUrl,
        },
        // onPayUrl callback will redirect automatically
      })

      // Dialog will remain open during redirect, or show loading
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

  const noOnlineMethods = !methodsLoading && onlineMethods.length === 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            Thanh toán online
          </DialogTitle>
          <DialogDescription>
            Chọn cổng thanh toán và số tiền để tiến hành thanh toán.
            {invoiceNumber && (
              <span className="block mt-1 font-medium">
                Hóa đơn: {invoiceNumber}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {noOnlineMethods ? (
          <div className="py-8 text-center">
            <AlertTriangle className="h-12 w-12 mx-auto text-warning-500 mb-4" />
            <p className="font-medium">Không có cổng thanh toán nào khả dụng</p>
            <p className="text-sm text-muted-foreground mt-1">
              Vui lòng liên hệ quản trị viên để cấu hình
            </p>
          </div>
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              {/* Payment Gateway */}
              <FormField
                control={form.control}
                name="method_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Cổng thanh toán <span className="text-destructive">*</span>
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
                            <SelectValue placeholder="Chọn cổng thanh toán..." />
                          )}
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {onlineMethods.map((method) => (
                          <SelectItem key={method.id} value={method.id.toString()}>
                            <div className="flex items-center gap-2">
                              <Wifi className="h-4 w-4 text-success-600" />
                              <span>{method.name}</span>
                              {method.gateway_code && (
                                <Badge variant="outline" className="text-xs">
                                  {method.gateway_code.toUpperCase()}
                                </Badge>
                              )}
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Selected Gateway Info */}
              {selectedMethod && (
                <Card className="border-primary/30 bg-primary/5">
                  <CardContent className="p-3 text-sm">
                    <div className="flex items-start gap-2">
                      <CreditCard className="h-4 w-4 mt-0.5 text-primary" />
                      <div>
                        <p className="font-medium">{selectedMethod.name}</p>
                        {selectedMethod.gateway_code && (
                          <p className="text-muted-foreground text-xs mt-0.5">
                            Cổng thanh toán: {selectedMethod.gateway_code.toUpperCase()}
                          </p>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

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

              {/* Warning */}
              <Card className="border-warning-500/50 bg-warning-50/50 dark:bg-warning-950/20">
                <CardContent className="p-3 text-sm flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 text-warning-600 shrink-0" />
                  <div>
                    <p className="font-medium text-warning-700 dark:text-warning-400">
                      Lưu ý
                    </p>
                    <p className="text-muted-foreground text-xs mt-0.5">
                      Bạn sẽ được chuyển đến cổng thanh toán. Sau khi hoàn tất, bạn sẽ
                      được chuyển về hệ thống.
                    </p>
                  </div>
                </CardContent>
              </Card>

              <DialogFooter className="gap-2 sm:gap-0">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                  disabled={createIntentMutation.isPending}
                >
                  Hủy
                </Button>
                <Button type="submit" disabled={createIntentMutation.isPending}>
                  {createIntentMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Đang xử lý…
                    </>
                  ) : (
                    <>
                      <ExternalLink className="h-4 w-4 mr-2" />
                      Thanh toán
                    </>
                  )}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default OnlinePaymentDialog
