"use client"

/**
 * GĐ2-F1 — soạn bảng chỉ tiêu năm (thay TOÀN BỘ nội dung qua PUT, `version` của bảng đang xem; 0 = tạo mới).
 *
 * Ô chỉ tiêu ngành / trần nhóm là chuỗi đúng như gõ: TRỐNG ⇒ gửi `null` (máy chủ 422 — chưa nhập), KHÔNG thành 0
 * (quyết định owner 19-11 câu 4). Giao diện không cộng / so chỉ tiêu, không kiểm trùng: máy chủ là chốt (400 / 409 / 422
 * ⇒ câu theo mã). Danh sách ngành để thêm = học vụ của ĐÚNG năm (dữ liệu máy chủ), chỉ lọc để hiển thị.
 */
import { useId, useMemo, useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSaveQuotaTable } from "@/lib/hooks/use-quota-tables"
import {
  countToInput,
  draftToPutBody,
  newGroupKey,
  type DraftGroup,
  type DraftMember,
} from "@/lib/quota-tables/draft"
import { describeQuotaTableError } from "@/lib/quota-tables/messages"

export interface MemberOption {
  offering_academic_info_id: number
  label: string
  /** Chỉ tiêu năm HIỆN CÓ của học vụ (null = chưa có) — điền sẵn vào ô khi thêm ngành, không đặt mặc định. */
  annual_admission_quota: number | null
}

interface Props {
  year: number
  /** Phiên bản bảng đang xem; 0 = năm chưa có bảng. */
  version: number
  /** GĐ2-F1 — dấu chỉ tiêu của năm lúc mở (GET; năm chưa có bảng: thân 404). */
  quotaFingerprint: string
  initialGroups: DraftGroup[]
  options: MemberOption[]
  labelOf: (offeringAcademicInfoId: number) => string
  onCancel: () => void
  onSaved: () => void
}

const NUMBER_INPUT_CLASS = "w-28 text-right tabular-nums"

export function QuotaTableEditor({
  year,
  version: versionProp,
  quotaFingerprint: quotaFingerprintProp,
  initialGroups,
  options,
  labelOf,
  onCancel,
  onSaved,
}: Props) {
  const baseId = useId()
  // Phiên bản CHỐT lúc mở soạn: bảng được làm mới sau lỗi (vd 409 stale) KHÔNG được âm thầm nâng phiên bản của bản nháp —
  // nếu không, bấm Lưu lần nữa sẽ đè thay đổi của người khác mà người soạn chưa xem.
  const [version] = useState(versionProp)
  // GĐ2-F1 (điểm chặn Codex): dấu chỉ tiêu cũng CHỐT lúc mở — chỉ tiêu ngành sửa ở trang khác sau đó ⇒ máy chủ 409, không đè.
  const [quotaFingerprint] = useState(quotaFingerprintProp)
  const [groups, setGroups] = useState<DraftGroup[]>(initialGroups)
  const [error, setError] = useState<string | null>(null)
  const save = useSaveQuotaTable(year)

  const usedIds = useMemo(
    () => new Set(groups.flatMap((g) => g.members.map((m) => m.offering_academic_info_id))),
    [groups],
  )
  const freeOptions = options.filter((o) => !usedIds.has(o.offering_academic_info_id))

  const updateGroup = (key: string, patch: Partial<DraftGroup>) =>
    setGroups((gs) => gs.map((g) => (g.key === key ? { ...g, ...patch } : g)))
  const updateMember = (key: string, id: number, patch: Partial<DraftMember>) =>
    setGroups((gs) =>
      gs.map((g) =>
        g.key === key
          ? { ...g, members: g.members.map((m) => (m.offering_academic_info_id === id ? { ...m, ...patch } : m)) }
          : g,
      ),
    )
  const removeMember = (key: string, id: number) =>
    setGroups((gs) =>
      gs.map((g) => (g.key === key ? { ...g, members: g.members.filter((m) => m.offering_academic_info_id !== id) } : g)),
    )
  const addMember = (key: string, rawId: string) => {
    const opt = options.find((o) => String(o.offering_academic_info_id) === rawId)
    if (!opt) return
    setGroups((gs) =>
      gs.map((g) =>
        g.key === key
          ? {
              ...g,
              members: [
                ...g.members,
                {
                  offering_academic_info_id: opt.offering_academic_info_id,
                  label: opt.label,
                  quota: countToInput(opt.annual_admission_quota),
                },
              ],
            }
          : g,
      ),
    )
  }
  const addGroup = () =>
    setGroups((gs) => [...gs, { key: newGroupKey(), code: "", name: "", ceiling: "", members: [] }])
  const removeGroup = (key: string) => setGroups((gs) => gs.filter((g) => g.key !== key))

  const submit = () => {
    setError(null)
    save.mutate(draftToPutBody(version, quotaFingerprint, groups), {
      onSuccess: () => {
        toast.success(version === 0 ? `Đã tạo bảng chỉ tiêu năm ${year}` : `Đã lưu bảng chỉ tiêu năm ${year}`)
        onSaved()
      },
      onError: (e) => setError(describeQuotaTableError(e, { year, labelOf, draft: groups })),
    })
  }

  return (
    <div className="space-y-4" data-testid="bang-chi-tieu-soan">
      <p className="text-sm text-muted-foreground">
        Ô để trống nghĩa là <strong>chưa nhập</strong> — máy chủ sẽ không nhận. Nhập 0 chỉ khi chỉ tiêu / trần thật sự bằng 0.
        Lưu sẽ thay toàn bộ nội dung bảng của năm {year}.
      </p>

      {groups.map((g, gi) => (
        <Card key={g.key} data-testid={`soan-nhom-${gi}`}>
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <Label htmlFor={`${baseId}-${g.key}-ma`}>Mã nhóm</Label>
                <Input
                  id={`${baseId}-${g.key}-ma`}
                  value={g.code}
                  maxLength={30}
                  onChange={(e) => updateGroup(g.key, { code: e.target.value })}
                  className="w-32"
                />
              </div>
              <div className="min-w-[200px] flex-1 space-y-1">
                <Label htmlFor={`${baseId}-${g.key}-ten`}>Tên nhóm</Label>
                <Input
                  id={`${baseId}-${g.key}-ten`}
                  value={g.name}
                  maxLength={255}
                  onChange={(e) => updateGroup(g.key, { name: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`${baseId}-${g.key}-tran`}>Trần chỉ tiêu nhóm</Label>
                <Input
                  id={`${baseId}-${g.key}-tran`}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  step={1}
                  placeholder="Trống"
                  value={g.ceiling}
                  onChange={(e) => updateGroup(g.key, { ceiling: e.target.value })}
                  className={NUMBER_INPUT_CLASS}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => removeGroup(g.key)}
                aria-label={`Xoá nhóm ${g.code || gi + 1}`}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {g.members.length === 0 && <p className="text-sm text-muted-foreground">Nhóm chưa có ngành nào.</p>}
            {g.members.map((m) => {
              const inputId = `${baseId}-${g.key}-ct-${m.offering_academic_info_id}`
              return (
                <div key={m.offering_academic_info_id} className="flex flex-wrap items-center gap-3">
                  <Label htmlFor={inputId} className="min-w-[200px] flex-1 font-normal">
                    Chỉ tiêu năm — {m.label}
                  </Label>
                  <Input
                    id={inputId}
                    type="number"
                    inputMode="numeric"
                    min={0}
                    step={1}
                    placeholder="Trống"
                    value={m.quota}
                    onChange={(e) => updateMember(g.key, m.offering_academic_info_id, { quota: e.target.value })}
                    className={NUMBER_INPUT_CLASS}
                  />
                  {m.quota.trim() === "" && (
                    <span className="text-xs text-warning-700" data-testid={`o-trong-${m.offering_academic_info_id}`}>
                      Trống — chưa nhập
                    </span>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeMember(g.key, m.offering_academic_info_id)}
                    aria-label={`Bỏ ${m.label} khỏi nhóm`}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
              )
            })}
            <div className="pt-1">
              <Label htmlFor={`${baseId}-${g.key}-them`} className="sr-only">
                Thêm ngành vào nhóm
              </Label>
              <select
                id={`${baseId}-${g.key}-them`}
                value=""
                onChange={(e) => addMember(g.key, e.target.value)}
                disabled={freeOptions.length === 0}
                className="h-9 w-full max-w-md rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">
                  {freeOptions.length === 0 ? "Không còn ngành nào của năm để thêm" : "+ Thêm ngành của năm vào nhóm…"}
                </option>
                {freeOptions.map((o) => (
                  <option key={o.offering_academic_info_id} value={String(o.offering_academic_info_id)}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </CardContent>
        </Card>
      ))}

      <Button type="button" variant="outline" size="sm" onClick={addGroup}>
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
        Thêm nhóm ngành
      </Button>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={save.isPending}>
          Huỷ
        </Button>
        <Button type="button" onClick={submit} disabled={save.isPending} data-testid="luu-bang">
          {save.isPending ? "Đang lưu…" : version === 0 ? "Tạo bảng" : "Lưu bảng"}
        </Button>
      </div>
    </div>
  )
}
