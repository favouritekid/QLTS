// src/components/sms/admin/SmsClickReportPanel.tsx
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
  useSmsClickReport,
} from "@/hooks/useSmsAdmin"
import type { SmsClickReportParams } from "@/lib/api/sms"
import type { SmsGranularity } from "@/lib/zod/sms"

import {
  CARRIER_FILTER_OPTIONS,
  GRANULARITY_OPTIONS,
  campaignStatusLabel,
  formatInt,
  formatPercent,
} from "./labels"

const ALL = "all"

/** Chuyển date string (YYYY-MM-DD, giờ địa phương) → ISO tz-aware (Z). */
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

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  )
}

/**
 * Báo cáo click tổng hợp theo ngày/tháng/năm (§9). Filter: granularity +
 * chiến dịch + nhà mạng + khoảng ngày. CTR chính = distinct non-bot /
 * recipients_handed_off (BE tính sẵn `ctr_percent`).
 */
export function SmsClickReportPanel() {
  const [granularity, setGranularity] = useState<SmsGranularity>("day")
  const [campaignId, setCampaignId] = useState<string>(ALL)
  const [carrier, setCarrier] = useState<string>(ALL)
  const [dateFrom, setDateFrom] = useState<string>("")
  const [dateTo, setDateTo] = useState<string>("")

  const { data: campaignData } = useSmsCampaignList({ limit: 200 })

  const params = useMemo<SmsClickReportParams>(
    () => ({
      granularity,
      campaign_id: campaignId === ALL ? undefined : Number(campaignId),
      carrier: carrier === ALL ? undefined : carrier,
      date_from: toIsoStart(dateFrom),
      date_to: toIsoEnd(dateTo),
    }),
    [granularity, campaignId, carrier, dateFrom, dateTo],
  )

  const { data, isLoading, isError, refetch, isFetching } =
    useSmsClickReport(params)

  const resetFilters = () => {
    setCampaignId(ALL)
    setCarrier(ALL)
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="sms-report-granularity">Khoảng thời gian</Label>
              <Select
                value={granularity}
                onValueChange={(v) => setGranularity(v as SmsGranularity)}
              >
                <SelectTrigger id="sms-report-granularity">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {GRANULARITY_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="sms-report-campaign">Chiến dịch</Label>
              <Select value={campaignId} onValueChange={setCampaignId}>
                <SelectTrigger id="sms-report-campaign">
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
              <Label htmlFor="sms-report-carrier">Nhà mạng</Label>
              <Select value={carrier} onValueChange={setCarrier}>
                <SelectTrigger id="sms-report-carrier">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Tất cả nhà mạng</SelectItem>
                  {CARRIER_FILTER_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="sms-report-from">Từ ngày</Label>
              <Input
                id="sms-report-from"
                type="date"
                value={dateFrom}
                max={dateTo || undefined}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="sms-report-to">Đến ngày</Label>
              <Input
                id="sms-report-to"
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
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <SummaryCard
            label="Tổng lượt click"
            value={formatInt(data.total_clicks)}
          />
          <SummaryCard
            label="Click thật (đã lọc bot)"
            value={formatInt(data.human_clicks)}
          />
          <SummaryCard
            label="Số người click"
            value={formatInt(data.distinct_contacts_clicked)}
          />
          <SummaryCard
            label="Đã bàn giao gửi"
            value={formatInt(data.recipients_handed_off)}
          />
          <SummaryCard label="CTR" value={formatPercent(data.ctr_percent)} />
        </div>
      ) : null}

      {/* Bảng theo mốc thời gian */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Diễn tiến theo mốc thời gian
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !data || data.buckets.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {isFetching
                ? "Đang tải…"
                : "Chưa có lượt click nào trong phạm vi đã chọn."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mốc</TableHead>
                    <TableHead className="text-right">Tổng click</TableHead>
                    <TableHead className="text-right">Click thật</TableHead>
                    <TableHead className="text-right">Số người click</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.buckets.map((b) => (
                    <TableRow key={b.period}>
                      <TableCell className="font-medium">{b.period}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInt(b.total_clicks)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInt(b.human_clicks)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatInt(b.distinct_contacts_clicked)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
