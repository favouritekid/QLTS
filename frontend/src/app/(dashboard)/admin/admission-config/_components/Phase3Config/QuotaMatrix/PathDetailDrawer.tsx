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
  Archive,
  CheckCircle2,
  Loader2,
  Power,
  PowerOff,
  Save,
  XCircle,
} from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useMemo, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  useArchiveAdmissionPath,
  useDeactivateAdmissionPath,
  useUpdateAdmissionPath,
} from "@/hooks/admissions/useAdmissionPaths"
import {
  quotaMatrixKeys,
  useUpdatePathQuota,
} from "@/hooks/admissions/useQuotaMatrix"
import { parseApiError } from "@/lib/utils/api-errors"
import type { AdmissionPathResponse } from "@/lib/zod/admission-path"

import { ConfigCriteria } from "../ConfigCriteria"
import { ConfigDocuments } from "../ConfigDocuments"
import { AdvancedTab } from "./AdvancedTab"
import { pathStatusLabel } from "./labels"

type PathLike = AdmissionPathResponse

interface Props {
  pathId: number
  onClose: () => void
}

const VALID_TABS = [
  "quota",
  "identity",
  "criteria",
  "documents",
  "advanced",
  "lifecycle",
] as const
type TabId = (typeof VALID_TABS)[number]

export function PathDetailDrawer({ pathId, onClose }: Props) {
  const { data: path, isLoading } = useAdmissionPath(pathId)

  // Thẻ "Nâng cao" (governance) gate theo computed flag `can_edit_governance`
  // từ API (thin-client) thay vì `user.role === "admin"`. Máy chủ enforce
  // server-side (BusinessRuleViolation khi non-admin ghi governance); flag
  // này chỉ mirror cho UX. `path` async undefined → canGov=false an toàn.
  const canGov = path?.can_edit_governance ?? false

  // Pass 2 hard-review FM-2: tab active sync với ?tab= URL param.
  // Reload page giữ tab user đang xem; share link mở thẳng tab cụ thể.
  // Default = "quota" nếu URL không có hoặc invalid value.
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const tab: TabId = useMemo(() => {
    const raw = searchParams.get("tab")
    const valid = (VALID_TABS as readonly string[]).includes(raw ?? "")
      ? (raw as TabId)
      : "quota"
    // Non-gov dán ?tab=advanced → fallback "quota" (tránh rơi vào thẻ ẩn).
    return valid === "advanced" && !canGov ? "quota" : valid
  }, [searchParams, canGov])
  const setTab = useCallback(
    (next: string) => {
      // Idempotent guard: Radix Tabs + React 19 effects có thể fire
      // onValueChange 2x per click với same value (no-op double dispatch).
      // Verified via Phase B.1 runtime debug 2026-05-11.
      if (next === tab) return
      const params = new URLSearchParams(searchParams.toString())
      if (next === "quota") params.delete("tab")
      else params.set("tab", next)
      const qs = params.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [pathname, router, searchParams, tab],
  )

  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent className="sm:max-w-3xl w-full flex flex-col overflow-hidden">
        <SheetHeader className="pr-8">
          <SheetTitle className="text-pretty">
            {path?.display_name || `Phương thức tuyển sinh #${pathId}`}
          </SheetTitle>
          <SheetDescription className="sr-only">
            Cấu hình chi tiết phương thức tuyển sinh: chỉ tiêu, định danh, tiêu chí, giấy tờ, vòng đời.
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
            <span className="sr-only">Đang tải chi tiết phương thức tuyển sinh…</span>
          </div>
        )}

        {path && (
          // Pass 2 hard-review F-2-3: ``key={pathId}`` ép Tabs subtree remount
          // khi parent giữ drawer mở rồi swap path khác (vd drill-down từ
          // AggregateDrawer sang path khác). Nếu không có key, QuotaTab /
          // IdentityTab / LifecycleTab giữ ``useState`` initial value của
          // path cũ → user save = ghi đè path mới với data path cũ.
          <Tabs
            key={pathId}
            value={tab}
            onValueChange={setTab}
            className="flex-1 flex flex-col min-h-0"
          >
            <TabsList
              className={`flex w-full justify-start overflow-x-auto shrink-0 sm:grid sm:justify-center ${
                canGov ? "sm:grid-cols-6" : "sm:grid-cols-5"
              }`}
            >
              <TabsTrigger value="quota">Chỉ tiêu</TabsTrigger>
              <TabsTrigger value="identity">Định danh</TabsTrigger>
              <TabsTrigger value="criteria">Tiêu chí</TabsTrigger>
              <TabsTrigger value="documents">Giấy tờ</TabsTrigger>
              {canGov && (
                <TabsTrigger value="advanced">Nâng cao</TabsTrigger>
              )}
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
              {canGov && (
                <TabsContent value="advanced">
                  <AdvancedTab path={path} pathId={pathId} onClose={onClose} />
                </TabsContent>
              )}
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
      toast.error(parseApiError(e, "Lỗi lưu — kiểm tra mạng và thử lại."))
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
          <span
            className="text-muted-foreground"
            title="Bộ đếm cổng Tier-2 (đơn nguyện vọng). KHÔNG tăng cho hồ sơ multi-nguyện-vọng nên có thể lệch với số 'Hồ sơ' ở ô ma trận (đếm thực)."
          >
            Đã nộp (cổng Tier-2):
          </span>
          <span className="font-medium tabular-nums">{path.submission_count}</span>
        </div>
        <div className="text-muted-foreground">
          Bộ đếm cổng đơn-nguyện-vọng; số &quot;Hồ sơ&quot; ở ô ma trận đếm
          thực (gồm multi-nguyện-vọng) nên có thể khác.
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
      toast.error(parseApiError(e, "Lỗi lưu — kiểm tra mạng và thử lại."))
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
  const archiveMutation = useArchiveAdmissionPath()
  // Pass 2 hard-review FM-1: custom Dialog confirm thay JS confirm()
  // (mobile UX kém + a11y kém — không có focus trap, không styled).
  const [confirmDeactivate, setConfirmDeactivate] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)

  const hasCriteria = path.criteria !== null
  const hasQuota = path.admit_quota !== null && path.admit_quota > 0
  const errors = path.validation_errors ?? []

  const handleActivate = async () => {
    try {
      await activateMutation.mutateAsync(pathId)
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
      toast.success("Đã kích hoạt phương thức tuyển sinh")
      onClose()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi kích hoạt — kiểm tra checklist và thử lại."))
    }
  }

  const performDeactivate = async () => {
    setConfirmDeactivate(false)
    try {
      await deactivateMutation.mutateAsync(pathId)
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
      toast.success("Đã vô hiệu hoá phương thức tuyển sinh")
      onClose()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi vô hiệu hoá — thử lại sau."))
    }
  }

  const performArchive = async () => {
    setConfirmArchive(false)
    try {
      await archiveMutation.mutateAsync(pathId)
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
      toast.success("Đã lưu trữ phương thức tuyển sinh")
      onClose()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi lưu trữ — thử lại sau."))
    }
  }

  const isActive = path.status === "active"
  const isArchived = path.status === "archived"
  // Archive khả dụng cho draft/inactive (BE chặn active: phải deactivate
  // trước; chặn archived: terminal). Cho admin retire path thừa qua UI.
  const canArchive = !isActive && !isArchived
  const isPending =
    activateMutation.isPending ||
    deactivateMutation.isPending ||
    archiveMutation.isPending

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
                  {errors.map((err) => (
                    <li key={err}>• {err}</li>
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
            onClick={() => setConfirmDeactivate(true)}
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
          <>
            {canArchive && (
              <Button
                variant="outline"
                onClick={() => setConfirmArchive(true)}
                disabled={isPending}
                aria-busy={isPending}
              >
                {isPending ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
                ) : (
                  <Archive className="h-4 w-4 mr-1" aria-hidden="true" />
                )}
                Lưu trữ
              </Button>
            )}
            {!isArchived && (
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
          </>
        )}
      </div>

      {/* Pass 2 hard-review FM-1: custom Dialog confirm thay JS confirm() —
          focus trap + styled + a11y-friendly trên mobile. */}
      <Dialog open={confirmDeactivate} onOpenChange={setConfirmDeactivate}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Vô hiệu hoá phương thức tuyển sinh?</DialogTitle>
            <DialogDescription>
              Storefront sẽ ẩn ngay phương thức tuyển sinh này. Người dùng đã
              nộp hồ sơ vẫn giữ snapshot path; chỉ submission mới bị chặn.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDeactivate(false)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={performDeactivate}
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
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmArchive} onOpenChange={setConfirmArchive}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Lưu trữ phương thức tuyển sinh?</DialogTitle>
            <DialogDescription>
              Phương thức tuyển sinh sẽ chuyển sang trạng thái lưu trữ
              (archived) — ẩn khỏi danh mục cấu hình và không thể chỉnh sửa
              hay kích hoạt lại. Dùng để gỡ các đường nháp/đã vô hiệu không
              còn dùng. Hồ sơ đã nộp (nếu có) giữ nguyên snapshot path.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmArchive(false)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={performArchive}
              disabled={isPending}
              aria-busy={isPending}
            >
              {isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
              ) : (
                <Archive className="h-4 w-4 mr-1" aria-hidden="true" />
              )}
              Lưu trữ
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
