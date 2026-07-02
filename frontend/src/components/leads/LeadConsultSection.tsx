// src/components/leads/LeadConsultSection.tsx
"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
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
import { formatDwell } from "@/lib/format"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import {
  useCreateConsultLink,
  useLeadSmsInterests,
} from "@/hooks/useSmsConsult"

/**
 * P2-4b — "Tư vấn SMS: Quan tâm ngành" ở trang chi tiết lead. Collapsible
 * (§16.5 tab, lazy): chỉ fetch interest khi mở → không thêm request cho mọi
 * lead không dùng SMS. Thin-client: BE gác quyền (CasbinAuth + IDOR); FE render.
 * - Nút "Tạo link tư vấn" CHỈ hiện khi query interest thành công (cùng gate
 *   Casbin+IDOR → dùng kết quả API làm cờ quyền, không đoán theo role).
 * - Mã/url CHỈ hiện 1 lần (BE lưu token_hash) → copy ngay.
 */
export function LeadConsultSection({ leadId }: { leadId: number }) {
  const [expanded, setExpanded] = useState(false)
  const { copied, copy, reset: resetCopied } = useCopyToClipboard()

  const { data, isLoading, isError, refetch, isFetching } =
    useLeadSmsInterests(leadId, expanded)
  const createLink = useCreateConsultLink()
  const link = createLink.data

  // Đổi lead → reset link vừa tạo (tránh hiện link lead cũ trên lead mới) +
  // copied. createLink.data là mutation-state không tự re-key theo leadId.
  useEffect(() => {
    createLink.reset()
    resetCopied()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadId])

  const onCopy = async () => {
    if (!link) return
    const ok = await copy(link.url)
    if (!ok) {
      toast.error("Không tự sao chép được — vui lòng copy tay từ ô hiển thị.")
    }
  }

  return (
    <Card>
      <CardHeader className="px-4 py-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown className="text-muted-foreground h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="text-muted-foreground h-4 w-4 shrink-0" />
          )}
          <MessageSquareShare className="h-4 w-4 shrink-0" />
          <CardTitle className="flex-1 text-sm font-medium">
            Tư vấn SMS — Quan tâm ngành
          </CardTitle>
        </button>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : isError ? (
            // Query lỗi (403 không quyền / network) → error KHÁC empty; ẩn nút
            // tạo (cùng gate → không tạo được) + cho thử lại.
            <div className="text-muted-foreground flex flex-col items-center gap-2 py-4 text-center text-sm">
              <AlertCircle className="text-destructive h-5 w-5" />
              <span>Không tải được dữ liệu quan tâm ngành.</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => refetch()}
                disabled={isFetching}
              >
                Thử lại
              </Button>
            </div>
          ) : (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => createLink.mutate(leadId)}
                disabled={createLink.isPending}
                className="w-full"
              >
                {createLink.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Link2 className="mr-2 h-4 w-4" />
                )}
                {link ? "Tạo link khác" : "Tạo link tư vấn"}
              </Button>

              {/* Link vừa tạo — copy NGAY (mã chỉ hiện 1 lần) */}
              {link && (
                <div
                  role="status"
                  className="bg-muted/50 space-y-2 rounded border p-3"
                >
                  <p className="text-muted-foreground text-xs">
                    Sao chép NGAY và gửi cho khách qua Zalo/tin nhắn — mã chỉ
                    hiển thị một lần, rời trang sẽ không lấy lại được (tạo link
                    mới nếu cần). Link không hết hạn.
                  </p>
                  <div className="flex items-center gap-2">
                    <code
                      title={link.url}
                      className="bg-background min-w-0 flex-1 truncate rounded px-2 py-1 text-xs"
                    >
                      {link.url}
                    </code>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={onCopy}
                      aria-label={copied ? "Đã sao chép link" : "Sao chép link"}
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
              {!data || data.items.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  Khách chưa xem ngành nào. Tạo link tư vấn và gửi cho khách để
                  bắt đầu đo mức quan tâm.
                </p>
              ) : (
                <ul className="max-h-64 space-y-2 overflow-y-auto">
                  {data.items.map((it) => (
                    <li
                      key={it.major_program_id}
                      className="flex items-center gap-3 rounded border p-2"
                    >
                      <GraduationCap className="text-primary h-4 w-4 shrink-0" />
                      <span
                        title={it.program_name}
                        className="min-w-0 flex-1 truncate text-sm font-medium"
                      >
                        {it.program_name}
                      </span>
                      <Badge variant="secondary" className="shrink-0">
                        {formatDwell(it.total_dwell_seconds)}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </CardContent>
      )}
    </Card>
  )
}
