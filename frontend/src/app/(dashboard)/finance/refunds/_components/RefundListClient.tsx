"use client"

import * as React from "react"
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  XCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import { cn } from "@/lib/utils"
import {
  useApproveRefund,
  useCreateRefund,
  useProcessRefund,
  useRefunds,
  useRejectRefund,
} from "@/hooks/finance/useRefunds"
import {
  FEE_TYPE_LABELS,
  type FeeType,
  type RefundFilters,
  type RefundRequest,
  type RefundStatus,
} from "@/types/finance.types"

const STATUS_LABELS: Record<RefundStatus, string> = {
  pending: "Chờ duyệt",
  approved: "Chờ chi tiền",
  rejected: "Đã từ chối",
  refunded: "Đã chi",
}

/** Bộ lọc mặt bảng. `needs_action` gộp hai trạng thái còn việc phải làm — mặc
 *  định cũ là `pending` đơn lẻ, mà thực tế hàng chờ nằm gần hết ở `approved`,
 *  nên mở màn hình ra là thấy trống và tưởng đã hết việc. */
type FilterKey = "needs_action" | RefundStatus | "all"

const FILTER_TO_PARAM: Record<FilterKey, RefundFilters["status"]> = {
  needs_action: "pending,approved",
  pending: "pending",
  approved: "approved",
  rejected: "rejected",
  refunded: "refunded",
  all: undefined,
}

const currency = new Intl.NumberFormat("vi-VN")
const dateFmt = new Intl.DateTimeFormat("vi-VN")

function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "string" ? Number(value) : value
  return Number.isFinite(n) ? currency.format(n) : "—"
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—"
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? "—" : dateFmt.format(d)
}

/** Số ngày phiếu đã nằm chờ ở trạng thái hiện tại. Thuần trình bày: đếm từ mốc
 *  thời gian backend trả về, không suy luận trạng thái. */
function daysWaiting(refund: RefundRequest): number | null {
  const since =
    refund.status === "approved"
      ? refund.approved_at ?? refund.created_at
      : refund.status === "pending"
        ? refund.created_at
        : null
  if (!since) return null
  const ms = Date.now() - new Date(since).getTime()
  return ms > 0 ? Math.floor(ms / 86_400_000) : 0
}

export function RefundListClient() {
  const [filter, setFilter] = React.useState<FilterKey>("needs_action")
  const [page, setPage] = React.useState(1)
  const [query, setQuery] = React.useState("")
  const [createOpen, setCreateOpen] = React.useState(false)
  const [action, setAction] = React.useState<
    null | { type: "reject" | "process"; refund: RefundRequest }
  >(null)
  const [createForm, setCreateForm] = React.useState({ payment_id: "", amount: "", reason: "" })
  const [rejectionReason, setRejectionReason] = React.useState("")
  const [refundReference, setRefundReference] = React.useState("")

  const PAGE_SIZE = 50
  const { data, isLoading, error, refetch } = useRefunds({
    status: FILTER_TO_PARAM[filter],
    page,
    page_size: PAGE_SIZE,
  })
  const createRefund = useCreateRefund()
  const approveRefund = useApproveRefund()
  const rejectRefund = useRejectRefund()
  const processRefund = useProcessRefund()

  const summary = data?.summary
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rangeFrom = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const rangeTo = Math.min(page * PAGE_SIZE, total)

  // Tìm nhanh trong trang đang tải — nhãn dưới ô nhập nói rõ phạm vi này.
  const items = React.useMemo(() => {
    const list = data?.items ?? []
    const q = query.trim().toLowerCase()
    if (!q) return list
    return list.filter((r) =>
      [
        r.student_name,
        // Mã phiếu hoàn + mã tham chiếu: kế toán cầm "HT-42-20260729" trên sao kê
        // phải tra ngược được về đúng dòng này — đó là lý do mã đó tồn tại.
        `#${r.id}`,
        String(r.id),
        r.refund_reference,
        r.suggested_reference,
        `#${r.payment_id}`,
        r.profile_id ? `#${r.profile_id}` : null,
        r.invoice_number,
        r.reason,
      ]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(q)),
    )
  }, [data?.items, query])

  const openReject = (refund: RefundRequest) => {
    // Xoá lý do của dòng trước. Không có bước này thì bấm Huỷ ở dòng A rồi mở dòng
    // B sẽ thấy nguyên văn lý do của A, nút gửi đang bật — một cú click là gán lý
    // do của A cho B và báo cho người yêu cầu của B.
    setRejectionReason("")
    setAction({ type: "reject", refund })
  }

  const openProcess = (refund: RefundRequest) => {
    // Điền sẵn mã backend gợi ý. Kế toán gõ đè khi có mã UNC thật; để nguyên
    // hoặc xoá trắng thì backend ghi đúng mã đang hiển thị ở đây.
    setRefundReference(refund.suggested_reference ?? "")
    setAction({ type: "process", refund })
  }

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
    const trimmed = refundReference.trim()
    // Gửi mã CHỈ KHI kế toán thực sự sửa. Nếu ô còn nguyên gợi ý (hoặc để trống),
    // không gửi khoá — để backend tự sinh tại thời điểm chi.
    //
    // Gợi ý được sinh lúc TẢI TRANG: một tab mở từ hôm qua vẫn hiển thị mã mang
    // ngày hôm qua, gửi lại nguyên si là ghi sai ngày vào sổ, mà mã này dùng đúng
    // để đối chiếu sao kê theo ngày.
    const edited = trimmed !== "" && trimmed !== (action.refund.suggested_reference ?? "")
    await processRefund.mutateAsync({
      id: action.refund.id,
      data: {
        refund_id: action.refund.id,
        ...(edited ? { refund_reference: trimmed } : {}),
      },
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
            <p className="font-medium text-destructive">Không tải được danh sách hoàn phí</p>
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
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Hoàn phí</h1>
          <p className="text-muted-foreground">Duyệt yêu cầu và chi tiền trả lại học sinh</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Làm mới
          </Button>
          {data?.can_create && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Tạo yêu cầu
            </Button>
          )}
        </div>
      </div>

      {/* Hàng chờ: bấm để lọc. Đứng trước bảng vì đây là câu hỏi đầu tiên mỗi
          sáng — còn bao nhiêu việc, bao nhiêu tiền đang treo. */}
      <div className="grid gap-3 sm:grid-cols-3">
        <QueueTile
          loading={isLoading}
          label="Chờ duyệt"
          count={summary?.pending_count ?? 0}
          amount={summary?.pending_amount}
          active={filter === "pending"}
          onClick={() => {
            setFilter("pending")
            setPage(1)
          }}
        />
        <QueueTile
          loading={isLoading}
          label="Chờ chi tiền"
          count={summary?.approved_count ?? 0}
          amount={summary?.approved_amount}
          active={filter === "approved"}
          emphasis
          onClick={() => {
            setFilter("approved")
            setPage(1)
          }}
        />
        <QueueTile
          loading={isLoading}
          label="Đã chi"
          count={summary?.refunded_count ?? 0}
          amount={summary?.refunded_amount}
          active={filter === "refunded"}
          onClick={() => {
            setFilter("refunded")
            setPage(1)
          }}
        />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-1">
          {(
            [
              ["needs_action", "Còn việc"],
              ["all", "Tất cả"],
              ["rejected", "Đã từ chối"],
            ] as [FilterKey, string][]
          ).map(([key, label]) => (
            <Button
              key={key}
              size="sm"
              variant={filter === key ? "default" : "ghost"}
              onClick={() => {
                setFilter(key)
                setPage(1)
              }}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="Tìm tên, mã phiếu, mã hồ sơ, hoá đơn"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Tìm trong danh sách đang hiển thị"
          />
        </div>
      </div>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Học sinh</TableHead>
                <TableHead className="hidden lg:table-cell">Khoản đã thu</TableHead>
                <TableHead className="text-right">Hoàn / đã thu</TableHead>
                <TableHead className="hidden md:table-cell">Lý do</TableHead>
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
              ) : items.length ? (
                items.map((refund) => (
                  <RefundRow
                    key={refund.id}
                    refund={refund}
                    onApprove={() => approveRefund.mutate(refund.id)}
                    onReject={() => openReject(refund)}
                    onProcess={() => openProcess(refund)}
                  />
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center">
                    <p className="font-medium">
                      {query ? "Không có phiếu nào khớp" : "Không có phiếu nào ở mục này"}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {query ? (
                        "Thử bỏ bớt từ khoá."
                      ) : (
                        <>
                          Còn {summary?.pending_count ?? 0} phiếu chờ duyệt và{" "}
                          {summary?.approved_count ?? 0} phiếu chờ chi tiền.{" "}
                          <button
                            type="button"
                            className="underline underline-offset-4"
                            onClick={() => setFilter("all")}
                          >
                            Xem tất cả
                          </button>
                        </>
                      )}
                    </p>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Dải tổng quan đếm toàn phạm vi, nên phải với tới được dòng thứ 51 trở đi —
          nếu không thì những phiếu CŨ NHẤT (đúng thứ badge "chờ N ngày" muốn nêu)
          nằm ngoài tầm với mà màn hình vẫn khẳng định chúng tồn tại. */}
      {total > 0 && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {query ? (
              <>
                Tìm thấy {items.length} trong {data?.items.length ?? 0} phiếu đang hiển thị.
                Ô tìm chỉ lọc trang này, không phải toàn bộ hệ thống.
              </>
            ) : (
              <>
                Hiển thị {rangeFrom}–{rangeTo} trên {total} phiếu
              </>
            )}
          </p>
          {totalPages > 1 && !query && (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || isLoading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Trang trước
              </Button>
              <span className="text-sm tabular-nums text-muted-foreground">
                {page}/{totalPages}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= totalPages || isLoading}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Trang sau
              </Button>
            </div>
          )}
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Tạo yêu cầu hoàn phí</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Field label="Mã phiếu thu">
              <Input
                inputMode="numeric"
                value={createForm.payment_id}
                onChange={(event) =>
                  setCreateForm((prev) => ({
                    ...prev,
                    payment_id: event.target.value.replace(/\D/g, ""),
                  }))
                }
              />
            </Field>
            <Field label="Số tiền hoàn">
              <Input
                inputMode="decimal"
                value={createForm.amount}
                onChange={(event) =>
                  setCreateForm((prev) => ({ ...prev, amount: event.target.value }))
                }
              />
            </Field>
            <Field label="Lý do">
              <Textarea
                value={createForm.reason}
                onChange={(event) =>
                  setCreateForm((prev) => ({ ...prev, reason: event.target.value }))
                }
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Huỷ
            </Button>
            <Button
              onClick={handleCreate}
              disabled={
                !createForm.payment_id ||
                !createForm.amount ||
                !createForm.reason ||
                createRefund.isPending
              }
            >
              Tạo yêu cầu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "reject"} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Từ chối yêu cầu hoàn phí</DialogTitle>
            <DialogDescription>
              {action?.refund.student_name ?? "Học sinh"} · {money(action?.refund.amount)} đ
            </DialogDescription>
          </DialogHeader>
          <Field label="Lý do từ chối">
            <Textarea
              value={rejectionReason}
              onChange={(event) => setRejectionReason(event.target.value)}
              placeholder="Ghi rõ để người yêu cầu biết cần sửa gì"
            />
          </Field>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={handleReject}
              disabled={!rejectionReason.trim() || rejectRefund.isPending}
            >
              Từ chối
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={action?.type === "process"} onOpenChange={(open) => !open && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Chi tiền hoàn</DialogTitle>
            <DialogDescription>
              Xác nhận đã trả tiền cho học sinh. Thao tác này ghi giảm số đã thu của khoản phí.
            </DialogDescription>
          </DialogHeader>

          {action?.type === "process" && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md border bg-muted/40 p-3 text-sm">
              <dt className="text-muted-foreground">Học sinh</dt>
              <dd className="font-medium">
                {action.refund.student_name ?? "—"}
                {action.refund.profile_id ? (
                  <span className="ml-1 font-normal text-muted-foreground">
                    · hồ sơ #{action.refund.profile_id}
                  </span>
                ) : null}
              </dd>
              <dt className="text-muted-foreground">Số tiền chi</dt>
              <dd className="font-semibold tabular-nums">{money(action.refund.amount)} đ</dd>
              <dt className="text-muted-foreground">Phiếu thu gốc</dt>
              <dd className="tabular-nums">
                {money(action.refund.payment_amount)} đ
                <span className="ml-1 text-muted-foreground">
                  · {formatDate(action.refund.payment_date)}
                </span>
              </dd>
            </dl>
          )}

          <Field label="Mã tham chiếu">
            <Input
              value={refundReference}
              onChange={(event) => setRefundReference(event.target.value)}
              placeholder={action?.refund.suggested_reference ?? "Để trống để dùng mã gợi ý"}
            />
          </Field>
          <p className="-mt-1 text-xs text-muted-foreground">
            Đã điền sẵn mã gợi ý. Xoá trắng cũng được — hệ thống sẽ dùng{" "}
            <span className="font-mono">{action?.refund.suggested_reference ?? "mã tự sinh"}</span>.
            Nhập mã uỷ nhiệm chi của ngân hàng nếu có.
          </p>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>
              Huỷ
            </Button>
            <Button onClick={handleProcess} disabled={processRefund.isPending}>
              Xác nhận đã chi
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function QueueTile({
  label,
  count,
  amount,
  active,
  emphasis,
  loading,
  onClick,
}: {
  label: string
  count: number
  amount: string | undefined
  active: boolean
  emphasis?: boolean
  loading?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-lg border p-4 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        active ? "border-primary bg-primary/5" : "hover:bg-muted/50",
      )}
    >
      <div className="text-sm text-muted-foreground">{label}</div>
      {loading ? (
        // Lần tải đầu chưa có số: hiện khung chờ thay vì khẳng định "0 phiếu" —
        // con số 0 sai ở đây đúng bằng việc nói với kế toán là hết việc.
        <>
          <div className="mt-2 h-7 w-16 animate-pulse rounded bg-muted" />
          <div className="mt-1.5 h-4 w-24 animate-pulse rounded bg-muted" />
        </>
      ) : (
      <div className="mt-1 flex items-baseline gap-2">
        <span
          className={cn(
            "text-2xl font-semibold tabular-nums",
            emphasis && count > 0 && "text-primary",
          )}
        >
          {count}
        </span>
        <span className="text-sm text-muted-foreground">phiếu</span>
      </div>
      )}
      {!loading && (
        <div className="mt-0.5 text-sm tabular-nums text-muted-foreground">
          {money(amount)} đ
        </div>
      )}
    </button>
  )
}

function RefundRow({
  refund,
  onApprove,
  onReject,
  onProcess,
}: {
  refund: RefundRequest
  onApprove: () => void
  onReject: () => void
  onProcess: () => void
}) {
  const waited = daysWaiting(refund)
  const asked = Number(refund.amount ?? 0)
  // So với SỐ CÒN HOÀN ĐƯỢC do backend tính (phiếu thu − phần đã chi hoàn), không
  // phải tổng phiếu thu. Đó đúng là ngưỡng `process_approved_refund` gác: một
  // phiếu thu 1.000.000 đã hoàn 600.000 thì phiếu 500.000 sẽ bị từ chối, dù so với
  // tổng thu nó trông vô hại. Tự suy ở đây là đẩy phép tính tiền vào giao diện rồi
  // lệch với backend.
  const refundable =
    refund.refundable_amount !== null ? Number(refund.refundable_amount) : null
  const alreadyRefunded = Number(refund.already_refunded_amount ?? 0)
  const ratio = refundable && refundable > 0 ? Math.min(asked / refundable, 1) : 0
  const overAsking = refundable !== null && asked > refundable

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{refund.student_name ?? "—"}</div>
        <div className="text-xs text-muted-foreground">
          {refund.profile_id ? `Hồ sơ #${refund.profile_id}` : `Phiếu thu #${refund.payment_id}`}
          {refund.major_name ? ` · ${refund.major_name}` : ""}
        </div>
      </TableCell>

      <TableCell className="hidden lg:table-cell">
        <div className="text-sm">
          {refund.fee_type
            ? FEE_TYPE_LABELS[refund.fee_type as FeeType] ?? refund.fee_type
            : "—"}
        </div>
        <div className="text-xs text-muted-foreground">
          {refund.invoice_number ?? "—"}
          {refund.payment_method_name ? ` · ${refund.payment_method_name}` : ""}
          {refund.payment_date ? ` · ${formatDate(refund.payment_date)}` : ""}
        </div>
      </TableCell>

      <TableCell className="text-right">
        <div className={cn("font-semibold tabular-nums", overAsking && "text-destructive")}>
          {money(refund.amount)}
        </div>
        <div className="text-xs tabular-nums text-muted-foreground">
          trên {money(refund.payment_amount)}
          {alreadyRefunded > 0 ? ` · đã hoàn ${money(alreadyRefunded)}` : ""}
        </div>
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div
            className={cn("h-full rounded-full", overAsking ? "bg-destructive" : "bg-primary/70")}
            style={{ width: `${overAsking ? 100 : Math.round(ratio * 100)}%` }}
          />
        </div>
        {overAsking && (
          <div className="mt-1 text-xs font-medium text-destructive">
            Vượt số còn hoàn được ({money(refundable)})
          </div>
        )}
      </TableCell>

      <TableCell className="hidden max-w-[22ch] md:table-cell">
        <div className="line-clamp-2 text-sm" title={refund.reason}>
          {refund.reason}
        </div>
        {refund.requested_by_name && (
          <div className="mt-0.5 text-xs text-muted-foreground">
            {refund.requested_by_name}
            {refund.approved_by_name ? ` → ${refund.approved_by_name}` : ""}
          </div>
        )}
      </TableCell>

      <TableCell>
        <Badge variant={refund.status === "rejected" ? "destructive" : "outline"}>
          {STATUS_LABELS[refund.status]}
        </Badge>
        {waited !== null && (
          <div
            className={cn(
              "mt-1 flex items-center gap-1 text-xs",
              waited >= 3 ? "font-medium text-amber-600 dark:text-amber-500" : "text-muted-foreground",
            )}
          >
            <Clock className="h-3 w-3" />
            {waited === 0 ? "hôm nay" : `chờ ${waited} ngày`}
          </div>
        )}
        {refund.status === "refunded" && refund.refund_reference && (
          <div className="mt-1 font-mono text-xs text-muted-foreground">
            {refund.refund_reference}
          </div>
        )}
      </TableCell>

      <TableCell>
        <div className="flex justify-end gap-2">
          {refund.can_approve && (
            <Button size="sm" variant="outline" onClick={onApprove}>
              <CheckCircle className="mr-2 h-4 w-4" />
              Duyệt
            </Button>
          )}
          {refund.can_reject && (
            <Button size="sm" variant="outline" onClick={onReject}>
              <XCircle className="mr-2 h-4 w-4" />
              Từ chối
            </Button>
          )}
          {refund.can_process && (
            <Button size="sm" onClick={onProcess}>
              <RotateCcw className="mr-2 h-4 w-4" />
              Chi tiền
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
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
