"use client"

import { AlertTriangle, Info, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { useMeasureSmsTemplate } from "@/hooks/useSmsCampaigns"
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value"

/**
 * Preview tin cuối + đếm ký tự/đoạn LIVE cho form soạn campaign (§7). Đo qua BE
 * (cùng logic với build → số khớp). Phân 2 tầng:
 * - Lỗi-chặn-lưu (đỏ): biến lạ / chứa __SMS_LINK__ (mirror gate _validate_content).
 * - Cảnh báo mềm (vàng): optout chưa cấu hình, tin vượt 1 đoạn.
 * KHÔNG tự chặn submit — build/preflight/create-gate là cổng cuối.
 */
export function SmsTemplatePreview({ template }: { template: string }) {
  const debounced = useDebouncedValue(template, 400)
  const { data, isFetching, isError } = useMeasureSmsTemplate(debounced)

  if (!debounced.trim()) return null

  const blocking =
    !!data && (data.unknown_vars.length > 0 || data.has_internal_sentinel)

  return (
    <div className="bg-muted/40 space-y-2 rounded-md border p-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground font-medium">Xem trước tin</span>
        {isFetching && (
          <Loader2 className="text-muted-foreground h-3 w-3 animate-spin" />
        )}
      </div>

      {isError ? (
        <p className="text-muted-foreground">Không đo được tin (thử lại sau).</p>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{data.length} ký tự</Badge>
            <Badge variant={data.is_over_limit ? "destructive" : "secondary"}>
              {data.segments} đoạn
            </Badge>
            <Badge variant="outline">{data.encoding}</Badge>
            {data.has_link && <Badge variant="outline">có {"{link}"}</Badge>}
          </div>

          <p className="bg-background text-foreground rounded border p-2 break-words whitespace-pre-wrap">
            {data.preview}
          </p>

          {blocking && (
            <div className="text-destructive flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <div>
                <p className="font-medium">Nội dung sẽ bị từ chối khi lưu:</p>
                <ul className="list-inside list-disc">
                  {data.unknown_vars.map((v) => (
                    <li key={v}>Biến không hợp lệ: {v}</li>
                  ))}
                  {data.has_internal_sentinel && (
                    <li>Chứa chuỗi nội bộ __SMS_LINK__ (sẽ bị gỡ)</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          {data.warnings.length > 0 && (
            <div className="flex items-start gap-1.5 text-amber-600 dark:text-amber-500">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <ul className="list-inside list-disc">
                {data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <p className="text-muted-foreground">Đang đo…</p>
      )}
    </div>
  )
}
