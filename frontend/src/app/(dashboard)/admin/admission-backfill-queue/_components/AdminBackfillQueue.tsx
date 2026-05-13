"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — Admin backfill queue UI.
 *
 * Consumes 4 BE-2 endpoints (LIVE prod via PR #271 27a7a38e):
 *   - GET    /api/v2/admin/admission-backfill-exceptions  (list + filter)
 *   - PATCH  /api/v2/admin/admission-backfill-exceptions/{id}/resolve
 *   - POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve
 *   - GET    /api/v2/admin/admission-backfill-exceptions/export.csv
 *
 * UX:
 *   1. Filter row (exception_type input + is_resolved tri-state + page size)
 *   2. Toolbar with selected counter + bulk-resolve + export CSV
 *   3. Table with checkbox column + per-row resolve button + expand JSON
 *   4. Pagination (prev / next / page indicator)
 *
 * Per Plan v0.7 design: admin reviews backfill exceptions left by Phase 1/2
 * scripts and decides outcome per row (via notes — BE has 1 mutation "resolve",
 * NOT separate Approve/Reject as plan text suggested — notes carry the
 * decision rationale).
 */
import { Fragment, useMemo, useState } from "react"
import { ChevronDown, ChevronUp, Download, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { exportBackfillExceptionsCsv } from "@/lib/api/admission-backfill"
import { parseApiError } from "@/lib/utils/api-errors"
import type {
  AdmissionBackfillException,
  BackfillListFilters,
} from "@/lib/zod/admission-backfill"
import {
  useBackfillExceptions,
  useBulkResolveBackfillExceptions,
  useResolveBackfillException,
} from "@/hooks/admissions/useAdmissionBackfill"
import { BackfillResolveDialog } from "./BackfillResolveDialog"

type ResolvedFilter = "all" | "open" | "closed"

function resolvedToBackend(rf: ResolvedFilter): boolean | undefined {
  if (rf === "open") return false
  if (rf === "closed") return true
  return undefined
}

export function AdminBackfillQueue() {
  // Filter state
  const [exceptionType, setExceptionType] = useState<string>("")
  const [resolvedFilter, setResolvedFilter] = useState<ResolvedFilter>("open")
  const [pageSize, setPageSize] = useState<number>(50)
  const [page, setPage] = useState<number>(0)

  const filters = useMemo<BackfillListFilters>(
    () => ({
      exception_type: exceptionType.trim() || undefined,
      is_resolved: resolvedToBackend(resolvedFilter),
      limit: pageSize,
      offset: page * pageSize,
    }),
    [exceptionType, resolvedFilter, pageSize, page],
  )

  const { data, isLoading, isError, error } = useBackfillExceptions(filters)

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [resolveTarget, setResolveTarget] =
    useState<AdmissionBackfillException | null>(null)
  const [bulkOpen, setBulkOpen] = useState<boolean>(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exporting, setExporting] = useState<boolean>(false)

  const resolveMutation = useResolveBackfillException()
  const bulkMutation = useBulkResolveBackfillExceptions()

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const allSelectedOnPage =
    items.length > 0 && items.every((it) => selected.has(it.id))
  const someSelected = items.some((it) => selected.has(it.id))

  const toggleRow = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAllOnPage = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allSelectedOnPage) {
        items.forEach((it) => next.delete(it.id))
      } else {
        items.forEach((it) => next.add(it.id))
      }
      return next
    })
  }

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSingleResolveSubmit = (reason: string) => {
    if (!resolveTarget) return
    resolveMutation.mutate(
      { exceptionId: resolveTarget.id, payload: { resolution_notes: reason } },
      {
        onSuccess: () => {
          setResolveTarget(null)
          // Drop from selection if it was selected
          setSelected((prev) => {
            const next = new Set(prev)
            next.delete(resolveTarget.id)
            return next
          })
        },
      },
    )
  }

  const handleBulkSubmit = (reason: string) => {
    if (selected.size === 0) return
    bulkMutation.mutate(
      {
        exception_ids: Array.from(selected),
        resolution_notes: reason,
      },
      {
        onSuccess: () => {
          setBulkOpen(false)
          setSelected(new Set())
        },
      },
    )
  }

  const handleExport = async () => {
    setExportError(null)
    setExporting(true)
    try {
      const blob = await exportBackfillExceptionsCsv({
        exception_type: filters.exception_type,
        is_resolved: filters.is_resolved,
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      const ts = new Date().toISOString().replace(/[:.]/g, "-")
      link.href = url
      link.download = `backfill_exceptions_${ts}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(parseApiError(err, "Không thể tải file CSV."))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-4" data-testid="admin-backfill-queue">
      {/* Filter row */}
      <section
        className="grid gap-3 rounded-md border bg-card p-3 sm:grid-cols-[1fr_180px_120px]"
        aria-label="Bộ lọc"
      >
        <div className="space-y-1">
          <Label htmlFor="filter-exception-type">Loại ngoại lệ</Label>
          <Input
            id="filter-exception-type"
            placeholder="VD: selected_subject_group_ambiguous"
            value={exceptionType}
            onChange={(e) => {
              setExceptionType(e.target.value)
              setPage(0)
            }}
            data-testid="filter-exception-type"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-resolved">Trạng thái</Label>
          <Select
            value={resolvedFilter}
            onValueChange={(v) => {
              setResolvedFilter(v as ResolvedFilter)
              setPage(0)
            }}
          >
            <SelectTrigger id="filter-resolved" data-testid="filter-resolved">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Đang mở</SelectItem>
              <SelectItem value="closed">Đã đóng</SelectItem>
              <SelectItem value="all">Tất cả</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-page-size">Hàng / trang</Label>
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(Number(v))
              setPage(0)
            }}
          >
            <SelectTrigger id="filter-page-size" data-testid="filter-page-size">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="25">25</SelectItem>
              <SelectItem value="50">50</SelectItem>
              <SelectItem value="100">100</SelectItem>
              <SelectItem value="200">200</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </section>

      {/* Toolbar */}
      <section
        className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/30 p-2"
        aria-label="Thao tác"
      >
        <div className="text-sm">
          <span className="font-medium">{total}</span> dòng tổng cộng
          {selected.size > 0 && (
            <span className="ml-3 text-muted-foreground">
              • Đã chọn{" "}
              <strong data-testid="selected-counter">{selected.size}</strong>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setBulkOpen(true)}
            disabled={selected.size === 0 || bulkMutation.isPending}
            data-testid="bulk-resolve-button"
          >
            {bulkMutation.isPending ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            Đóng hàng loạt ({selected.size})
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={exporting}
            data-testid="export-csv-button"
          >
            {exporting ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-1 h-4 w-4" />
            )}
            Tải CSV
          </Button>
        </div>
      </section>

      {exportError && (
        <p role="alert" className="text-sm text-destructive">
          {exportError}
        </p>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  aria-label="Chọn tất cả trên trang"
                  checked={
                    allSelectedOnPage
                      ? true
                      : someSelected
                      ? "indeterminate"
                      : false
                  }
                  onCheckedChange={toggleAllOnPage}
                  data-testid="select-all-checkbox"
                />
              </TableHead>
              <TableHead className="w-16">ID</TableHead>
              <TableHead>Loại ngoại lệ</TableHead>
              <TableHead className="w-24">Hồ sơ</TableHead>
              <TableHead className="w-40">Tạo lúc</TableHead>
              <TableHead className="w-40">Trạng thái</TableHead>
              <TableHead className="w-40">Hành động</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-sm text-muted-foreground">
                  Đang tải…
                </TableCell>
              </TableRow>
            )}
            {isError && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-sm text-destructive"
                >
                  {parseApiError(error, "Không tải được dữ liệu.")}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !isError && items.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-sm text-muted-foreground"
                  data-testid="empty-row"
                >
                  Không có ngoại lệ nào khớp bộ lọc.
                </TableCell>
              </TableRow>
            )}
            {items.map((row) => {
              const isResolved = row.resolved_at !== null && row.resolved_at !== undefined
              const isExpanded = expanded.has(row.id)
              const isSelected = selected.has(row.id)
              return (
                <Fragment key={row.id}>
                  <TableRow
                    data-testid={`exception-row-${row.id}`}
                  >
                    <TableCell>
                      <Checkbox
                        aria-label={`Chọn dòng ${row.id}`}
                        checked={isSelected}
                        onCheckedChange={() => toggleRow(row.id)}
                        disabled={isResolved}
                        data-testid={`row-checkbox-${row.id}`}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      #{row.id}
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        onClick={() => toggleExpand(row.id)}
                        className="inline-flex items-center gap-1 text-left hover:underline"
                        aria-expanded={isExpanded}
                        aria-controls={`detail-${row.id}`}
                        data-testid={`expand-toggle-${row.id}`}
                      >
                        {isExpanded ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                        <code className="text-xs">{row.exception_type}</code>
                      </button>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      #{row.profile_id}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(row.created_at).toLocaleString("vi-VN")}
                    </TableCell>
                    <TableCell>
                      {isResolved ? (
                        <span
                          className="rounded-full bg-success-100 px-2 py-0.5 text-xs text-success-700"
                          data-testid={`status-resolved-${row.id}`}
                        >
                          Đã đóng
                        </span>
                      ) : (
                        <span
                          className="rounded-full bg-warning-100 px-2 py-0.5 text-xs text-warning-700"
                          data-testid={`status-open-${row.id}`}
                        >
                          Đang mở
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {!isResolved && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setResolveTarget(row)}
                          data-testid={`resolve-button-${row.id}`}
                        >
                          Đóng
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow>
                      <TableCell colSpan={7} className="bg-muted/20">
                        <div
                          id={`detail-${row.id}`}
                          className="space-y-2 p-2"
                          data-testid={`detail-row-${row.id}`}
                        >
                          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
                            Chi tiết JSONB
                          </h4>
                          <pre className="max-h-64 overflow-auto rounded-md bg-background p-2 text-xs">
                            {JSON.stringify(row.details, null, 2)}
                          </pre>
                          {isResolved && (
                            <>
                              <h4 className="text-xs font-semibold uppercase text-muted-foreground">
                                Đã xử lý
                              </h4>
                              <p className="text-xs text-muted-foreground">
                                Bởi: {row.resolved_by_username ?? `User ${row.resolved_by_user_id ?? "?"}`}
                                {" · "}
                                Lúc:{" "}
                                {row.resolved_at
                                  ? new Date(row.resolved_at).toLocaleString("vi-VN")
                                  : "—"}
                              </p>
                              {row.resolution_notes && (
                                <p className="text-xs italic">
                                  &ldquo;{row.resolution_notes}&rdquo;
                                </p>
                              )}
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {total > pageSize && (
        <nav
          className="flex items-center justify-between"
          aria-label="Phân trang"
        >
          <span className="text-sm text-muted-foreground">
            Trang {page + 1} / {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              data-testid="page-prev"
            >
              Trước
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              data-testid="page-next"
            >
              Sau
            </Button>
          </div>
        </nav>
      )}

      {/* Single resolve dialog */}
      <BackfillResolveDialog
        open={resolveTarget !== null}
        onOpenChange={(open) => {
          if (!open) setResolveTarget(null)
        }}
        target={resolveTarget}
        onSubmit={handleSingleResolveSubmit}
        isSubmitting={resolveMutation.isPending}
        errorMessage={
          resolveMutation.isError
            ? parseApiError(resolveMutation.error, "Không thể đóng. Thử lại.")
            : null
        }
      />

      {/* Bulk resolve dialog */}
      <BackfillResolveDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        bulkCount={selected.size}
        onSubmit={handleBulkSubmit}
        isSubmitting={bulkMutation.isPending}
        bulkResult={bulkMutation.data ?? null}
        errorMessage={
          bulkMutation.isError
            ? parseApiError(
                bulkMutation.error,
                "Không thể đóng hàng loạt. Thử lại.",
              )
            : null
        }
      />
    </div>
  )
}
