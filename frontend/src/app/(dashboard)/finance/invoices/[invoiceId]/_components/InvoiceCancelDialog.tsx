// src/app/(dashboard)/finance/invoices/[invoiceId]/_components/InvoiceCancelDialog.tsx
"use client"

import * as React from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Textarea } from "@/components/ui/textarea"
import { AlertTriangle, Loader2 } from "lucide-react"
import { useCancelInvoice } from "@/hooks/finance/useInvoices"
import { toast } from "sonner"

// =============================================================================
// FORM SCHEMA
// =============================================================================

const cancelFormSchema = z.object({
  reason: z.string().min(1, "Vui lòng nhập lý do hủy").max(500, "Lý do không được quá 500 ký tự"),
})

type CancelFormValues = z.infer<typeof cancelFormSchema>

// =============================================================================
// TYPES
// =============================================================================

interface InvoiceCancelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  invoiceId: number
  invoiceNumber: string
  feeId: number
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * InvoiceCancelDialog - Confirmation dialog to cancel an invoice
 *
 * Requires a reason for cancellation.
 */
export function InvoiceCancelDialog({
  open,
  onOpenChange,
  invoiceId,
  invoiceNumber,
  feeId,
}: InvoiceCancelDialogProps) {
  const cancelMutation = useCancelInvoice()

  const form = useForm<CancelFormValues>({
    resolver: zodResolver(cancelFormSchema),
    defaultValues: {
      reason: "",
    },
  })

  const onSubmit = async (values: CancelFormValues) => {
    try {
      await cancelMutation.mutateAsync({
        invoiceId,
        feeId,
        reason: values.reason,
      })
      toast.success("Đã hủy hóa đơn thành công")
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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            Xác nhận hủy hóa đơn
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2">
            {/* AlertDialogDescription renders a <p>; use block spans so we don't
                nest <p> in <p> (invalid HTML → hydration error). */}
            <span className="block">
              Bạn có chắc chắn muốn hủy hóa đơn <strong className="font-mono">{invoiceNumber}</strong>?
            </span>
            <span className="block text-destructive font-medium">
              Hành động này không thể hoàn tác.
            </span>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="reason"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Lý do hủy <span className="text-destructive">*</span>
                  </FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      placeholder="Nhập lý do hủy hóa đơn..."
                      rows={3}
                      className="resize-none"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <AlertDialogFooter>
              <AlertDialogCancel
                type="button"
                disabled={cancelMutation.isPending}
                onClick={() => onOpenChange(false)}
              >
                Không, giữ lại
              </AlertDialogCancel>
              <AlertDialogAction
                type="submit"
                disabled={cancelMutation.isPending}
                className="bg-destructive hover:bg-destructive/90"
                onClick={(e) => {
                  e.preventDefault()
                  form.handleSubmit(onSubmit)()
                }}
              >
                {cancelMutation.isPending && (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                )}
                Xác nhận hủy
              </AlertDialogAction>
            </AlertDialogFooter>
          </form>
        </Form>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export default InvoiceCancelDialog
