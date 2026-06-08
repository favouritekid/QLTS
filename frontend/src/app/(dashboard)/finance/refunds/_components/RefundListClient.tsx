"use client"

import * as React from "react"
import { AlertTriangle, CheckCircle, Plus, RefreshCw, RotateCcw, XCircle } from "lucide-react"
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
  useApproveRefund,
  useCreateRefund,
  useProcessRefund,
  useRefunds,
  useRejectRefund,
} from "@/hooks/finance/useRefunds"
import type { RefundRequest, RefundStatus } from "@/types/finance.types"

const STATUS_LABELS: Record<RefundStatus, string> = {
  pending: "Cho duyet",
  approved: "Da duyet",
  rejected: "Tu choi",
  refunded: "Da hoan",
}

export function RefundListClient() {
  const [statusFilter, setStatusFilter] = React.useState<RefundStatus | "all">("pending")
  const [createOpen, setCreateOpen] = React.useState(false)
  const [action, setAction] = React.useState<null | { type: "reject" | "process"; refund: RefundRequest }>(null)
  const [createForm, setCreateForm] = React.useState({ payment_id: "", amount: "", reason: "" })
  const [rejectionReason, setRejectionReason] = React.useState("")
  const [refundReference, setRefundReference] = React.useState("")

  const { data, isLoading, error, refetch } = useRefunds({
    status: statusFilter === "all" ? undefined : statusFilter,
    page: 1,
    page_size: 50,
  })
  const createRefund = useCreateRefund()
  const approveRefund = useApproveRefund()
  const rejectRefund = useRejectRefund()
  const processRefund = useProcessRefund()

  const handleCreate = async () => {
    await createRefund.mutateAsync({
      payment_id: Number(createForm.payment_id),
      amount: createForm.amount,
      reason: createForm.reason,
    })
    setCreateOpen(false)
    setCreateForm({ payment_id: "", amount: "", reason: "" })
  }

  const handleReject = async () => {
    if (!action || action.type !== "reject") return
    await rejectRefund.mutateAsync({
      id: action.refund.id,
      data: { rejection_reason: rejectionReason },
    })
    setAction(null)
    setRejectionReason("")
  }

  const handleProcess = async () => {
    if (!action || action.type !== "process") return
    await processRefund.mutateAsync({
      id: action.refund.id,
      data: { refund_id: action.refund.id, refund_reference: refundReference },
    })
    setAction(null)
    setRefundReference("")
  }

  if (error) {
    return (
      <div className="p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-destructive" />
            <p className="font-medium text-destructive">Khong the tai danh sach hoan phi</p>
            <Button variant="outline" className="mt-4" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Thu lai
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
          <h1 className="text-2xl font-bold tracking-tight">Hoan phi</h1>
          <p className="text-muted-foreground">Yeu cau, phe duyet va xu ly hoan phi</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Lam moi
          </Button>
          {data?.can_create && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Tao yeu cau
            </Button>
          )}
        </div>
      </div>

      <div className="flex max-w-xs">
        <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as RefundStatus | "all")}>
          <SelectTrigger>
            <SelectValue placeholder="Trang thai" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending">Cho duyet</SelectItem>
            <SelectItem value="all">Tat ca</SelectItem>
            <SelectItem value="approved">Da duyet</SelectItem>
            <SelectItem value="rejected">Tu choi</SelectItem>
            <SelectItem value="refunded">Da hoan</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Refund</TableHead>
                <TableHead>Payment</TableHead>
                <TableHead className="text-right">So tien</TableHead>
                <TableHead>Trang thai</TableHead>
                <TableHead>Ngay tao</TableHead>
                <TableHead className="text-right">Thao tac</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Dang tai...
                  </TableCell>
                </TableRow>
              ) : data?.items.length ? (
                data.items.map((refund) => (
                  <TableRow key={refund.id}>
                    <TableCell>
                      <div className="font-mono">#{refund.id}</div>
                      <div className="line-clamp-1 text-xs text-muted-foreground">{refund.reason}</div>
                    </TableCell>
                    <TableCell className="font-mono">#{refund.payment_id}</TableCell>
                    <TableCell className="text-right">
                      <AmountDisplay amount={refund.amount} showCurrency={false} size="sm" />
                    </TableCell>
                    <TableCell>
                      <Badge variant={refund.status === "rejected" ? "destructive" : "outline"}>
                        {STATUS_LABELS[refund.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>{new Intl.DateTimeFormat("vi-VN").format(new Date(refund.created_at))}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {refund.can_approve && (
                          <Button size="sm" variant="outline" onClick={() => approveRefund.mutate(refund.id)}>
                            <CheckCircle className="mr-2 h-4 w-4" />
                            Duyet
                          </Button>
                        )}
                        {refund.can_reject && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setAction({ type: "reject", refund })}
                          >
                            <XCircle className="mr-2 h-4 w-4" />
                            Tu choi
                          </Button>
                        )}
                        {refund.can_process && (
                          <Button size="sm" onClick={() => setAction({ type: "process", refund })}>
                            <RotateCcw className="mr-2 h-4 w-4" />
                            Xu ly
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Khong co du lieu
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tao yeu cau hoan phi</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Field label="Payment ID">
              <Input
                inputMode="numeric"
                value={createForm.payment_id}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, payment_id: event.target.value.replace(/\D/g, "") }))}
              />
            </Field>
            <Field label="So tien">
              <Input
                inputMode="decimal"
                value={createForm.amount}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, amount: event.target.value }))}
              />
            </Field>
            <Field label="Ly do">
              <Textarea
                value={createForm.reason}
                onChange={(event) => setCreateForm((prev) => ({ ...prev, reason: event.target.value }))}
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Huy</Button>
            <Button
              onClick={handleCreate}
              disabled={!createForm.payment_id || !createForm.amount || !createForm.reason || createRefund.isPending}
            >
              Tao
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "reject"} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tu choi hoan phi</DialogTitle>
          </DialogHeader>
          <Textarea value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>Huy</Button>
            <Button variant="destructive" onClick={handleReject} disabled={!rejectionReason || rejectRefund.isPending}>
              Tu choi
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "process"} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Xu ly hoan phi</DialogTitle>
          </DialogHeader>
          <Field label="Ma tham chieu">
            <Input value={refundReference} onChange={(event) => setRefundReference(event.target.value)} />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>Huy</Button>
            <Button onClick={handleProcess} disabled={!refundReference || processRefund.isPending}>
              Xu ly
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
