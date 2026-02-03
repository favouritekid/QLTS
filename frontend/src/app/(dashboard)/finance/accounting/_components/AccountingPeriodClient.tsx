// src/app/(dashboard)/finance/accounting/_components/AccountingPeriodClient.tsx
"use client"

import * as React from "react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Calendar,
  Plus,
  Lock,
  AlertTriangle,
  Loader2,
  CheckCircle,
  Clock,
} from "lucide-react"
import {
  useAccountingPeriods,
  useCurrentPeriod,
  useCreatePeriod,
  useClosePeriod,
} from "@/hooks/finance/useAccountingPeriods"
import { AmountDisplay } from "@/components/finance"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import type { AccountingPeriod } from "@/types/finance.types"

// =============================================================================
// MONTH LABELS
// =============================================================================

const MONTH_LABELS: Record<number, string> = {
  1: "Tháng 1",
  2: "Tháng 2",
  3: "Tháng 3",
  4: "Tháng 4",
  5: "Tháng 5",
  6: "Tháng 6",
  7: "Tháng 7",
  8: "Tháng 8",
  9: "Tháng 9",
  10: "Tháng 10",
  11: "Tháng 11",
  12: "Tháng 12",
}

// =============================================================================
// HELPERS
// =============================================================================

function formatPeriodLabel(month: number, year: number): string {
  return `${MONTH_LABELS[month]} ${year}`
}

function formatDate(dateString: string | null): string {
  if (!dateString) return "-"
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString))
}

// Generate year options (current year - 2 to current year + 1)
function getYearOptions(): number[] {
  const currentYear = new Date().getFullYear()
  return [currentYear - 2, currentYear - 1, currentYear, currentYear + 1]
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * AccountingPeriodClient - Manage accounting periods
 *
 * Features:
 * - List all accounting periods
 * - Create new period (admin only)
 * - Close period (admin only)
 * - View period summary
 */
export function AccountingPeriodClient() {
  // Filters
  const [yearFilter, setYearFilter] = React.useState<number | undefined>(undefined)

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [closeDialogOpen, setCloseDialogOpen] = React.useState(false)
  const [selectedPeriod, setSelectedPeriod] = React.useState<AccountingPeriod | null>(null)

  // Queries
  const { data: periods, isLoading, error } = useAccountingPeriods(
    yearFilter ? { year: yearFilter } : undefined
  )
  const { data: currentPeriod } = useCurrentPeriod()

  // Handle close period click
  const handleCloseClick = (period: AccountingPeriod) => {
    setSelectedPeriod(period)
    setCloseDialogOpen(true)
  }

  if (error) {
    return (
      <div className="h-full flex flex-col p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-destructive font-medium">Không thể tải dữ liệu</p>
            <p className="text-sm text-muted-foreground mt-1">
              Vui lòng thử lại sau
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Kỳ kế toán</h1>
          <p className="text-muted-foreground">
            Quản lý các kỳ kế toán theo tháng
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Tạo kỳ mới
        </Button>
      </div>

      {/* Current Period Card */}
      {currentPeriod && (
        <Card className="border-primary/50 bg-primary/5">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">Kỳ hiện tại</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <p className="text-2xl font-bold">
                  {formatPeriodLabel(currentPeriod.month, currentPeriod.year)}
                </p>
                <p className="text-sm text-muted-foreground">
                  Mở từ: {formatDate(currentPeriod.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">Thu trong kỳ</p>
                  <AmountDisplay
                    amount={currentPeriod.total_payments}
                    size="lg"
                    className="font-semibold"
                  />
                </div>
                <Button
                  variant="outline"
                  onClick={() => handleCloseClick(currentPeriod)}
                >
                  <Lock className="h-4 w-4 mr-2" />
                  Đóng kỳ
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4">
        <Calendar className="h-4 w-4 text-muted-foreground" />
        <Select
          value={yearFilter?.toString() ?? "all"}
          onValueChange={(value) =>
            setYearFilter(value === "all" ? undefined : parseInt(value))
          }
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Lọc theo năm" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Tất cả các năm</SelectItem>
            {getYearOptions().map((year) => (
              <SelectItem key={year} value={year.toString()}>
                Năm {year}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Period List */}
      {isLoading ? (
        <AccountingPeriodSkeleton />
      ) : periods && periods.length > 0 ? (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kỳ kế toán</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead className="text-right">Tổng thu</TableHead>
                <TableHead className="text-right">Tổng hoàn</TableHead>
                <TableHead className="text-right">Thu ròng</TableHead>
                <TableHead>Ngày đóng</TableHead>
                <TableHead className="w-[100px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periods.map((period) => (
                <TableRow key={period.id}>
                  <TableCell className="font-medium">
                    {formatPeriodLabel(period.month, period.year)}
                  </TableCell>
                  <TableCell>
                    {period.is_closed ? (
                      <Badge variant="secondary">
                        <Lock className="h-3 w-3 mr-1" />
                        Đã đóng
                      </Badge>
                    ) : (
                      <Badge variant="default">
                        <CheckCircle className="h-3 w-3 mr-1" />
                        Đang mở
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <AmountDisplay
                      amount={period.total_payments}
                      showCurrency={false}
                      size="sm"
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <AmountDisplay
                      amount={period.total_refunds}
                      showCurrency={false}
                      size="sm"
                      className={cn(
                        parseFloat(period.total_refunds) > 0 && "text-destructive"
                      )}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <AmountDisplay
                      amount={period.net_revenue}
                      showCurrency={false}
                      size="sm"
                      className="font-medium"
                    />
                  </TableCell>
                  <TableCell className="text-sm">
                    {period.closed_at ? formatDate(period.closed_at) : "-"}
                  </TableCell>
                  <TableCell>
                    {!period.is_closed && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleCloseClick(period)}
                      >
                        <Lock className="h-4 w-4" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-12 text-center">
            <Calendar className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground">Chưa có kỳ kế toán nào</p>
            <Button
              variant="link"
              onClick={() => setCreateDialogOpen(true)}
              className="mt-2"
            >
              Tạo kỳ kế toán đầu tiên
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Create Period Dialog */}
      <CreatePeriodDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />

      {/* Close Period Dialog */}
      {selectedPeriod && (
        <ClosePeriodDialog
          open={closeDialogOpen}
          onOpenChange={(open) => {
            setCloseDialogOpen(open)
            if (!open) setSelectedPeriod(null)
          }}
          period={selectedPeriod}
        />
      )}
    </div>
  )
}

// =============================================================================
// CREATE PERIOD DIALOG
// =============================================================================

interface CreatePeriodDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function CreatePeriodDialog({ open, onOpenChange }: CreatePeriodDialogProps) {
  const createMutation = useCreatePeriod()
  const currentDate = new Date()
  const [month, setMonth] = React.useState(currentDate.getMonth() + 1)
  const [year, setYear] = React.useState(currentDate.getFullYear())

  const handleCreate = async () => {
    try {
      await createMutation.mutateAsync({ month, year })
      toast.success("Đã tạo kỳ kế toán mới")
      onOpenChange(false)
    } catch {
      // Error handled by mutation
    }
  }

  // Reset form when dialog opens
  React.useEffect(() => {
    if (open) {
      const now = new Date()
      setMonth(now.getMonth() + 1)
      setYear(now.getFullYear())
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5" />
            Tạo kỳ kế toán mới
          </DialogTitle>
          <DialogDescription>
            Chỉ có thể có một kỳ kế toán đang mở tại một thời điểm. Kỳ trước phải
            được đóng trước khi tạo kỳ mới.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Tháng</Label>
              <Select
                value={month.toString()}
                onValueChange={(v) => setMonth(parseInt(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                    <SelectItem key={m} value={m.toString()}>
                      {MONTH_LABELS[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Năm</Label>
              <Select
                value={year.toString()}
                onValueChange={(v) => setYear(parseInt(v))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {getYearOptions().map((y) => (
                    <SelectItem key={y} value={y.toString()}>
                      {y}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={createMutation.isPending}
          >
            Hủy
          </Button>
          <Button onClick={handleCreate} disabled={createMutation.isPending}>
            {createMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Tạo kỳ
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// =============================================================================
// CLOSE PERIOD DIALOG
// =============================================================================

interface ClosePeriodDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  period: AccountingPeriod
}

function ClosePeriodDialog({
  open,
  onOpenChange,
  period,
}: ClosePeriodDialogProps) {
  const closeMutation = useClosePeriod()
  const [notes, setNotes] = React.useState("")

  const handleClose = async () => {
    try {
      await closeMutation.mutateAsync({
        periodId: period.id,
        notes: notes || undefined,
      })
      toast.success("Đã đóng kỳ kế toán")
      onOpenChange(false)
    } catch {
      // Error handled by mutation
    }
  }

  // Reset form when dialog opens
  React.useEffect(() => {
    if (open) {
      setNotes("")
    }
  }, [open])

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Lock className="h-5 w-5" />
            Đóng kỳ kế toán
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-3">
            <p>
              Bạn có chắc chắn muốn đóng kỳ kế toán{" "}
              <strong>{formatPeriodLabel(period.month, period.year)}</strong>?
            </p>
            <div className="bg-warning-50 dark:bg-warning-950/30 border border-warning-200 dark:border-warning-800 rounded-lg p-3">
              <div className="flex gap-2">
                <AlertTriangle className="h-5 w-5 text-warning-600 shrink-0 mt-0.5" />
                <div className="text-sm text-warning-800 dark:text-warning-200">
                  <p className="font-medium">Lưu ý quan trọng:</p>
                  <ul className="list-disc list-inside mt-1 space-y-1">
                    <li>Kỳ đã đóng không thể mở lại</li>
                    <li>
                      Không thể ghi nhận giao dịch mới cho kỳ đã đóng
                    </li>
                    <li>Các điều chỉnh sẽ phải ghi nhận vào kỳ tiếp theo</li>
                  </ul>
                </div>
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="py-4">
          <Label htmlFor="notes">Ghi chú (tùy chọn)</Label>
          <Textarea
            id="notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Nhập ghi chú khi đóng kỳ..."
            className="mt-2"
            maxLength={500}
          />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={closeMutation.isPending}>
            Hủy
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleClose}
            disabled={closeMutation.isPending}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {closeMutation.isPending && (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            )}
            Đóng kỳ
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

// =============================================================================
// SKELETON
// =============================================================================

function AccountingPeriodSkeleton() {
  return (
    <Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Kỳ kế toán</TableHead>
            <TableHead>Trạng thái</TableHead>
            <TableHead className="text-right">Tổng thu</TableHead>
            <TableHead className="text-right">Tổng hoàn</TableHead>
            <TableHead className="text-right">Thu ròng</TableHead>
            <TableHead>Ngày đóng</TableHead>
            <TableHead className="w-[100px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...Array(5)].map((_, i) => (
            <TableRow key={i}>
              {[...Array(7)].map((_, j) => (
                <TableCell key={j}>
                  <Skeleton className="h-4 w-full" />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

export default AccountingPeriodClient
