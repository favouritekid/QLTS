// src/components/sms/admin/SmsCampaignDashboardPanel.tsx
"use client"

import { useState } from "react"
import { AlertCircle, LinkIcon, Link2Off } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
  useSmsCampaignDashboard,
  useSmsCampaignList,
} from "@/hooks/useSmsAdmin"

import {
  campaignStatusLabel,
  carrierLabel,
  formatDateTimeVN,
  formatInt,
  formatPercent,
} from "./labels"

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
 * Dashboard 1 chiến dịch: chọn campaign → CTR + phân bố nhà mạng + danh sách
 * số đã click (đã lọc bot, PII masked). has_link=false → chiến dịch không có
 * short-link nên không đo được click.
 */
export function SmsCampaignDashboardPanel() {
  const [selected, setSelected] = useState<string>("")
  const { data: campaignData, isLoading: campaignsLoading } =
    useSmsCampaignList({ limit: 200 })

  const campaignId = selected ? Number(selected) : null
  const { data, isLoading, isError, refetch } =
    useSmsCampaignDashboard(campaignId)

  const carrierEntries = data
    ? Object.entries(data.carrier_distribution).sort((a, b) => b[1] - a[1])
    : []

  return (
    <div className="space-y-6">
      {/* Chọn chiến dịch */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Chọn chiến dịch</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-w-md space-y-1.5">
            <Label htmlFor="sms-dashboard-campaign">Chiến dịch</Label>
            <Select
              value={selected}
              onValueChange={setSelected}
              disabled={campaignsLoading}
            >
              <SelectTrigger id="sms-dashboard-campaign">
                <SelectValue
                  placeholder={
                    campaignsLoading
                      ? "Đang tải danh sách…"
                      : "— Chọn một chiến dịch —"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {campaignData?.items.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name} ({campaignStatusLabel(c.status)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!campaignsLoading && campaignData?.items.length === 0 && (
              <p className="text-muted-foreground text-xs">
                Chưa có chiến dịch nào.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Chưa chọn */}
      {campaignId == null && (
        <p className="text-muted-foreground py-8 text-center text-sm">
          Chọn một chiến dịch để xem báo cáo hiệu quả.
        </p>
      )}

      {/* Lỗi */}
      {campaignId != null && isError && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <AlertCircle className="text-destructive h-8 w-8" />
            <p className="text-muted-foreground text-sm">
              Không thể tải dashboard chiến dịch.
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Thử lại
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Đang tải */}
      {campaignId != null && isLoading && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      )}

      {/* Dữ liệu */}
      {campaignId != null && data && !isLoading && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">
              Bản dựng #{data.build_revision}
            </Badge>
            {data.has_link ? (
              <Badge variant="outline" className="gap-1">
                <LinkIcon className="h-3 w-3" /> Có short-link
              </Badge>
            ) : (
              <Badge variant="outline" className="gap-1 text-amber-600">
                <Link2Off className="h-3 w-3" /> Không có short-link
              </Badge>
            )}
          </div>

          {!data.has_link && (
            <Card className="border-amber-300 bg-amber-50">
              <CardContent className="text-sm text-amber-800">
                Chiến dịch này không chèn short-link nên hệ thống không đo được
                lượt click. Các chỉ số click bên dưới sẽ bằng 0.
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <SummaryCard
              label="Đã bàn giao gửi"
              value={formatInt(data.recipients_handed_off)}
            />
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
            <SummaryCard label="CTR" value={formatPercent(data.ctr_percent)} />
          </div>

          {/* Phân bố nhà mạng */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Phân bố theo nhà mạng (đã bàn giao)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {carrierEntries.length === 0 ? (
                <p className="text-muted-foreground py-4 text-center text-sm">
                  Chưa có dữ liệu phân bố.
                </p>
              ) : (
                <div className="space-y-2">
                  {carrierEntries.map(([bucket, count]) => (
                    <div
                      key={bucket}
                      className="flex items-center justify-between border-b py-1.5 last:border-0"
                    >
                      <span className="text-sm">{carrierLabel(bucket)}</span>
                      <span className="text-sm font-semibold tabular-nums">
                        {formatInt(count)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Danh sách số đã click */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Số đã click ({formatInt(data.clickers.length)})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.clickers.length === 0 ? (
                <p className="text-muted-foreground py-8 text-center text-sm">
                  Chưa có người nhận nào click (đã loại bot).
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Họ tên</TableHead>
                        <TableHead>Số điện thoại</TableHead>
                        <TableHead>Nhà mạng</TableHead>
                        <TableHead className="text-right">Lượt click</TableHead>
                        <TableHead>Click đầu</TableHead>
                        <TableHead>Click gần nhất</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.clickers.map((c) => (
                        <TableRow key={c.recipient_id}>
                          <TableCell className="font-medium">
                            {c.full_name}
                          </TableCell>
                          <TableCell className="tabular-nums">
                            {c.phone_masked}
                          </TableCell>
                          <TableCell>{carrierLabel(c.carrier_bucket)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatInt(c.human_click_count)}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            {formatDateTimeVN(c.first_human_clicked_at)}
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            {formatDateTimeVN(c.last_human_clicked_at)}
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
      )}
    </div>
  )
}
