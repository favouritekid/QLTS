// src/components/sms/admin/contacts/SmsContactsPanel.tsx
"use client"

import { useState } from "react"
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
import { useSmsContacts } from "@/hooks/useSmsContacts"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"
import { SMS_CONSENT_STATUSES, type SmsContact } from "@/lib/zod/sms"

import {
  consentStatusLabel,
  consentStatusVariant,
  formatDateTimeVN,
  formatInt,
} from "../labels"
import { SmsContactDetailDialog } from "./SmsContactDetailDialog"
import { SmsContactFormDialog } from "./SmsContactFormDialog"

const ALL = "all"
const PAGE_SIZE = 50

export function SmsContactsPanel() {
  const [searchInput, setSearchInput] = useState("")
  const [consent, setConsent] = useState<string>(ALL)
  const [page, setPage] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [detail, setDetail] = useState<SmsContact | null>(null)

  const search = useDebouncedValue(searchInput.trim())

  const onSearch = (v: string) => {
    setSearchInput(v)
    setPage(0)
  }
  const onConsent = (v: string) => {
    setConsent(v)
    setPage(0)
  }

  const { data, isLoading, isError, refetch, isFetching } = useSmsContacts({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    search: search || undefined,
    consent_status: consent === ALL ? undefined : consent,
  })

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const items = data?.items ?? []

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2 lg:max-w-xl">
              <div className="space-y-1.5">
                <Label htmlFor="ct-search">Tìm liên hệ</Label>
                <div className="relative">
                  <Search className="text-muted-foreground absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2" />
                  <Input
                    id="ct-search"
                    className="pl-8"
                    placeholder="Tên / số điện thoại…"
                    value={searchInput}
                    onChange={(e) => onSearch(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ct-consent">Consent</Label>
                <Select value={consent} onValueChange={onConsent}>
                  <SelectTrigger id="ct-consent">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Tất cả</SelectItem>
                    {SMS_CONSENT_STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {consentStatusLabel(s)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" /> Tạo liên hệ
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
                Không thể tải danh sách liên hệ.
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
                  : search || consent !== ALL
                    ? "Không có liên hệ khớp bộ lọc."
                    : "Chưa có liên hệ nào."}
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
                      <TableHead>Họ tên</TableHead>
                      <TableHead>Số điện thoại</TableHead>
                      <TableHead>Consent</TableHead>
                      <TableHead>Nguồn</TableHead>
                      <TableHead>Tạo lúc</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((c) => (
                      <TableRow
                        key={c.id}
                        className="hover:bg-muted/50 cursor-pointer"
                        onClick={() => setDetail(c)}
                      >
                        <TableCell className="font-medium">
                          {c.full_name}
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {c.phone_normalized}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={consentStatusVariant(
                              c.marketing_consent_status,
                            )}
                          >
                            {consentStatusLabel(c.marketing_consent_status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-[160px] truncate text-sm">
                          {c.source_label || "—"}
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
                  Tổng {formatInt(total)} liên hệ · Trang {page + 1}/{totalPages}
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

      <SmsContactFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        contact={null}
      />
      <SmsContactDetailDialog
        open={detail != null}
        onOpenChange={(o) => !o && setDetail(null)}
        contact={detail}
      />
    </div>
  )
}
