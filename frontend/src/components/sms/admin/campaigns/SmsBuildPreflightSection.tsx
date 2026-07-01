// src/components/sms/admin/campaigns/SmsBuildPreflightSection.tsx
"use client"

import { AlertCircle, AlertTriangle, Hammer, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
  useBuildSmsCampaign,
  useSmsCampaignPreflight,
} from "@/hooks/useSmsCampaigns"
import type { SmsPreflightReport } from "@/lib/zod/sms"

import {
  carrierLabel,
  excludedReasonLabel,
  formatInt,
} from "../labels"

interface Props {
  campaignId: number
  hasBuild: boolean
  /** Build được khi draft/ready/exported (chưa bàn giao/đóng). */
  canBuild: boolean
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border p-3">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="mt-0.5 text-xl font-bold tabular-nums">{value}</p>
    </div>
  )
}

export function SmsBuildPreflightSection({
  campaignId,
  hasBuild,
  canBuild,
}: Props) {
  const buildMut = useBuildSmsCampaign()
  const {
    data: preflightData,
    isLoading,
    isError,
    refetch,
  } = useSmsCampaignPreflight(campaignId, { enabled: hasBuild })
  // Ưu tiên kết quả build vừa chạy (tức thời), fallback query (reload).
  const preflight: SmsPreflightReport | undefined =
    buildMut.data ?? preflightData

  const carrierEntries = preflight
    ? Object.entries(preflight.carrier_distribution).sort((a, b) => b[1] - a[1])
    : []
  const excludedEntries = preflight
    ? Object.entries(preflight.excluded_by_reason).filter(([, n]) => n > 0)
    : []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Build &amp; Preflight</CardTitle>
        {canBuild && (
          <Button
            size="sm"
            onClick={() => buildMut.mutate(campaignId)}
            disabled={buildMut.isPending}
          >
            {buildMut.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Hammer className="mr-2 h-4 w-4" />
            )}
            {hasBuild ? "Build lại" : "Build"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!hasBuild && !preflight ? (
          <p className="text-muted-foreground py-4 text-center text-sm">
            Chưa build. Gắn nhóm rồi bấm “Build” để chốt danh sách gửi + kiểm tra
            độ dài tin.
          </p>
        ) : isError && !preflight ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <AlertCircle className="text-destructive h-7 w-7" />
            <p className="text-muted-foreground text-sm">
              Không tải được kết quả preflight.
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Thử lại
            </Button>
          </div>
        ) : isLoading && !preflight ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : preflight ? (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard
                label="Tổng người nhận"
                value={formatInt(preflight.total)}
              />
              <StatCard
                label="Gửi được"
                value={formatInt(preflight.exportable)}
              />
              <StatCard
                label="Bản dựng"
                value={`#${preflight.build_revision}`}
              />
              <StatCard
                label="Đo click"
                value={preflight.has_link ? "Có" : "Không"}
              />
            </div>

            {preflight.over_limit.length > 0 && (
              <div className="rounded border border-amber-300 bg-amber-50 p-3">
                <p className="flex items-center gap-1.5 text-sm font-medium text-amber-800">
                  <AlertTriangle className="h-4 w-4" />
                  {formatInt(preflight.over_limit.length)} người nhận có tin vượt
                  1 đoạn — phải rút gọn nội dung trước khi export.
                </p>
                <div className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs">
                  {preflight.over_limit.map((r, i) => (
                    <div key={i} className="text-amber-800">
                      {r.full_name} ({r.phone_normalized})
                      {r.segments != null ? ` — ${r.segments} đoạn` : ""}
                      {r.encoding ? ` · ${r.encoding}` : ""}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {preflight.warnings.length > 0 && (
              <div className="space-y-1">
                {preflight.warnings.map((w, i) => (
                  <p
                    key={i}
                    className="flex items-center gap-1.5 text-xs text-amber-600"
                  >
                    <AlertTriangle className="h-3.5 w-3.5" /> {w}
                  </p>
                ))}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-1.5 text-sm font-medium">Loại theo lý do</p>
                {excludedEntries.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    Không loại ai.
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Lý do</TableHead>
                        <TableHead className="text-right">Số lượng</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {excludedEntries.map(([reason, n]) => (
                        <TableRow key={reason}>
                          <TableCell>{excludedReasonLabel(reason)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatInt(n)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>

              <div>
                <p className="mb-1.5 text-sm font-medium">
                  Phân bố nhà mạng (gửi được)
                </p>
                {carrierEntries.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    Chưa có dữ liệu.
                  </p>
                ) : (
                  <div className="space-y-1">
                    {carrierEntries.map(([bucket, n]) => (
                      <div
                        key={bucket}
                        className="flex items-center justify-between border-b py-1 text-sm last:border-0"
                      >
                        <span>{carrierLabel(bucket)}</span>
                        <span className="font-semibold tabular-nums">
                          {formatInt(n)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {preflight.preview.length > 0 && (
              <div>
                <p className="mb-1.5 text-sm font-medium">
                  Xem trước tin cuối (mẫu)
                </p>
                <div className="space-y-2">
                  {preflight.preview.map((msg, i) => (
                    <div
                      key={i}
                      className="bg-muted/40 rounded border p-2 text-xs whitespace-pre-line"
                    >
                      {msg}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <Badge variant="secondary">
              {preflight.exportable > 0 && preflight.over_limit.length === 0
                ? "Sẵn sàng cho bước attestation + export (PR-6e)"
                : "Chưa đủ điều kiện export — xem cảnh báo ở trên"}
            </Badge>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
