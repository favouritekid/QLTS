// src/components/sms/admin/campaigns/SmsExportSection.tsx
"use client"

import { useState } from "react"
import { AlertTriangle, Download, FileDown, Loader2 } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useSmsCampaignPreflight } from "@/hooks/useSmsCampaigns"
import {
  useCampaignExports,
  useDownloadExport,
  useExportCampaign,
  useMarkExportHandedOff,
} from "@/hooks/useSmsExport"
import { SMS_ATTESTATION_KINDS, type SmsCampaign } from "@/lib/zod/sms"

import {
  carrierLabel,
  exportStatusLabel,
  exportStatusVariant,
  formatDateTimeVN,
  formatInt,
  isAttestationValid,
} from "../labels"

const REQUIRED = SMS_ATTESTATION_KINDS.length

interface Props {
  campaign: SmsCampaign
}

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function SmsExportSection({ campaign }: Props) {
  // Cờ BE. Bàn giao là chuyện TỪNG batch (`b.can_mark_handed_off`) — KHÔNG gắn
  // với vòng đời campaign: bàn giao batch đầu đẩy campaign sang 'handed_off',
  // nếu khoá cả khu theo status thì các nhà mạng còn lại mất nút bàn giao và
  // operator tưởng đã xong (sự cố chiến dịch #6: 338/380 người kẹt).
  const canExport = campaign.can_export === true
  const [handoffTarget, setHandoffTarget] = useState<{
    id: number
    carrier: string
  } | null>(null)

  const { data: preflight } = useSmsCampaignPreflight(campaign.id)
  const { data: exports, isLoading } = useCampaignExports(campaign.id)
  const exportMut = useExportCampaign(campaign.id)
  const handoffMut = useMarkExportHandedOff(campaign.id)
  const downloadMut = useDownloadExport(campaign.id)

  const validCount = SMS_ATTESTATION_KINDS.filter((k) =>
    isAttestationValid(campaign, k),
  ).length

  // Lý do CHƯA export được (BE là gate cuối 400; đây chỉ là gợi ý hiển thị).
  const reasons: string[] = []
  if (validCount < REQUIRED)
    reasons.push(`Còn thiếu ${REQUIRED - validCount}/${REQUIRED} xác nhận`)
  if (preflight && preflight.exportable <= 0)
    reasons.push("Không có người nhận hợp lệ")
  if (preflight && preflight.over_limit.length > 0)
    reasons.push(`Còn ${preflight.over_limit.length} tin vượt 1 đoạn`)
  // Chưa có preflight (đang tải/lỗi) → coi như chưa sẵn sàng (không bật sớm).
  const ready = reasons.length === 0 && preflight != null

  const batches = exports?.batches ?? []

  const confirmHandoff = () => {
    if (!handoffTarget) return
    handoffMut.mutate(
      { batchId: handoffTarget.id },
      { onSuccess: () => setHandoffTarget(null) },
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">Export &amp; bàn giao</CardTitle>
        {canExport && (
          <Button
            size="sm"
            onClick={() => exportMut.mutate()}
            disabled={!ready || exportMut.isPending}
          >
            {exportMut.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <FileDown className="mr-2 h-4 w-4" />
            )}
            Export Excel
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {canExport && !ready && (
          <div className="rounded border border-amber-300 bg-amber-50 p-2.5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
              <AlertTriangle className="h-3.5 w-3.5" />
              Chưa export được: {reasons.join(" · ")}.
            </p>
          </div>
        )}

        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : batches.length === 0 ? (
          <p className="text-muted-foreground py-3 text-center text-sm">
            Chưa có file export. Bấm “Export Excel” để sinh 1 file / nhà mạng.
          </p>
        ) : (
          <div className="divide-y">
            {batches.map((b) => (
              <div
                key={b.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {carrierLabel(b.carrier_bucket)}
                    </span>
                    <Badge variant={exportStatusVariant(b.status)}>
                      {exportStatusLabel(b.status)}
                    </Badge>
                    {b.is_expired && (
                      <Badge variant="secondary">Hết hạn</Badge>
                    )}
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {formatInt(b.recipient_count)} người ·{" "}
                    {formatBytes(b.file_size_bytes)}
                    {b.expires_at
                      ? ` · hết hạn ${formatDateTimeVN(b.expires_at)}`
                      : ""}
                  </p>
                  {b.failure_reason && (
                    <p className="text-destructive text-xs">
                      {b.failure_reason}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {b.can_download && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        downloadMut.isPending &&
                        downloadMut.variables?.batchId === b.id
                      }
                      onClick={() =>
                        downloadMut.mutate({
                          batchId: b.id,
                          fallbackName:
                            b.file_name ?? `${b.carrier_bucket}-export.xlsx`,
                        })
                      }
                    >
                      <Download className="mr-1.5 h-3.5 w-3.5" /> Tải
                    </Button>
                  )}
                  {b.can_mark_handed_off && (
                    <Button
                      size="sm"
                      onClick={() =>
                        setHandoffTarget({
                          id: b.id,
                          carrier: carrierLabel(b.carrier_bucket),
                        })
                      }
                    >
                      Đã bàn giao
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>

      <AlertDialog
        open={handoffTarget != null}
        onOpenChange={(o) => !o && setHandoffTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận đã bàn giao?</AlertDialogTitle>
            <AlertDialogDescription>
              Đánh dấu file <b>{handoffTarget?.carrier}</b> đã upload cho nhà
              mạng. Thao tác này neo người nhận (chặn build lại) + tính tần suất
              gửi, và đóng chiến dịch khi mọi nhà mạng đã bàn giao. Không hoàn
              tác được.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={handoffMut.isPending}>
              Hủy
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={handoffMut.isPending}
              onClick={(e) => {
                e.preventDefault()
                confirmHandoff()
              }}
            >
              {handoffMut.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Xác nhận bàn giao
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
