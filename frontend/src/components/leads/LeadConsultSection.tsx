// src/components/leads/LeadConsultSection.tsx
"use client"

import { useState } from "react"
import {
  Check,
  Copy,
  GraduationCap,
  Link2,
  Loader2,
  MessageSquareShare,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDwell } from "@/components/sms/admin/labels"
import {
  useCreateConsultLink,
  useLeadSmsInterests,
} from "@/hooks/useSmsConsult"

/**
 * P2-4b — "Tư vấn SMS: Quan tâm ngành" ở trang chi tiết lead. Thin-client:
 * - Nút "Tạo link tư vấn" → BE sinh consult link (match/tạo contact từ phone
 *   lead) → hiển thị code/url để officer copy gửi Zalo/tay.
 * - Danh sách ngành lead quan tâm (rank tổng dwell desc, qua contact match).
 * BE gác quyền (CasbinAuth + IDOR); FE chỉ render.
 */
export function LeadConsultSection({ leadId }: { leadId: number }) {
  const { data, isLoading, isError } = useLeadSmsInterests(leadId)
  const createLink = useCreateConsultLink()
  const [copied, setCopied] = useState(false)

  const link = createLink.data
  const onCopy = async () => {
    if (!link) return
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard bị chặn → officer copy tay từ ô hiển thị.
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <MessageSquareShare className="h-4 w-4" /> Tư vấn SMS — Quan tâm ngành
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          onClick={() => createLink.mutate(leadId)}
          disabled={createLink.isPending}
        >
          {createLink.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Link2 className="mr-2 h-4 w-4" />
          )}
          Tạo link tư vấn
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Link vừa tạo — copy gửi khách */}
        {link && (
          <div className="bg-muted/50 space-y-2 rounded border p-3">
            <p className="text-muted-foreground text-xs">
              Gửi link này cho khách qua Zalo/tin nhắn. Không hết hạn; lượt xem
              ngành của khách sẽ hiện bên dưới.
            </p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 text-xs">
                {link.url}
              </code>
              <Button
                size="sm"
                variant="secondary"
                onClick={onCopy}
                aria-label="Sao chép link"
              >
                {copied ? (
                  <Check className="h-4 w-4 text-green-600" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        )}

        {/* Danh sách ngành quan tâm */}
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="text-muted-foreground text-sm">
            Chưa có dữ liệu quan tâm ngành cho lead này.
          </p>
        ) : !data || data.items.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Khách chưa xem ngành nào. Tạo link tư vấn và gửi cho khách để bắt
            đầu đo mức quan tâm.
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((it) => (
              <li
                key={it.major_program_id}
                className="flex items-center gap-3 rounded border p-2"
              >
                <GraduationCap className="text-primary h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {it.program_name}
                </span>
                <Badge variant="secondary" className="shrink-0">
                  {formatDwell(it.total_dwell_seconds)}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
