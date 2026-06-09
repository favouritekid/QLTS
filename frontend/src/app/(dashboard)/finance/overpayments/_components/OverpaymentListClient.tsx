"use client"

import * as React from "react"
import { AlertTriangle, CheckCircle, RefreshCw, RotateCcw, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { AmountDisplay } from "@/components/finance"
import {
  useApplyOverpayment,
  useOverpayments,
  useRefundOverpayment,
  useWriteOffOverpayment,
} from "@/hooks/finance/useOverpayments"
import type { OverpaymentRecord, OverpaymentStatus } from "@/types/finance.types"

const STATUS_LABELS: Record<OverpaymentStatus, string> = {
  pending: "Chờ xử lý",
  applied: "Đã áp dụng",
  refunded: "Đã hoàn",
  cancelled: "Đã xóa sổ",
}

type ActionState =
  | { type: "apply"; overpayment: OverpaymentRecord }
  | { type: "refund"; overpayment: OverpaymentRecord }
  | { type: "write_off"; overpayment: OverpaymentRecord }
  | null

export function OverpaymentListClient() {
  const [statusFilter, setStatusFilter] = React.useState<OverpaymentStatus | "all">("pending")
  const [action, setAction] = React.useState<ActionState>(null)
  const [targetInvoiceId, setTargetInvoiceId] = React.useState("")
  const [amount, setAmount] = React.useState("")
  const [notes, setNotes] = React.useState("")

  const { data, isLoading, error, refetch } = useOverpayments({
    status: statusFilter === "all" ? undefined : statusFilter,
    page: 1,
    page_size: 50,
  })
  const applyOverpayment = useApplyOverpayment()
  const refundOverpayment = useRefundOverpayment()
  const writeOffOverpayment = useWriteOffOverpayment()

  const closeAction = () => {
    setAction(null)
    setTargetInvoiceId("")
    setAmount("")
    setNotes("")
  }

  const handleApply = async () => {
    if (!action || action.type !== "apply") return
    await applyOverpayment.mutateAsync({
      id: action.overpayment.id,
      data: {
        overpayment_id: action.overpayment.id,
        target_invoice_id: Number(targetInvoiceId),
        amount: amount || undefined,
        notes: notes || undefined,
      },
    })
    closeAction()
  }

  const handleRefund = async () => {
    if (!action || action.type !== "refund") return
    await refundOverpayment.mutateAsync({
      id: action.overpayment.id,
      data: {
        overpayment_id: action.overpayment.id,
        notes: notes || undefined,
      },
    })
    closeAction()
  }

  const handleWriteOff = async () => {
    if (!action || action.type !== "write_off") return
    await writeOffOverpayment.mutateAsync({
      id: action.overpayment.id,
      data: {
        overpayment_id: action.overpayment.id,
        reason: notes,
      },
    })
    closeAction()
  }

  if (error) {
    return (
      <div className="p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-destructive" />
            <p className="font-medium text-destructive">Không thể tải danh sách tiền nộp thừa</p>
            <Button variant="outline" className="mt-4" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Thử lại
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tiền nộp thừa</h1>
          <p className="text-muted-foreground">Xử lý các khoản tiền nộp thừa đang treo</p>
        </div>
        <Button variant="outline" onClick={() => refetch()}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Làm mới
        </Button>
      </div>

      <div className="flex max-w-xs">
        <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as OverpaymentStatus | "all")}>
          <SelectTrigger>
            <SelectValue placeholder="Trạng thái" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending">Chờ xử lý</SelectItem>
            <SelectItem value="all">Tất cả</SelectItem>
            <SelectItem value="applied">Đã áp dụng</SelectItem>
            <SelectItem value="refunded">Đã hoàn</SelectItem>
            <SelectItem value="cancelled">Đã xóa sổ</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Khoản nộp thừa</TableHead>
                <TableHead>Hồ sơ</TableHead>
                <TableHead>Hóa đơn</TableHead>
                <TableHead className="text-right">Số tiền</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Đang tải...
                  </TableCell>
                </TableRow>
              ) : data?.items.length ? (
                data.items.map((overpayment) => (
                  <TableRow key={overpayment.id}>
                    <TableCell className="font-mono">#{overpayment.id}</TableCell>
                    <TableCell className="font-mono">#{overpayment.admission_profile_id}</TableCell>
                    <TableCell className="font-mono">#{overpayment.invoice_id}</TableCell>
                    <TableCell className="text-right">
                      <AmountDisplay amount={overpayment.overpayment_amount} showCurrency={false} size="sm" />
                    </TableCell>
                    <TableCell>
                      <Badge variant={overpayment.status === "cancelled" ? "destructive" : "outline"}>
                        {STATUS_LABELS[overpayment.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {overpayment.can_apply && (
                          <Button size="sm" variant="outline" onClick={() => setAction({ type: "apply", overpayment })}>
                            <CheckCircle className="mr-2 h-4 w-4" />
                            Áp dụng
                          </Button>
                        )}
                        {overpayment.can_refund && (
                          <Button size="sm" variant="outline" onClick={() => setAction({ type: "refund", overpayment })}>
                            <RotateCcw className="mr-2 h-4 w-4" />
                            Hoàn tiền
                          </Button>
                        )}
                        {overpayment.can_write_off && (
                          <Button size="sm" variant="outline" onClick={() => setAction({ type: "write_off", overpayment })}>
                            <XCircle className="mr-2 h-4 w-4" />
                            Xóa sổ
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Không có dữ liệu
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={action?.type === "apply"} onOpenChange={(open) => !open && closeAction()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Áp dụng tiền nộp thừa</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Field label="Hóa đơn đích">
              <Input
                inputMode="numeric"
                value={targetInvoiceId}
                onChange={(event) => setTargetInvoiceId(event.target.value.replace(/\D/g, ""))}
              />
            </Field>
            <Field label="Số tiền">
              <Input
                inputMode="decimal"
                placeholder={action?.type === "apply" ? action.overpayment.overpayment_amount : undefined}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />
            </Field>
            <Field label="Ghi chú">
              <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeAction}>Hủy</Button>
            <Button onClick={handleApply} disabled={!targetInvoiceId || applyOverpayment.isPending}>
              Áp dụng
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "refund"} onOpenChange={(open) => !open && closeAction()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tạo yêu cầu hoàn tiền nộp thừa</DialogTitle>
          </DialogHeader>
          <Field label="Ghi chú">
            <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={closeAction}>Hủy</Button>
            <Button onClick={handleRefund} disabled={refundOverpayment.isPending}>
              Tạo yêu cầu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "write_off"} onOpenChange={(open) => !open && closeAction()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xóa sổ tiền nộp thừa</DialogTitle>
          </DialogHeader>
          <Field label="Lý do">
            <Textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={closeAction}>Hủy</Button>
            <Button variant="destructive" onClick={handleWriteOff} disabled={!notes || writeOffOverpayment.isPending}>
              Xóa sổ
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = React.useId()
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<{ id?: string }>, { id })
        : children}
    </div>
  )
}
