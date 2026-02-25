"use client"

import { useState } from "react"
import { CheckCircle, XCircle, DollarSign } from "lucide-react"
import { PageContainer } from "@/components/layouts/PageContainer"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  useCommissionRecords,
  useApproveCommission,
  useRejectCommission,
  usePayCommission,
} from "@/hooks/useCommissions"
import type { CommissionRecord } from "@/types/commission.types"

// =============================================================================
// CONSTANTS
// =============================================================================

const PAGE_SIZE = 10

const STATUS_CONFIG: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  pending: { label: "Chờ duyệt", variant: "secondary" },
  approved: { label: "Đã duyệt", variant: "default" },
  paid: { label: "Đã thanh toán", variant: "default" },
  rejected: { label: "Từ chối", variant: "destructive" },
  cancelled: { label: "Đã hủy", variant: "outline" },
}

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(amount)
}

function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "-"
  try {
    return new Date(isoString).toLocaleDateString("vi-VN")
  } catch {
    return "-"
  }
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function CommissionsClient() {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string>("all")

  // Action dialogs
  const [approveTarget, setApproveTarget] = useState<CommissionRecord | null>(null)
  const [rejectTarget, setRejectTarget] = useState<CommissionRecord | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const [payTarget, setPayTarget] = useState<CommissionRecord | null>(null)
  const [payRef, setPayRef] = useState("")

  const { data, isLoading, isError, error } = useCommissionRecords({
    skip: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    status: statusFilter === "all" ? undefined : statusFilter,
  })

  const approveMutation = useApproveCommission()
  const rejectMutation = useRejectCommission()
  const payMutation = usePayCommission()

  async function handleApprove() {
    if (approveTarget) {
      await approveMutation.mutateAsync(approveTarget.id)
      setApproveTarget(null)
    }
  }

  async function handleReject() {
    if (rejectTarget && rejectReason.trim()) {
      await rejectMutation.mutateAsync({ id: rejectTarget.id, data: { rejection_reason: rejectReason } })
      setRejectTarget(null)
      setRejectReason("")
    }
  }

  async function handlePay() {
    if (payTarget) {
      await payMutation.mutateAsync({ id: payTarget.id, data: { payment_reference: payRef || null } })
      setPayTarget(null)
      setPayRef("")
    }
  }

  const totalPages = data ? Math.ceil(data.total_count / PAGE_SIZE) : 0

  if (isError) {
    return (
      <PageContainer maxWidth="xl">
        <h1 className="text-2xl font-bold tracking-tight">Quản lý Hoa hồng</h1>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi tải dữ liệu: {error?.message}</p>
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer maxWidth="xl">
      <header>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Quản lý Hoa hồng</h1>
        <p className="text-muted-foreground">Duyệt, từ chối và thanh toán hoa hồng cho CTV.</p>
      </header>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Bộ lọc</CardTitle>
          <CardDescription>Lọc theo trạng thái</CardDescription>
        </CardHeader>
        <CardContent>
          <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1) }}>
            <SelectTrigger className="w-full md:w-[200px]">
              <SelectValue placeholder="Tất cả trạng thái" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả</SelectItem>
              <SelectItem value="pending">Chờ duyệt</SelectItem>
              <SelectItem value="approved">Đã duyệt</SelectItem>
              <SelectItem value="paid">Đã thanh toán</SelectItem>
              <SelectItem value="rejected">Từ chối</SelectItem>
              <SelectItem value="cancelled">Đã hủy</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[800px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>CTV</TableHead>
                    <TableHead>Lead</TableHead>
                    <TableHead>Chính sách</TableHead>
                    <TableHead className="text-right">Số tiền</TableHead>
                    <TableHead>Trạng thái</TableHead>
                    <TableHead>Ngày tạo</TableHead>
                    <TableHead>Thao tác</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data?.records?.length ? (
                    data.records.map((record) => (
                      <TableRow key={record.id}>
                        <TableCell className="font-mono text-sm">#{record.id}</TableCell>
                        <TableCell>
                          {record.collaborator ? (
                            <div>
                              <p className="font-medium text-sm">{record.collaborator.full_name}</p>
                              <p className="text-muted-foreground text-xs">{record.collaborator.code}</p>
                            </div>
                          ) : "-"}
                        </TableCell>
                        <TableCell>
                          {record.lead ? (
                            <p className="text-sm">{record.lead.full_name ?? `Lead #${record.lead_id}`}</p>
                          ) : `#${record.lead_id}`}
                        </TableCell>
                        <TableCell>
                          <p className="text-sm">{record.policy?.name ?? `Policy #${record.policy_id}`}</p>
                        </TableCell>
                        <TableCell className="text-right font-medium">
                          {formatCurrency(record.amount)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={STATUS_CONFIG[record.status]?.variant ?? "outline"}>
                            {STATUS_CONFIG[record.status]?.label ?? record.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDate(record.triggered_at)}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {record.status === "pending" && (
                              <>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setApproveTarget(record)}
                                  aria-label="Duyệt"
                                >
                                  <CheckCircle className="h-4 w-4 text-green-600" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setRejectTarget(record)}
                                  aria-label="Từ chối"
                                >
                                  <XCircle className="h-4 w-4 text-destructive" />
                                </Button>
                              </>
                            )}
                            {record.status === "approved" && (
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setPayTarget(record)}
                                aria-label="Thanh toán"
                              >
                                <DollarSign className="h-4 w-4 text-blue-600" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={8} className="h-32 text-center text-muted-foreground">
                        Chưa có hoa hồng nào.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {data && data.total_count > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-sm">
            Hiển thị {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, data.total_count)} / {data.total_count}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
              Trước
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
              Sau
            </Button>
          </div>
        </div>
      )}

      {/* Approve Dialog */}
      <AlertDialog open={!!approveTarget} onOpenChange={() => setApproveTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Duyệt hoa hồng?</AlertDialogTitle>
            <AlertDialogDescription>
              Duyệt hoa hồng <strong>{formatCurrency(approveTarget?.amount ?? 0)}</strong> cho CTV{" "}
              <strong>{approveTarget?.collaborator?.full_name}</strong>?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={handleApprove} disabled={approveMutation.isPending}>
              {approveMutation.isPending ? "Đang xử lý…" : "Duyệt"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reject Dialog */}
      <AlertDialog open={!!rejectTarget} onOpenChange={() => { setRejectTarget(null); setRejectReason("") }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Từ chối hoa hồng?</AlertDialogTitle>
            <AlertDialogDescription>
              Từ chối hoa hồng {formatCurrency(rejectTarget?.amount ?? 0)} cho CTV{" "}
              {rejectTarget?.collaborator?.full_name}?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="px-6 pb-2">
            <Label htmlFor="rejection-reason">Lý do từ chối</Label>
            <Input
              id="rejection-reason"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Nhập lý do..."
              className="mt-1"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleReject}
              disabled={rejectMutation.isPending || !rejectReason.trim()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {rejectMutation.isPending ? "Đang xử lý…" : "Từ chối"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Pay Dialog */}
      <AlertDialog open={!!payTarget} onOpenChange={() => { setPayTarget(null); setPayRef("") }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Thanh toán hoa hồng?</AlertDialogTitle>
            <AlertDialogDescription>
              Thanh toán {formatCurrency(payTarget?.amount ?? 0)} cho CTV{" "}
              {payTarget?.collaborator?.full_name}?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="px-6 pb-2">
            <Label htmlFor="payment-ref">Mã tham chiếu thanh toán (tùy chọn)</Label>
            <Input
              id="payment-ref"
              value={payRef}
              onChange={(e) => setPayRef(e.target.value)}
              placeholder="VD: CK-20260225-001"
              className="mt-1"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={handlePay} disabled={payMutation.isPending}>
              {payMutation.isPending ? "Đang xử lý…" : "Xác nhận thanh toán"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
