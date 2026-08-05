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
import { useCreatePayment, usePendingPaymentsByFee } from "@/hooks/finance/usePayments"
import { usePaymentMethods } from "@/hooks/finance/usePaymentMethods"
import { useInvoiceDetail } from "@/hooks/finance/useInvoices"
import { AmountDisplay } from "@/components/finance"
import { formatVND, parseVNDDisplayAmount } from "@/lib/zod/finance"
import { calendarDateToISO } from "@/lib/utils/vn-date"
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
  /**
   * Số dư ĐÃ ĐỊNH DẠNG, chụp tại nơi mở form. Chỉ để vẽ ngay lúc mở (tránh
   * nhảy layout) và làm phương án dự phòng khi chưa có số máy chủ. KHÔNG được
   * dùng trực tiếp ở bất kỳ chỗ nào khác — mọi con số hiện ra và mọi phép
   * kiểm tra đều đi qua `remainingLabel` / `remainingLimit` bên dưới, nếu
   * không dialog sẽ nói hai số "còn lại" khác nhau ở hai chỗ.
   */
  maxAmount: string
  /**
   * BẮT BUỘC: ô "đang chờ duyệt" hỏi theo KHOẢN PHÍ (mọi đợt), không theo một
   * hoá đơn. Thiếu nó thì ô đếm im lặng trống rỗng và dialog quay về đúng
   * trạng thái nói dối mà B1 sinh ra để xoá — nên đây là lỗi biên dịch, không
   * phải giá trị tuỳ chọn.
   */
  feeId: number
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

  // Số thật để dựng bảng công nợ. Chỉ fetch khi dialog mở — không tốn request
  // cho mọi dòng trong danh sách.
  const {
    data: invoice,
    isLoading: invoiceLoading,
    isError: invoiceFailed,
  } = useInvoiceDetail(invoiceId, {
    enabled: open,
    // `enabled: open` KHÔNG đủ để có số mới: trang cha dùng chung query key
    // này với độ tươi mặc định 30 giây, nên mở lại form trong 30 giây sẽ đọc
    // lại đúng bản cache cũ — trong khi hàng đợi chờ duyệt đã tươi. Kết quả là
    // panel nói "không còn phiếu chờ" kèm một số dư từ trước lúc duyệt, tức
    // vẫn đúng cái màn hình nói dối mà B1 sinh ra để xoá.
    staleTime: 0,
  })
  // Phiếu TAY ĐANG CHỜ DUYỆT của cả khoản phí (mọi đợt). Đây là dòng chữa
  // bệnh: `fee.paid_amount` chỉ tăng khi phiếu được duyệt, nên nếu không hiện
  // phần đang chờ thì màn hình trông y như chưa ai thu — và kế toán nhập lại.
  const {
    data: pendingPage,
    isLoading: pendingLoading,
    isError: pendingFailed,
  } = usePendingPaymentsByFee(feeId, {
    enabled: open,
  })

  const pendingItems = pendingPage?.items ?? []
  // Cộng tối đa 100 phần tử số — rẻ hơn hẳn chi phí giữ một mảng ổn định qua
  // các lần render, nên không memo hoá.
  const pendingSum = pendingItems.reduce((sum, p) => sum + Number(p.amount ?? 0), 0)
  // Máy chủ trả `total` của cả khoản phí, còn `items` bị cắt theo page_size.
  // Nếu cắt thì con số cộng được KHÔNG phải tổng thật — phải nói ra, chứ trình
  // bày một tổng thiếu như thể đầy đủ cũng là một kiểu nói dối.
  const pendingTruncated = (pendingPage?.total ?? pendingItems.length) > pendingItems.length

  // MỘT nguồn duy nhất cho "còn phải thu": số máy chủ nếu đã tải được, nếu
  // chưa thì rơi về ảnh chụp truyền qua prop. Cả tiêu đề, dòng mô tả ô nhập,
  // thông báo lỗi lẫn phép chặn đều đọc ở đây — trước đó phép chặn dùng số
  // máy chủ còn chữ hiển thị dùng prop, nên form từ chối một số tiền mà chính
  // nó vừa nói là hợp lệ.
  const serverRemaining = invoice?.remaining_amount
  const hasServerRemaining = serverRemaining !== undefined && serverRemaining !== null
  const remainingLimit = hasServerRemaining
    ? Number(serverRemaining)
    : parseVNDDisplayAmount(maxAmount)
  const remainingLabel = hasServerRemaining ? formatVND(serverRemaining) : maxAmount

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
    // Chặn theo đúng con số mà form vừa hiển thị — cùng biến, không tính lại.
    if (!isNaN(remainingLimit) && values.amount > remainingLimit) {
      form.setError("amount", {
        message: `Số tiền không được vượt quá số dư (${remainingLabel})`,
      });
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
          // Đọc thẳng ô ngày người dùng bấm. `toISOString()` quy về UTC nên ở
          // Việt Nam nó ghi LÙI MỘT NGÀY mọi lần kế toán tự chọn ngày —
          // xem `calendarDateToISO`.
          payment_date: values.payment_date
            ? calendarDateToISO(values.payment_date)
            : undefined,
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
            <span className="font-medium">Số tiền còn lại: {remainingLabel}</span>
            {!hasServerRemaining && !invoiceLoading && (
              <span className="text-muted-foreground"> (chưa đối chiếu lại)</span>
            )}
          </DialogDescription>
        </DialogHeader>

        {/*
          Bảng công nợ. Dòng "đang chờ duyệt" là lý do cả khối này tồn tại:
          tiền chỉ vào sổ khi phiếu được DUYỆT, nên nếu không nói ra thì màn
          hình hiện y như chưa ai thu và kế toán nhập lại — prod đã có 9 phiếu
          nghi trùng theo đúng đường đó.
          Đang tải thì hiện khung mờ, KHÔNG chặn form: người dùng vẫn gõ được.
        */}
        <div
          className="rounded-md border bg-muted/40 p-3 text-sm"
          data-testid="payment-debt-panel"
        >
          {invoiceLoading || pendingLoading ? (
            <div className="space-y-2" aria-hidden>
              <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
              <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
            </div>
          ) : invoiceFailed ? (
            /*
              Request hỏng thì TUYỆT ĐỐI không vẽ 0. Một bảng công nợ toàn số 0
              trông y hệt "hồ sơ này chưa nợ gì" — kế toán tin là đã đối chiếu
              xong rồi nhập tiếp, tức lỗi tải trở thành đúng cái nguyên nhân mà
              ô này sinh ra để chặn.
            */
            <p
              role="alert"
              className="text-destructive"
              data-testid="payment-debt-error"
            >
              Không tải được dữ liệu đối chiếu. Vui lòng đóng và mở lại form —
              đừng ghi tiền khi chưa thấy số dư và các phiếu đang chờ duyệt.
            </p>
          ) : (
            <dl className="space-y-1">
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Tổng hoá đơn</dt>
                <dd><AmountDisplay amount={invoice?.total_due ?? "0"} /></dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Đã thu (đã duyệt)</dt>
                <dd><AmountDisplay amount={invoice?.paid_amount ?? "0"} /></dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Còn phải thu</dt>
                <dd className="font-medium">
                  <AmountDisplay amount={invoice?.remaining_amount ?? "0"} />
                </dd>
              </div>
              {/*
                Ô "chờ duyệt" hỏng thì phải NÓI hỏng. Ẩn đi là trình bày "không
                có phiếu nào đang chờ" — đúng câu trả lời sai nguy hiểm nhất ở
                đây, vì nó cấp phép cho lần nhập thứ hai.
              */}
              {pendingFailed ? (
                <div
                  className="border-t pt-1 text-destructive"
                  role="alert"
                  data-testid="payment-pending-error"
                >
                  Không tải được danh sách phiếu đang chờ duyệt — chưa thể
                  khẳng định khoản này đã được nhập hay chưa.
                </div>
              ) : (
                pendingItems.length > 0 && (
                  <div
                    className="border-t pt-1 text-amber-700 dark:text-amber-500"
                    data-testid="payment-pending-row"
                  >
                    <div className="flex justify-between gap-4">
                      <dt className="font-medium">
                        Chờ duyệt: {pendingItems.length} phiếu
                      </dt>
                      <dd className="font-medium">
                        <AmountDisplay amount={String(pendingSum)} />
                      </dd>
                    </div>
                    {pendingTruncated && (
                      <p
                        className="text-xs font-normal"
                        data-testid="payment-pending-truncated"
                      >
                        Danh sách bị giới hạn {pendingItems.length} phiếu trên
                        tổng {pendingPage?.total} — số cộng ở đây chưa phải tổng
                        đầy đủ.
                      </p>
                    )}
                  </div>
                )
              )}
            </dl>
          )}
        </div>

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
                  <FormDescription>Số tiền còn lại: {remainingLabel}</FormDescription>
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
