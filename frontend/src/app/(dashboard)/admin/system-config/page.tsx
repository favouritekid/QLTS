/**
 * Admin page — runtime system_config key-value editor.
 *
 * Phase 3 close-out 2026-05-14: phase3_01 migration seeded
 * ``max_choices_per_profile=5`` (Q-P3-01) and Phase 1 PR-1D shipped the
 * backend admin endpoints, but the FE consumer (admin UI) was never
 * wired. Without this page admin can only mutate config via curl or
 * direct SQL.
 *
 * Keys we expect to live here:
 *   - ``max_choices_per_profile`` (int) — Phase 3 multi-NV cap
 *   - ``current_intake_year`` (int) — storefront default year
 *   - Future: ``zalo_template_approved`` / ``sms_template_approved``
 *     gating flags (Q-P3-07 follow-up)
 *
 * Sensitive keys (secrets, tokens) MUST NOT be stored here — read path
 * is permissive across active users. Backend service rejects writes for
 * non-admin via ``require_admin``.
 */
"use client"

import { useState } from "react"

import { PageContainer } from "@/components/layouts/PageContainer"
import { PageHeader } from "@/components/layouts/PageHeader"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Pencil, Loader2 } from "lucide-react"

import {
  useSystemConfigList,
  useUpdateSystemConfig,
} from "@/hooks/admin/useSystemConfig"
import type { SystemConfigResponse } from "@/lib/zod/system-config"

function formatValueForDisplay(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  // Compact JSON for nested shapes — multi-line view lives in the edit
  // dialog, the table cell stays single-line readable.
  return JSON.stringify(value)
}

function formatValueForEdit(value: unknown): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "string") return value
  return JSON.stringify(value, null, 2)
}

/**
 * Parse the textarea content back into the JSON shape the BE expects.
 *
 * BE stores heterogeneous JSONB so we accept:
 *   - Bare strings (single line, no JSON wrapping)
 *   - Numbers, booleans, null
 *   - Arrays / nested objects (valid JSON)
 *
 * Order matters: try strict JSON first so ``"5"`` round-trips as a
 * string and ``5`` parses as int. If JSON.parse fails the input is
 * treated as a raw string.
 */
function parseEditedValue(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === "") return ""
  try {
    return JSON.parse(trimmed)
  } catch {
    return trimmed
  }
}

export default function SystemConfigPage() {
  const { data, isLoading } = useSystemConfigList()
  const updateMutation = useUpdateSystemConfig()

  const [editTarget, setEditTarget] = useState<SystemConfigResponse | null>(null)
  const [valueDraft, setValueDraft] = useState("")
  const [descriptionDraft, setDescriptionDraft] = useState("")

  const openEdit = (row: SystemConfigResponse) => {
    setEditTarget(row)
    setValueDraft(formatValueForEdit(row.value))
    setDescriptionDraft(row.description ?? "")
  }

  const closeEdit = () => {
    setEditTarget(null)
    setValueDraft("")
    setDescriptionDraft("")
  }

  const handleSubmit = async () => {
    if (!editTarget) return
    await updateMutation.mutateAsync({
      key: editTarget.key,
      data: {
        value: parseEditedValue(valueDraft),
        description: descriptionDraft.trim() === "" ? null : descriptionDraft,
      },
    })
    closeEdit()
  }

  const rows = data?.items ?? []

  return (
    <PageContainer>
      <PageHeader
        title="Cấu hình hệ thống"
        description="Chỉnh sửa các tham số runtime của hệ thống (max nguyện vọng / năm tuyển sinh mặc định / cờ tính năng). Giá trị nhận JSON hợp lệ (số, chuỗi, mảng) hoặc text thuần."
      />

      <Card>
        <CardHeader>
          <CardTitle>Các tham số runtime</CardTitle>
          <CardDescription>
            Sau khi sửa, giá trị có hiệu lực ngay với mọi request tiếp theo —
            không cần restart backend. Phím nhạy cảm (secret, token) tuyệt
            đối không được lưu ở đây.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2" data-testid="system-config-loading">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Chưa có tham số nào được khởi tạo.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Giá trị</TableHead>
                  <TableHead>Mô tả</TableHead>
                  <TableHead>Cập nhật gần nhất</TableHead>
                  <TableHead className="text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.key} data-testid={`system-config-row-${row.key}`}>
                    <TableCell className="font-mono text-xs">{row.key}</TableCell>
                    <TableCell className="max-w-xs truncate font-mono text-xs">
                      {formatValueForDisplay(row.value)}
                    </TableCell>
                    <TableCell className="max-w-md text-xs text-muted-foreground">
                      {row.description ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(row.updated_at).toLocaleString("vi-VN")}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(row)}
                        data-testid={`system-config-edit-${row.key}`}
                      >
                        <Pencil className="mr-1 h-3.5 w-3.5" />
                        Sửa
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={editTarget !== null} onOpenChange={(o) => !o && closeEdit()}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              Sửa cấu hình: <code>{editTarget?.key}</code>
            </DialogTitle>
            <DialogDescription>
              Giá trị mới được áp dụng ngay. Nhập JSON hợp lệ (số / chuỗi
              JSON / mảng / object) hoặc plain string. Mọi thay đổi đều ghi
              audit log.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <label
                htmlFor="system-config-value"
                className="text-sm font-medium"
              >
                Giá trị
              </label>
              <Textarea
                id="system-config-value"
                value={valueDraft}
                onChange={(e) => setValueDraft(e.target.value)}
                rows={6}
                className="font-mono text-xs"
                data-testid="system-config-value-input"
              />
              <p className="text-xs text-muted-foreground">
                Hệ thống thử parse JSON trước; nếu không phải JSON hợp lệ sẽ
                lưu nguyên dạng chuỗi.
              </p>
            </div>

            <div className="space-y-2">
              <label
                htmlFor="system-config-description"
                className="text-sm font-medium"
              >
                Mô tả (tuỳ chọn)
              </label>
              <Input
                id="system-config-description"
                value={descriptionDraft}
                onChange={(e) => setDescriptionDraft(e.target.value)}
                placeholder="Mô tả khoá cấu hình, ghi chú quyết định..."
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeEdit}>
              Huỷ
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={updateMutation.isPending}
              data-testid="system-config-submit"
            >
              {updateMutation.isPending && (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              )}
              Lưu
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  )
}
