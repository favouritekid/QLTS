/**
 * PathDetailDrawer — chi tiết 1 path với 5 tabs configurator.
 *
 * Phase 2 v8.2 PR-2D.1 v4a — Option A merge: gộp wizard cũ vào drawer.
 * Tabs: Chỉ tiêu / Định danh / Tiêu chí / Giấy tờ / Vòng đời.
 *
 * Thin-client: button visibility = path.can_edit / path.can_activate /
 * path.available_actions từ API; KHÔNG check role; KHÔNG infer state.
 */
"use client"

import { useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Power,
  PowerOff,
  Save,
  XCircle,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  useActivateAdmissionPath,
  useAdmissionPath,
  useDeactivateAdmissionPath,
  useUpdateAdmissionPath,
} from "@/hooks/admissions/useAdmissionPaths"
import {
  quotaMatrixKeys,
  useUpdatePathQuota,
} from "@/hooks/admissions/useQuotaMatrix"
import type { AdmissionPathResponse } from "@/lib/zod/admission-path"

import { ConfigCriteria } from "../ConfigCriteria"
import { ConfigDocuments } from "../ConfigDocuments"
import { pathStatusLabel } from "./labels"

type PathLike = AdmissionPathResponse

interface Props {
  pathId: number
  onClose: () => void
}

export function PathDetailDrawer({ pathId, onClose }: Props) {
  const { data: path, isLoading } = useAdmissionPath(pathId)
  const [tab, setTab] = useState<string>("quota")

  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent className="sm:max-w-3xl w-full flex flex-col overflow-hidden">
        <SheetHeader className="pr-8">
          <SheetTitle className="text-pretty">
            {path?.display_name || `Đường tuyển sinh #${pathId}`}
          </SheetTitle>
          <SheetDescription className="sr-only">
            Cấu hình chi tiết đường tuyển sinh: chỉ tiêu, định danh, tiêu chí, giấy tờ, vòng đời.
          </SheetDescription>
          {path && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span translate="no">
                {path.admission_method?.code ?? `method ${path.admission_method_id}`}
              </span>
              <span aria-hidden="true">·</span>
              <Badge
                variant={path.status === "active" ? "default" : "outline"}
                className="text-[10px] h-4 px-1"
              >
                {pathStatusLabel(path.status)}
              </Badge>
            </div>
          )}
        </SheetHeader>

        {isLoading && (
          <div className="flex items-center justify-center py-8" aria-live="polite">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
            <span className="sr-only">Đang tải chi tiết đường tuyển sinh…</span>
          </div>
        )}

        {path && (
          <Tabs value={tab} onValueChange={setTab} className="flex-1 flex flex-col min-h-0">
            <TabsList className="grid grid-cols-5 shrink-0">
              <TabsTrigger value="quota">Chỉ tiêu</TabsTrigger>
              <TabsTrigger value="identity">Định danh</TabsTrigger>
              <TabsTrigger value="criteria">Tiêu chí</TabsTrigger>
              <TabsTrigger value="documents">Giấy tờ</TabsTrigger>
              <TabsTrigger value="lifecycle">Vòng đời</TabsTrigger>
            </TabsList>

            <div className="flex-1 min-h-0 overflow-y-auto py-4">
              <TabsContent value="quota">
                <QuotaTab path={path} pathId={pathId} onClose={onClose} />
              </TabsContent>
              <TabsContent value="identity">
                <IdentityTab path={path} pathId={pathId} onClose={onClose} />
              </TabsContent>
              <TabsContent value="criteria">
                <ConfigCriteria
                  path={path}
                  onNext={onClose}
                  onBack={onClose}
                  embedded
                />
              </TabsContent>
              <TabsContent value="documents">
                <ConfigDocuments
                  path={path}
                  onFinish={onClose}
                  onBack={onClose}
                  embedded
                />
              </TabsContent>
              <TabsContent value="lifecycle">
                <LifecycleTab path={path} pathId={pathId} onClose={onClose} />
              </TabsContent>
            </div>
          </Tabs>
        )}
      </SheetContent>
    </Sheet>
  )
}

// ============================================================================
// Tab: Chỉ tiêu (Quota)
// ============================================================================

function QuotaTab({
  path,
  pathId,
  onClose,
}: {
  path: PathLike
  pathId: number
  onClose: () => void
}) {
  const [roundQuota, setRoundQuota] = useState(path.round_quota?.toString() ?? "")
  const [admitQuota, setAdmitQuota] = useState(path.admit_quota?.toString() ?? "")
  const updateMutation = useUpdatePathQuota()

  const handleSave = async () => {
    const rq = roundQuota.trim() === "" ? null : Number(roundQuota)
    const aq = admitQuota.trim() === "" ? null : Number(admitQuota)
    if (rq !== null && aq !== null && aq > rq) {
      toast.error("Trần admit phải ≤ trần submit. Giảm trần admit hoặc tăng trần submit.")
      return
    }
    try {
      await updateMutation.mutateAsync({
        pathId,
        data: { round_quota: rq, admit_quota: aq },
      })
      toast.success("Đã lưu chỉ tiêu")
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Lỗi lưu — kiểm tra mạng và thử lại."
      toast.error(msg)
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="round-quota">Trần submit (số hồ sơ tối đa)</Label>
          <Input
            id="round-quota"
            name="round_quota"
            type="number"
            inputMode="numeric"
            min="0"
            value={roundQuota}
            onChange={(e) => setRoundQuota(e.target.value)}
            placeholder="∞"
            autoComplete="off"
            disabled={!path.can_edit}
          />
          <p className="text-[11px] text-muted-foreground">
            Bỏ trống = không giới hạn số hồ sơ nộp.
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="admit-quota">Trần admit (số trúng tuyển tối đa)</Label>
          <Input
            id="admit-quota"
            name="admit_quota"
            type="number"
            inputMode="numeric"
            min="0"
            value={admitQuota}
            onChange={(e) => setAdmitQuota(e.target.value)}
            placeholder="—"
            autoComplete="off"
            disabled={!path.can_edit}
          />
          <p className="text-[11px] text-muted-foreground">
            Tier 1 ràng buộc với cap năm của ngành.
          </p>
        </div>
      </div>
      <div className="rounded-md border bg-muted/40 p-3 text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Đã nộp:</span>
          <span className="font-medium tabular-nums">{path.submission_count}</span>
        </div>
        <div className="text-muted-foreground">
          Tier 1 (admit ≤ cap năm) &amp; Tier 2 (admit ≤ submit) sẽ kiểm tra ở máy chủ.
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t pt-3">
        <Button variant="outline" onClick={onClose}>Đóng</Button>
        <Button
          onClick={handleSave}
          disabled={!path.can_edit || updateMutation.isPending}
          aria-busy={updateMutation.isPending}
        >
          {updateMutation.isPending ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4 mr-1" aria-hidden="true" />
          )}
          Lưu chỉ tiêu
        </Button>
      </div>
    </div>
  )
}

// ============================================================================
// Tab: Định danh (Identity)
// ============================================================================

function IdentityTab({
  path,
  pathId,
  onClose,
}: {
  path: PathLike
  pathId: number
  onClose: () => void
}) {
  const [displayName, setDisplayName] = useState(path.display_name ?? "")
  const [displayOrder, setDisplayOrder] = useState(path.display_order.toString())
  const [visibility, setVisibility] = useState<string>(path.visibility)
  const [applicationFee, setApplicationFee] = useState(
    path.application_fee?.toString() ?? "",
  )
  const [allowUnverified, setAllowUnverified] = useState(path.allow_unverified_submission)
  const updateMutation = useUpdateAdmissionPath()

  const handleSave = async () => {
    try {
      await updateMutation.mutateAsync({
        pathId,
        data: {
          display_name: displayName.trim() || null,
          display_order: Number(displayOrder),
          visibility: visibility as "public" | "internal",
          application_fee:
            applicationFee.trim() === "" ? null : Number(applicationFee),
          allow_unverified_submission: allowUnverified,
        },
      })
      toast.success("Đã lưu định danh")
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Lỗi lưu — kiểm tra mạng và thử lại."
      toast.error(msg)
    }
  }

  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="display-name">Tên hiển thị</Label>
        <Input
          id="display-name"
          name="display_name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          disabled={!path.can_edit}
          placeholder="VD: CNTT 2026 — Học bạ…"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="display-order">Thứ tự hiển thị</Label>
          <Input
            id="display-order"
            name="display_order"
            type="number"
            inputMode="numeric"
            min="0"
            value={displayOrder}
            onChange={(e) => setDisplayOrder(e.target.value)}
            autoComplete="off"
            disabled={!path.can_edit}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="visibility">Phạm vi hiển thị</Label>
          <Select
            value={visibility}
            onValueChange={setVisibility}
            disabled={!path.can_edit}
          >
            <SelectTrigger id="visibility"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="public">Công khai (storefront)</SelectItem>
              <SelectItem value="internal">Nội bộ (chỉ admin)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="app-fee">Lệ phí xét tuyển (VND)</Label>
        <Input
          id="app-fee"
          name="application_fee"
          type="number"
          inputMode="numeric"
          min="0"
          value={applicationFee}
          onChange={(e) => setApplicationFee(e.target.value)}
          placeholder="0 hoặc bỏ trống = miễn phí…"
          autoComplete="off"
          disabled={!path.can_edit}
        />
      </div>

      <div className="flex items-start gap-2 rounded-md border p-3">
        <Checkbox
          id="allow-unverified"
          checked={allowUnverified}
          onCheckedChange={(checked) => setAllowUnverified(checked === true)}
          disabled={!path.can_edit}
          className="mt-0.5"
        />
        <div className="flex-1">
          <Label htmlFor="allow-unverified" className="cursor-pointer">
            Cho phép nộp khi chưa xác minh giấy tờ
          </Label>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Chế độ legacy. Tắt = bắt buộc xác minh trước khi nộp.
          </p>
        </div>
      </div>

      <div className="rounded-md border bg-muted/40 p-3 text-xs space-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Phương thức:</span>
          <span className="font-medium" translate="no">
            {path.admission_method?.code ?? `#${path.admission_method_id}`}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Mã tiêu chí:</span>
          <span className="font-medium font-mono text-[11px]" translate="no">
            {path.criteria?.code ?? "—"}
          </span>
        </div>
        <p className="text-muted-foreground mt-1">
          Phương thức &amp; tiêu chí khoá sau khi tạo (3-col UNIQUE + invariant ADM-003).
        </p>
      </div>

      <div className="flex justify-end gap-2 border-t pt-3">
        <Button variant="outline" onClick={onClose}>Đóng</Button>
        <Button
          onClick={handleSave}
          disabled={!path.can_edit || updateMutation.isPending}
          aria-busy={updateMutation.isPending}
        >
          {updateMutation.isPending ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="h-4 w-4 mr-1" aria-hidden="true" />
          )}
          Lưu định danh
        </Button>
      </div>
    </div>
  )
}

// ============================================================================
// Tab: Vòng đời (Lifecycle)
// ============================================================================

function LifecycleTab({
  path,
  pathId,
  onClose,
}: {
  path: PathLike
  pathId: number
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const activateMutation = useActivateAdmissionPath()
  const deactivateMutation = useDeactivateAdmissionPath()

  const hasCriteria = path.criteria !== null
  const hasQuota = path.admit_quota !== null && path.admit_quota > 0
  const errors = path.validation_errors ?? []

  const handleActivate = async () => {
    try {
      await activateMutation.mutateAsync(pathId)
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
      toast.success("Đã kích hoạt đường tuyển sinh")
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Lỗi kích hoạt — kiểm tra checklist và thử lại."
      toast.error(msg)
    }
  }

  const handleDeactivate = async () => {
    if (!confirm("Vô hiệu hoá đường tuyển sinh này? Storefront sẽ ẩn ngay.")) return
    try {
      await deactivateMutation.mutateAsync(pathId)
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
      toast.success("Đã vô hiệu hoá đường tuyển sinh")
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Lỗi vô hiệu hoá — thử lại sau."
      toast.error(msg)
    }
  }

  const isActive = path.status === "active"
  const isPending = activateMutation.isPending || deactivateMutation.isPending

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground">Trạng thái hiện tại</Label>
        <div>
          <Badge variant={isActive ? "default" : "outline"} className="text-sm">
            {pathStatusLabel(path.status)}
          </Badge>
        </div>
      </div>

      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground">
          Checklist sẵn sàng kích hoạt
        </Label>
        <ul className="space-y-1.5 text-sm">
          <ChecklistRow
            ok={hasCriteria}
            label="Đã cấu hình tiêu chí (tổ hợp môn + điểm sàn)"
          />
          <ChecklistRow
            ok={hasQuota}
            label={`Đã đặt trần admit (hiện tại: ${path.admit_quota ?? "—"})`}
          />
          {errors.length === 0 ? (
            <ChecklistRow ok label="Không có lỗi xác thực từ máy chủ" />
          ) : (
            <li className="flex items-start gap-2 text-destructive">
              <XCircle className="h-4 w-4 mt-0.5 shrink-0" aria-hidden="true" />
              <div>
                <div className="font-medium">Lỗi xác thực từ máy chủ</div>
                <ul className="text-xs mt-0.5 space-y-0.5 ml-1">
                  {errors.map((err, i) => (
                    <li key={i}>• {err}</li>
                  ))}
                </ul>
              </div>
            </li>
          )}
        </ul>
      </div>

      {!path.can_activate && !isActive && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3 text-xs flex gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <div className="font-medium text-amber-900 dark:text-amber-200">
              Chưa thể kích hoạt
            </div>
            <p className="text-muted-foreground mt-0.5">
              Hoàn tất checklist phía trên trước khi kích hoạt.
            </p>
          </div>
        </div>
      )}

      <div className="flex justify-end gap-2 border-t pt-3">
        <Button variant="outline" onClick={onClose}>Đóng</Button>
        {isActive ? (
          <Button
            variant="destructive"
            onClick={handleDeactivate}
            disabled={isPending}
            aria-busy={isPending}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            ) : (
              <PowerOff className="h-4 w-4 mr-1" aria-hidden="true" />
            )}
            Vô hiệu hoá
          </Button>
        ) : (
          <Button
            onClick={handleActivate}
            disabled={!path.can_activate || isPending}
            aria-busy={isPending}
          >
            {isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            ) : (
              <Power className="h-4 w-4 mr-1" aria-hidden="true" />
            )}
            Kích hoạt
          </Button>
        )}
      </div>
    </div>
  )
}

function ChecklistRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className="flex items-start gap-2">
      {ok ? (
        <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" aria-hidden="true" />
      ) : (
        <XCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" aria-hidden="true" />
      )}
      <span className={ok ? "" : "text-muted-foreground"}>{label}</span>
    </li>
  )
}
