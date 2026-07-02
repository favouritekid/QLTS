// src/components/sms/admin/SmsProgramInterestPanel.tsx
"use client"

import { useMemo, useState } from "react"
import { AlertCircle, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import {
  useSmsCampaignList,
  useSmsProgramInterest,
} from "@/hooks/useSmsAdmin"
import type { SmsProgramInterestParams } from "@/lib/api/sms"

import { campaignStatusLabel, formatDwell, formatInt } from "./labels"
import { SmsSummaryCard } from "./SmsSummaryCard"

const ALL = "all"

function toIsoStart(d: string): string | undefined {
  if (!d) return undefined
  const parsed = new Date(`${d}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
}
function toIsoEnd(d: string): string | undefined {
  if (!d) return undefined
  const parsed = new Date(`${d}T23:59:59.999`)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
}

/**
 * Report "ngành nóng" (§16.7) — tín hiệu chính = TỔNG dwell/ngành (rank desc,
 * BE loại phiên bot + tên ngành hiện tại). Filter chiến dịch + khoảng ngày.
 * Thin-client: render đúng số BE trả.
 */
export function SmsProgramInterestPanel() {
  const [campaignId, setCampaignId] = useState<string>(ALL)
  const [dateFrom, setDateFrom] = useState<string>("")
  const [dateTo, setDateTo] = useState<string>("")

  const { data: campaignData } = useSmsCampaignList({ limit: 200 })

  const params = useMemo<SmsProgramInterestParams>(
    () => ({
      campaign_id: campaignId === ALL ? undefined : Number(campaignId),
      date_from: toIsoStart(dateFrom),
      date_to: toIsoEnd(dateTo),
    }),
    [campaignId, dateFrom, dateTo],
  )

  const { data, isLoading, isError, refetch, isFetching } =
    useSmsProgramInterest(params)

  const invalidRange = dateFrom !== "" && dateTo !== "" && dateFrom > dateTo

  const resetFilters = () => {
    setCampaignId(ALL)
    setDateFrom("")
    setDateTo("")
  }

  return (
    <div className="space-y-6">
      {/* Bộ lọc */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Bộ lọc</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1.5">
              <Label htmlFor="sms-interest-campaign">Chiến dịch</Label>
              <Select value={campaignId} onValueChange={setCampaignId}>
                <SelectTrigger id="sms-interest-campaign">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Tất cả chiến dịch</SelectItem>
                  {campaignData?.items.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name} ({campaignStatusLabel(c.status)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="sms-interest-from">Từ ngày</Label>
              <Input
                id="sms-interest-from"
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="sms-interest-to">Đến ngày</Label>
              <Input
                id="sms-interest-to"
                type="date"
                value={dateTo}
                min={dateFrom || undefined}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>

            <div className="flex items-end">
              <Button
                variant="outline"
                onClick={resetFilters}
                className="w-full sm:w-auto"
              >
                <RotateCcw className="mr-2 h-4 w-4" /> Xóa lọc
              </Button>
            </div>
          </div>

          {invalidRange && (
            <p className="text-destructive mt-3 text-xs">
              Mốc bắt đầu đang muộn hơn mốc kết thúc — vui lòng chọn lại khoảng
              ngày hợp lệ.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Trạng thái lỗi */}
      {isError && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <AlertCircle className="text-destructive h-8 w-8" />
            <p className="text-muted-foreground text-sm">
              Không thể tải báo cáo. Vui lòng thử lại.
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Thử lại
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Thẻ tổng hợp */}
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <SmsSummaryCard
            label="Số người quan tâm"
            value={formatInt(data.distinct_contacts_total)}
          />
          <SmsSummaryCard
            label="Tổng lượt xem ngành"
            value={formatInt(data.view_count_total)}
          />
          <SmsSummaryCard
            label="Tổng thời gian xem"
            value={formatDwell(data.total_dwell_seconds)}
          />
        </div>
      ) : null}

      {/* Bảng ngành nóng */}
      {!isError && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Ngành được quan tâm (theo tổng thời gian xem)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : !data || data.items.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                {isFetching
                  ? "Đang tải…"
                  : "Chưa có lượt xem ngành nào trong phạm vi đã chọn."}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10 text-right">#</TableHead>
                      <TableHead>Ngành</TableHead>
                      <TableHead className="text-right">
                        Số người quan tâm
                      </TableHead>
                      <TableHead className="text-right">Lượt xem</TableHead>
                      <TableHead className="text-right">
                        Tổng thời gian
                      </TableHead>
                      <TableHead className="text-right">TB/lượt</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((row, i) => (
                      <TableRow
                        key={row.major_program_id ?? `deleted-${i}`}
                      >
                        <TableCell className="text-muted-foreground text-right tabular-nums">
                          {i + 1}
                        </TableCell>
                        <TableCell className="font-medium">
                          {row.program_name}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatInt(row.distinct_contacts)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatInt(row.view_count)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatDwell(row.total_dwell_seconds)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatDwell(Math.round(row.avg_dwell_seconds))}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
