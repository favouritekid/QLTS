// src/components/sms/admin/campaigns/SmsCampaignsListClient.tsx
"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
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
import { useSmsCampaignsFull } from "@/hooks/useSmsCampaigns"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import type { SmsCampaign } from "@/lib/zod/sms"

import {
  campaignStatusLabel,
  formatDateTimeVN,
  formatInt,
  landingTypeLabel,
} from "../labels"
import { SmsCampaignFormDialog } from "./SmsCampaignFormDialog"

const ALL = "all"
const PAGE_SIZE = 50
const STATUSES = ["draft", "ready", "exported", "handed_off", "closed"]

function statusVariant(
  s: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (s === "closed") return "secondary"
  if (s === "handed_off" || s === "exported") return "default"
  return "outline"
}

export function SmsCampaignsListClient() {
  const router = useRouter()
  const [searchInput, setSearchInput] = useState("")
  const [status, setStatus] = useState<string>(ALL)
  const [page, setPage] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)

  const search = useDebouncedValue(searchInput.trim())

  const onSearch = (v: string) => {
    setSearchInput(v)
    setPage(0)
  }
  const onStatus = (v: string) => {
    setStatus(v)
    setPage(0)
  }

  const { data, isLoading, isError, refetch, isFetching } = useSmsCampaignsFull({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    search: search || undefined,
    status: status === ALL ? undefined : status,
  })

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const items = data?.items ?? []

  const openCampaign = (c: SmsCampaign) =>
    router.push(`/admin/sms/campaigns/${c.id}`)

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-xl">
              <div className="space-y-1.5">
                <Label htmlFor="cp-search">Tìm chiến dịch</Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="cp-search"
                    className="pl-8"
                    placeholder="Tên / mã…"
                    value={searchInput}
                    onChange={(e) => onSearch(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cp-status">Trạng thái</Label>
                <Select value={status} onValueChange={onStatus}>
                  <SelectTrigger id="cp-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Tất cả</SelectItem>
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {campaignStatusLabel(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" /> Tạo chiến dịch
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
                Không thể tải danh sách chiến dịch.
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
                  : search || status !== ALL
                    ? "Không có chiến dịch khớp bộ lọc."
                    : "Chưa có chiến dịch nào."}
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
                      <TableHead>Tên</TableHead>
                      <TableHead>Trạng thái</TableHead>
                      <TableHead>Trang đích</TableHead>
                      <TableHead className="text-right">Nhóm</TableHead>
                      <TableHead>Tạo lúc</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((c) => (
                      <TableRow
                        key={c.id}
                        className="hover:bg-muted/50 cursor-pointer"
                        onClick={() => openCampaign(c)}
                      >
                        <TableCell>
                          <div className="font-medium">{c.name}</div>
                          <div className="text-muted-foreground text-xs">
                            {c.code}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(c.status)}>
                            {campaignStatusLabel(c.status)}
                          </Badge>
                        </TableCell>
                        <TableCell>{landingTypeLabel(c.landing_type)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {c.group_count != null ? formatInt(c.group_count) : "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                          {formatDateTimeVN(c.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="mt-4 flex items-center justify-between">
                <p className="text-muted-foreground text-sm">
                  Tổng {formatInt(total)} chiến dịch · Trang {page + 1}/
                  {totalPages}
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

      <SmsCampaignFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        campaign={null}
        onCreated={openCampaign}
      />
    </div>
  )
}
