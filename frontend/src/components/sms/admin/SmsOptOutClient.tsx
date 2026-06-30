// src/components/sms/admin/SmsOptOutClient.tsx
"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useSmsOptOuts } from "@/hooks/useSmsAdmin"

import {
  OPT_OUT_SOURCE_LABELS,
  formatDateTimeVN,
  formatInt,
  optOutSourceLabel,
} from "./labels"
import { SmsManualOptOutDialog } from "./SmsManualOptOutDialog"

const ALL = "all"
const PAGE_SIZE = 50

/** Debounce cục bộ — tránh gọi API mỗi lần gõ. */
function useDebouncedValue<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

const SOURCE_FILTER_OPTIONS = Object.keys(OPT_OUT_SOURCE_LABELS)

/**
 * Quản lý danh sách số từ chối nhận tin (suppression toàn cục) + thêm thủ
 * công. Admin-only (BE require_admin; sidebar roles:["admin"]).
 */
export function SmsOptOutClient() {
  const [searchInput, setSearchInput] = useState("")
  const [source, setSource] = useState<string>(ALL)
  const [page, setPage] = useState(0) // 0-based
  const [dialogOpen, setDialogOpen] = useState(false)

  const search = useDebouncedValue(searchInput.trim())

  // Đổi filter/search → về trang đầu. Reset NGAY trong event handler (không
  // dùng effect → tránh cascading render).
  const handleSearchChange = (value: string) => {
    setSearchInput(value)
    setPage(0)
  }
  const handleSourceChange = (value: string) => {
    setSource(value)
    setPage(0)
  }

  const params = useMemo(
    () => ({
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
      search: search || undefined,
      source: source === ALL ? undefined : source,
    }),
    [page, search, source],
  )

  const { data, isLoading, isError, refetch, isFetching } =
    useSmsOptOuts(params)

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const items = data?.items ?? []

  return (
    <div className="space-y-4">
      {/* Thanh công cụ */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-2xl">
              <div className="space-y-1.5">
                <Label htmlFor="optout-search">Tìm số điện thoại</Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="optout-search"
                    className="pl-8"
                    placeholder="Nhập số điện thoại…"
                    value={searchInput}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    maxLength={32}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="optout-source">Nguồn</Label>
                <Select value={source} onValueChange={handleSourceChange}>
                  <SelectTrigger id="optout-source">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Tất cả nguồn</SelectItem>
                    {SOURCE_FILTER_OPTIONS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {optOutSourceLabel(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" /> Thêm thủ công
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Bảng */}
      <Card>
        <CardContent className="pt-6">
          {isError ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <AlertCircle className="text-destructive h-8 w-8" />
              <p className="text-muted-foreground text-sm">
                Không thể tải danh sách. Vui lòng thử lại.
              </p>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                Thử lại
              </Button>
            </div>
          ) : isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <p className="text-muted-foreground py-10 text-center text-sm">
              {search || source !== ALL
                ? "Không có số nào khớp bộ lọc."
                : "Chưa có số từ chối nhận tin nào."}
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Số điện thoại</TableHead>
                      <TableHead>Nguồn</TableHead>
                      <TableHead>Tham chiếu</TableHead>
                      <TableHead>Lý do</TableHead>
                      <TableHead>Thời điểm</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((o) => (
                      <TableRow key={o.id}>
                        <TableCell className="font-medium tabular-nums">
                          {o.phone_normalized}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">
                            {optOutSourceLabel(o.source)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-[200px] truncate text-sm">
                          {o.source_reference || "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-[280px] truncate text-sm">
                          {o.reason || "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                          {formatDateTimeVN(o.observed_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Phân trang */}
              <div className="mt-4 flex items-center justify-between">
                <p className="text-muted-foreground text-sm">
                  Tổng {formatInt(total)} số · Trang {page + 1}/{totalPages}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0 || isFetching}
                  >
                    <ChevronLeft className="h-4 w-4" /> Trước
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((p) => Math.min(totalPages - 1, p + 1))
                    }
                    disabled={page >= totalPages - 1 || isFetching}
                  >
                    Sau <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <SmsManualOptOutDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  )
}
