/**
 * SubjectGroupConfigTab — admin quản lý path_subject_group_config (#7).
 *
 * Tab "Tổ hợp môn" cho hồ sơ multi-NV: thêm/sửa/xóa tổ hợp (điểm sàn, quota
 * Tier 3, môn chính) + gợi ý đồng bộ từ tiêu chí (drift hint). Độc lập với
 * criteria_subject_group — KHÔNG auto-sync, chỉ gợi ý.
 *
 * Thin-client: hiển thị + bật control theo path.can_manage_subject_group_configs
 * (admin-only + not-archived, server enforce). KHÔNG check role.
 */
"use client"

import { Check, ChevronsUpDown, Loader2, Plus, Star, Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
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
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  useAddPathSubjectGroupItem,
  useCreatePathSubjectGroupConfig,
  useDeletePathSubjectGroupConfig,
  useDeletePathSubjectGroupItem,
  usePathSubjectGroupConfigsAdmin,
  useUpdatePathSubjectGroupConfig,
  useUpdatePathSubjectGroupItem,
} from "@/hooks/admissions/usePathSubjectGroupConfigs"
import { useSubjectGroups } from "@/hooks/admissions/useMasterData"
import type { PathSubjectGroupConfigAdmin } from "@/lib/api/admission-paths"
import { parseApiError } from "@/lib/utils/api-errors"
import { cn } from "@/lib/utils"
import { foldVietnamese } from "@/lib/utils/vietnamese"
import type { AdmissionPathResponse } from "@/lib/zod/admission-path"

/**
 * Parse a numeric input. "" → null (clear). Returns ``undefined`` for anything
 * invalid (NaN / Infinity / negative / non-integer when required) so the caller
 * BLOCKS instead of POSTing junk — Number() otherwise accepts "1e2"→100,
 * "0x10"→16, "-5", "3.7", and "Infinity"→null (silently read as "clear").
 */
function numOrNull(
  s: string,
  opts?: { integer?: boolean },
): number | null | undefined {
  const t = s.trim()
  if (t === "") return null
  const n = Number(t)
  if (!Number.isFinite(n) || n < 0) return undefined
  if (opts?.integer && !Number.isInteger(n)) return undefined
  return n
}

export function SubjectGroupConfigTab({
  path,
  pathId,
  onClose,
}: {
  path: AdmissionPathResponse
  pathId: number
  onClose: () => void
}) {
  const canManage = path.can_manage_subject_group_configs ?? false
  const { data, isLoading } = usePathSubjectGroupConfigsAdmin(pathId, canManage)
  const configs = data?.items ?? []
  const { data: allGroups } = useSubjectGroups()

  const createMut = useCreatePathSubjectGroupConfig()
  const updateMut = useUpdatePathSubjectGroupConfig()
  const deleteMut = useDeletePathSubjectGroupConfig()

  const [pickerOpen, setPickerOpen] = useState(false)
  const [newGroupId, setNewGroupId] = useState<number | null>(null)
  const [newMinScore, setNewMinScore] = useState("")
  const [newGroupQuota, setNewGroupQuota] = useState("")

  // #1: store only the configId; derive the LIVE config from the (refetched)
  // list so the dialog reflects item add/remove instead of a frozen snapshot.
  const [principalCfgId, setPrincipalCfgId] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] =
    useState<PathSubjectGroupConfigAdmin | null>(null)
  // Per-chip pending: a local Set (NOT createMut.variables, which only holds
  // the last call) so concurrent drift-chip creates each track independently —
  // a double-click on one chip can't re-POST (→ 409) while others stay usable.
  const [creatingIds, setCreatingIds] = useState<ReadonlySet<number>>(
    new Set<number>(),
  )

  const configuredIds = new Set(configs.map((c) => c.subject_group_id))
  const groups = (allGroups ?? []) as { id: number; code: string; name: string }[]
  const available = groups.filter((g) => !configuredIds.has(g.id))
  // Drift: tổ hợp có trong tiêu chí nhưng chưa có config (criteria nullable).
  const missing = (path.criteria?.subject_groups ?? []).filter(
    (g) => !configuredIds.has(g.id),
  )
  const liveCfg = configs.find((c) => c.id === principalCfgId) ?? null

  const newGroupLabel = (() => {
    const g = groups.find((x) => x.id === newGroupId)
    return g ? `${g.code} — ${g.name}` : "Chọn tổ hợp môn…"
  })()

  const doCreate = async (
    subjectGroupId: number,
    minScore: number | null,
    groupQuota: number | null,
  ) => {
    setCreatingIds((s) => new Set(s).add(subjectGroupId))
    try {
      await createMut.mutateAsync({
        pathId,
        data: {
          subject_group_id: subjectGroupId,
          min_score: minScore,
          group_quota: groupQuota,
        },
      })
      toast.success("Đã thêm tổ hợp môn")
      setNewGroupId(null)
      setNewMinScore("")
      setNewGroupQuota("")
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi thêm tổ hợp — thử lại."))
    } finally {
      setCreatingIds((s) => {
        const n = new Set(s)
        n.delete(subjectGroupId)
        return n
      })
    }
  }

  const handleAddClick = () => {
    if (newGroupId == null) return
    const ms = numOrNull(newMinScore)
    const gq = numOrNull(newGroupQuota, { integer: true })
    if (ms === undefined || gq === undefined) {
      toast.error("Điểm sàn (≥0) / quota (số nguyên ≥0) không hợp lệ.")
      return
    }
    void doCreate(newGroupId, ms, gq)
  }

  const handleDelete = async (cfg: PathSubjectGroupConfigAdmin) => {
    try {
      await deleteMut.mutateAsync({ pathId, configId: cfg.id })
      toast.success("Đã xóa tổ hợp môn")
      setConfirmDelete(null)
    } catch (e: unknown) {
      // 409 (đang dùng) / 400 (Tier 3) → message thân thiện từ BE.
      toast.error(parseApiError(e, "Không xóa được tổ hợp."))
    }
  }

  if (!canManage) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        Chỉ admin mới quản lý được tổ hợp môn cho phương thức này (phương thức
        đã lưu trữ cũng không sửa được).
      </p>
    )
  }

  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">
        Tổ hợp môn cho hồ sơ đa nguyện vọng (multi-NV). Độc lập với &quot;Tiêu
        chí&quot; — sửa ở đây KHÔNG đổi tiêu chí và ngược lại.
      </p>

      {/* Drift hint: criteria có nhưng config thiếu */}
      {missing.length > 0 && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3 text-xs space-y-2">
          <div className="font-medium text-amber-900 dark:text-amber-200">
            {missing.length} tổ hợp có trong tiêu chí nhưng chưa có ở đây
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((g) => (
              <Button
                key={g.id}
                size="sm"
                variant="outline"
                className="h-7"
                disabled={creatingIds.has(g.id)}
                onClick={() => void doCreate(g.id, null, null)}
              >
                {creatingIds.has(g.id) ? (
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" aria-hidden="true" />
                ) : (
                  <Plus className="h-3 w-3 mr-1" aria-hidden="true" />
                )}
                {g.code}
              </Button>
            ))}
          </div>
          <p className="text-muted-foreground">
            &quot;Thêm nhanh&quot; tạo tổ hợp với điểm sàn/quota để trống —
            chỉnh sau ở bảng dưới.
          </p>
        </div>
      )}

      {/* Bảng tổ hợp hiện có */}
      {isLoading ? (
        <div className="flex items-center gap-2 py-6 text-muted-foreground" aria-live="polite">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          <span className="text-sm">Đang tải tổ hợp môn…</span>
        </div>
      ) : configs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">
          Chưa có tổ hợp môn nào. Thêm bên dưới.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tổ hợp</TableHead>
              <TableHead>Môn</TableHead>
              <TableHead className="w-24 text-right">Điểm sàn</TableHead>
              <TableHead className="w-24 text-right">Quota</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {configs.map((c) => (
              <ConfigRow
                // #5: re-key on server values so a successful save / another
                // admin's edit remounts the row with fresh inputs (no stale
                // value, no phantom "Lưu").
                key={`${c.id}:${c.min_score ?? ""}:${c.group_quota ?? ""}`}
                config={c}
                pathId={pathId}
                updateMut={updateMut}
                onPrincipal={() => setPrincipalCfgId(c.id)}
                onDelete={() => setConfirmDelete(c)}
              />
            ))}
          </TableBody>
        </Table>
      )}

      {/* Thêm tổ hợp */}
      <div className="rounded-md border p-3 space-y-3">
        <Label className="text-xs text-muted-foreground">Thêm tổ hợp môn</Label>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-[200px] space-y-1">
            <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  role="combobox"
                  aria-expanded={pickerOpen}
                  className="w-full justify-between font-normal"
                >
                  <span className="truncate">{newGroupLabel}</span>
                  <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                className="w-[var(--radix-popover-trigger-width)] p-0"
                align="start"
              >
                <Command
                  filter={(value, search) =>
                    foldVietnamese(value).includes(foldVietnamese(search)) ? 1 : 0
                  }
                >
                  <CommandInput placeholder="Gõ mã/tên tổ hợp…" />
                  <CommandList>
                    <CommandEmpty>Không còn tổ hợp để thêm.</CommandEmpty>
                    {available.map((g) => (
                      <CommandItem
                        key={g.id}
                        value={`${g.code} ${g.name} ${g.id}`}
                        onSelect={() => {
                          setNewGroupId(g.id)
                          setPickerOpen(false)
                        }}
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4 shrink-0",
                            newGroupId === g.id ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="flex-1 truncate">{g.name}</span>
                        <span className="ml-2 shrink-0 text-[11px] text-muted-foreground" translate="no">
                          {g.code}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>
          <div className="space-y-1 w-24">
            <Label htmlFor="new-min-score" className="text-[11px]">Điểm sàn</Label>
            <Input
              id="new-min-score"
              type="number"
              inputMode="decimal"
              min="0"
              value={newMinScore}
              onChange={(e) => setNewMinScore(e.target.value)}
              placeholder="—"
              autoComplete="off"
            />
          </div>
          <div className="space-y-1 w-24">
            <Label htmlFor="new-group-quota" className="text-[11px]">Quota</Label>
            <Input
              id="new-group-quota"
              type="number"
              inputMode="numeric"
              min="0"
              step="1"
              value={newGroupQuota}
              onChange={(e) => setNewGroupQuota(e.target.value)}
              placeholder="—"
              autoComplete="off"
            />
          </div>
          <Button
            onClick={handleAddClick}
            disabled={newGroupId == null || createMut.isPending}
            aria-busy={createMut.isPending}
          >
            {createMut.isPending ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
            ) : (
              <Plus className="h-4 w-4 mr-1" aria-hidden="true" />
            )}
            Thêm
          </Button>
        </div>
      </div>

      <div className="flex justify-end border-t pt-3">
        <Button variant="outline" onClick={onClose}>Đóng</Button>
      </div>

      {liveCfg && (
        <PrincipalItemsDialog
          config={liveCfg}
          pathId={pathId}
          onOpenChange={(o) => { if (!o) setPrincipalCfgId(null) }}
        />
      )}

      <Dialog
        open={confirmDelete != null}
        onOpenChange={(o) => { if (!o) setConfirmDelete(null) }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Xóa tổ hợp môn?</DialogTitle>
            <DialogDescription>
              Xóa tổ hợp{" "}
              <span className="font-medium" translate="no">
                {confirmDelete?.subject_group_code}
              </span>{" "}
              khỏi phương thức này. Không xóa được nếu đang có nguyện vọng dùng.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(null)}>
              Huỷ
            </Button>
            <Button
              variant="destructive"
              onClick={() => confirmDelete && void handleDelete(confirmDelete)}
              disabled={deleteMut.isPending}
              aria-busy={deleteMut.isPending}
            >
              {deleteMut.isPending ? (
                <Loader2 className="h-4 w-4 mr-1 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4 mr-1" aria-hidden="true" />
              )}
              Xóa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ============================================================================
// Row: 1 config — inline edit điểm sàn/quota + nút Môn chính / Xóa
// ============================================================================

function ConfigRow({
  config,
  pathId,
  updateMut,
  onPrincipal,
  onDelete,
}: {
  config: PathSubjectGroupConfigAdmin
  pathId: number
  updateMut: ReturnType<typeof useUpdatePathSubjectGroupConfig>
  onPrincipal: () => void
  onDelete: () => void
}) {
  // Init từ server value lúc mount. Parent re-key theo server value nên sau khi
  // lưu / refetch row remount với giá trị mới (không stale).
  const [minScore, setMinScore] = useState(config.min_score?.toString() ?? "")
  const [quota, setQuota] = useState(config.group_quota?.toString() ?? "")
  const principalCount = config.items.filter((it) => it.is_principal).length
  const parsedMin = numOrNull(minScore)
  const parsedQuota = numOrNull(quota, { integer: true })
  // #5: dirty so sánh theo SỐ (đã chuẩn hóa) — "5.0" vs 5 KHÔNG còn là dirty;
  // giá trị không hợp lệ coi như dirty để hiện nút Lưu (save sẽ chặn + toast).
  const dirty =
    parsedMin === undefined ||
    parsedQuota === undefined ||
    parsedMin !== (config.min_score ?? null) ||
    parsedQuota !== (config.group_quota ?? null)

  const save = async () => {
    if (parsedMin === undefined || parsedQuota === undefined) {
      toast.error("Điểm sàn (≥0) / quota (số nguyên ≥0) không hợp lệ.")
      return
    }
    try {
      await updateMut.mutateAsync({
        pathId,
        configId: config.id,
        data: { min_score: parsedMin, group_quota: parsedQuota },
      })
      toast.success("Đã lưu tổ hợp")
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi lưu tổ hợp."))
    }
  }

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium" translate="no">{config.subject_group_code}</div>
        <div className="text-[11px] text-muted-foreground">
          {config.subject_group_name}
        </div>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        <div className="flex flex-wrap gap-1">
          {config.subjects.map((s) => {
            const item = config.items.find(
              (it) => it.subject_group_subject_id === s.subject_group_subject_id,
            )
            return (
              <Badge
                key={s.subject_group_subject_id}
                variant={item?.is_principal ? "default" : "outline"}
                className="text-[10px] h-4 px-1 gap-0.5"
                translate="no"
              >
                {item?.is_principal && <Star className="h-2.5 w-2.5" aria-hidden="true" />}
                {s.subject_code}
              </Badge>
            )
          })}
        </div>
        {principalCount > 0 && (
          <span className="text-[10px]">({principalCount} môn chính)</span>
        )}
      </TableCell>
      <TableCell className="text-right">
        <Input
          type="number"
          inputMode="decimal"
          min="0"
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
          className="h-8 text-right"
          placeholder="—"
          aria-label={`Điểm sàn ${config.subject_group_code}`}
        />
      </TableCell>
      <TableCell className="text-right">
        <Input
          type="number"
          inputMode="numeric"
          min="0"
          step="1"
          value={quota}
          onChange={(e) => setQuota(e.target.value)}
          className="h-8 text-right"
          placeholder="—"
          aria-label={`Quota ${config.subject_group_code}`}
        />
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          {dirty && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2"
              onClick={() => void save()}
              disabled={updateMut.isPending}
            >
              Lưu
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={onPrincipal}
            title="Môn chính"
          >
            <Star className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="sr-only">Môn chính</span>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-destructive"
            onClick={onDelete}
            title="Xóa tổ hợp"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="sr-only">Xóa</span>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

// ============================================================================
// Dialog: Môn chính per config — toggle is_principal (tạo/xóa item)
// ============================================================================

function PrincipalItemsDialog({
  config,
  pathId,
  onOpenChange,
}: {
  config: PathSubjectGroupConfigAdmin
  pathId: number
  onOpenChange: (open: boolean) => void
}) {
  const addItem = useAddPathSubjectGroupItem()
  const updateItem = useUpdatePathSubjectGroupItem()
  const deleteItem = useDeletePathSubjectGroupItem()
  // #3/#2: pending theo TỪNG môn — Set (không phải 1-slot) để thao tác môn A
  // rồi B khi A chưa xong KHÔNG tắt sớm spinner A / mở lại A.
  const [pendingSgs, setPendingSgs] = useState<ReadonlySet<number>>(
    new Set<number>(),
  )

  const itemFor = (sgsId: number) =>
    config.items.find((it) => it.subject_group_subject_id === sgsId)

  const run = async (sgsId: number, fn: () => Promise<unknown>) => {
    setPendingSgs((s) => new Set(s).add(sgsId))
    try {
      await fn()
    } catch (e: unknown) {
      toast.error(parseApiError(e, "Lỗi cập nhật môn chính."))
    } finally {
      setPendingSgs((s) => {
        const n = new Set(s)
        n.delete(sgsId)
        return n
      })
    }
  }

  const togglePrincipal = (sgsId: number, checked: boolean) => {
    const item = itemFor(sgsId)
    void run(sgsId, () =>
      !item
        ? addItem.mutateAsync({
            pathId,
            configId: config.id,
            data: { subject_group_subject_id: sgsId, is_principal: checked },
          })
        : updateItem.mutateAsync({
            pathId,
            configId: config.id,
            itemId: item.id,
            data: { is_principal: checked },
          }),
    )
  }

  const removeItem = (sgsId: number) => {
    const item = itemFor(sgsId)
    if (!item) return
    void run(sgsId, () =>
      deleteItem.mutateAsync({ pathId, configId: config.id, itemId: item.id }),
    )
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Môn chính —{" "}
            <span translate="no">{config.subject_group_code}</span>
          </DialogTitle>
          <DialogDescription>
            Đánh dấu môn chính của tổ hợp. Lưu sẵn cấu hình —{" "}
            <span className="font-medium">chưa ảnh hưởng chấm điểm</span> (engine
            hiện dùng trọng số tổ hợp + điểm sàn tiêu chí); sẽ dùng ở bước sau.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 max-h-[50vh] overflow-y-auto">
          {config.subjects.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Tổ hợp chưa khai báo môn (cấu hình ở master tổ hợp môn).
            </p>
          )}
          {config.subjects.map((s) => {
            const item = itemFor(s.subject_group_subject_id)
            const rowPending = pendingSgs.has(s.subject_group_subject_id)
            return (
              <div
                key={s.subject_group_subject_id}
                className="flex items-center gap-2 rounded-md border p-2"
              >
                <Checkbox
                  checked={item?.is_principal ?? false}
                  disabled={rowPending}
                  onCheckedChange={(v) =>
                    togglePrincipal(s.subject_group_subject_id, v === true)
                  }
                  aria-label={`Môn chính ${s.subject_code}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate" translate="no">
                    {s.subject_code}
                  </div>
                  <div className="text-[11px] text-muted-foreground truncate">
                    {s.subject_name}
                  </div>
                </div>
                {rowPending && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
                )}
                {item && !rowPending && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-destructive"
                    onClick={() => removeItem(s.subject_group_subject_id)}
                    title="Gỡ cấu hình môn"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">Gỡ</span>
                  </Button>
                )}
              </div>
            )
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Đóng
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
