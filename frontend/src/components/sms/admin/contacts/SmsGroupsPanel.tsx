// src/components/sms/admin/contacts/SmsGroupsPanel.tsx
"use client"

import { useState } from "react"
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Search,
  Users,
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
import { useSmsContactGroups } from "@/hooks/useSmsContacts"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import type { SmsContactGroup } from "@/lib/zod/sms"

import {
  GROUP_TYPE_OPTIONS,
  formatDateTimeVN,
  formatInt,
  groupTypeLabel,
} from "../labels"
import { SmsGroupContactsDialog } from "./SmsGroupContactsDialog"
import { SmsGroupFormDialog } from "./SmsGroupFormDialog"

const ALL = "all"
const PAGE_SIZE = 50

export function SmsGroupsPanel() {
  const [searchInput, setSearchInput] = useState("")
  const [type, setType] = useState<string>(ALL)
  const [active, setActive] = useState<string>(ALL)
  const [page, setPage] = useState(0)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<SmsContactGroup | null>(null)
  const [detailGroup, setDetailGroup] = useState<SmsContactGroup | null>(null)

  const search = useDebouncedValue(searchInput.trim())

  const resetPage = () => setPage(0)
  const onSearch = (v: string) => {
    setSearchInput(v)
    resetPage()
  }
  const onType = (v: string) => {
    setType(v)
    resetPage()
  }
  const onActive = (v: string) => {
    setActive(v)
    resetPage()
  }

  const { data, isLoading, isError, refetch, isFetching } = useSmsContactGroups(
    {
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
      search: search || undefined,
      group_type: type === ALL ? undefined : type,
      is_active: active === ALL ? undefined : active === "active",
    },
  )

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const items = data?.items ?? []

  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }
  const openEdit = (g: SmsContactGroup) => {
    setEditing(g)
    setFormOpen(true)
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-3 lg:max-w-2xl">
              <div className="space-y-1.5">
                <Label htmlFor="grp-search">Tìm nhóm</Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="grp-search"
                    className="pl-8"
                    placeholder="Tên / mã nhóm…"
                    value={searchInput}
                    onChange={(e) => onSearch(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="grp-type">Loại</Label>
                <Select value={type} onValueChange={onType}>
                  <SelectTrigger id="grp-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Tất cả loại</SelectItem>
                    {GROUP_TYPE_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="grp-active">Trạng thái</Label>
                <Select value={active} onValueChange={onActive}>
                  <SelectTrigger id="grp-active">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Tất cả</SelectItem>
                    <SelectItem value="active">Đang hoạt động</SelectItem>
                    <SelectItem value="inactive">Ngừng</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button onClick={openCreate}>
              <Plus className="mr-2 h-4 w-4" /> Tạo nhóm
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {isError ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <AlertCircle className="text-destructive h-8 w-8" />
              <p className="text-muted-foreground text-sm">
                Không thể tải danh sách nhóm.
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
            <div className="space-y-3 py-10 text-center">
              <p className="text-muted-foreground text-sm">
                {page > 0
                  ? "Trang này không còn dữ liệu."
                  : search || type !== ALL || active !== ALL
                    ? "Không có nhóm khớp bộ lọc."
                    : "Chưa có nhóm liên hệ nào."}
              </p>
              {page > 0 && (
                <Button variant="outline" size="sm" onClick={() => setPage(0)}>
                  Về trang đầu
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tên nhóm</TableHead>
                      <TableHead>Loại</TableHead>
                      <TableHead className="text-right">Thành viên</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead>Tạo lúc</TableHead>
                      <TableHead className="text-right">Thao tác</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((g) => (
                      <TableRow key={g.id}>
                        <TableCell>
                          <button
                            type="button"
                            onClick={() => setDetailGroup(g)}
                            className="text-left font-medium hover:underline"
                          >
                            {g.name}
                          </button>
                          <div className="text-muted-foreground text-xs">
                            {g.code}
                          </div>
                        </TableCell>
                        <TableCell>{groupTypeLabel(g.group_type)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {g.member_count != null
                            ? formatInt(g.member_count)
                            : "—"}
                        </TableCell>
                        <TableCell>
                          {g.is_active ? (
                            <Badge variant="default">Hoạt động</Badge>
                          ) : (
                            <Badge variant="secondary">Ngừng</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                          {formatDateTimeVN(g.created_at)}
                        </TableCell>
                        <TableCell className="text-right whitespace-nowrap">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDetailGroup(g)}
                          >
                            <Users className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => openEdit(g)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="mt-4 flex items-center justify-between">
                <p className="text-muted-foreground text-sm">
                  Tổng {formatInt(total)} nhóm · Trang {page + 1}/{totalPages}
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

      <SmsGroupFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        group={editing}
      />
      <SmsGroupContactsDialog
        open={detailGroup != null}
        onOpenChange={(o) => !o && setDetailGroup(null)}
        // Bản tươi từ list để member_count cập nhật sau import; fallback snapshot.
        group={items.find((g) => g.id === detailGroup?.id) ?? detailGroup}
      />
    </div>
  )
}
