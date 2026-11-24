/**
 * CreateSchoolFromGroupDialog — tạo trường THCS MỚI (mã nội bộ NB do máy sinh) từ
 * một nhóm tên gõ tay và ghép nhóm với trường ấy (BE: một giao dịch). Luật mã /
 * mã xã do BE quyết (`VnSchoolService.create_school`).
 */

"use client"

import { useMemo, useState } from "react"
import { toast } from "sonner"

import {
  CommunePicker,
  type CommunePickerValue,
} from "@/components/admin/CommunePicker"
import { Button } from "@/components/ui/button"
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
import { Switch } from "@/components/ui/switch"

import { useCreateSchoolFromThcsGroup } from "@/lib/hooks/useThcsSchoolMapping"
import { useSchoolProvinces } from "@/lib/hooks/useVnSchoolAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import {
  thcsCreateSchoolFromGroupSchema,
  type ThcsNameGroup,
} from "@/lib/zod/thcs-school-mapping"
import { VN_SCHOOL_LEVEL_LABELS } from "@/lib/zod/vn-school-admin"

const LEVELS = ["THCS", "THCS_THPT"] as const
type Level = (typeof LEVELS)[number]

interface Props {
  group: ThcsNameGroup | null
  onOpenChange: (open: boolean) => void
}

export function CreateSchoolFromGroupDialog({ group, onOpenChange }: Props) {
  const mutation = useCreateSchoolFromThcsGroup()
  const { data: provinces } = useSchoolProvinces()
  // Remount theo nhóm (key ở cha) ⇒ state khởi tạo từ cách viết phổ biến nhất.
  const [name, setName] = useState(group?.variants[0]?.text ?? "")
  const [level, setLevel] = useState<Level>("THCS")
  const [provinceCode, setProvinceCode] = useState("")
  const [province, setProvince] = useState("")
  const [commune, setCommune] = useState<CommunePickerValue | null>(null)
  const [isDtnt, setIsDtnt] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const uniqueProvinces = useMemo(() => {
    const seen = new Set<string>()
    return (provinces ?? []).filter((p) => {
      if (seen.has(p.moet_province_code)) return false
      seen.add(p.moet_province_code)
      return true
    })
  }, [provinces])

  const handleSubmit = async () => {
    if (!group) return
    setError(null)
    const parsed = thcsCreateSchoolFromGroupSchema.safeParse({
      normalized_name: group.normalized_name,
      school: {
        moet_province_code: provinceCode,
        commune_code: commune?.commune_code,
        name: name.trim(),
        province: province.trim(),
        ward: commune?.ward ?? undefined,
        level,
        is_dtnt: isDtnt,
      },
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Dữ liệu không hợp lệ")
      return
    }
    try {
      const res = await mutation.mutateAsync(parsed.data)
      toast.success(
        `Đã tạo trường ${res.school.moet_school_code} và ghép nhóm “${group.normalized_name}”. Nhớ xác nhận KV ở Danh mục trường.`,
      )
      onOpenChange(false)
    } catch (e) {
      setError(parseApiError(e, "Tạo trường thất bại"))
    }
  }

  return (
    <Dialog open={group != null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Tạo trường mới từ nhóm “{group?.normalized_name}”</DialogTitle>
          <DialogDescription>
            Trường mới mang mã nội bộ NB… do máy sinh. Tra xã và cờ DTNT từ học bạ.
            Sau khi tạo, xác nhận KV gợi ý theo xã ở trang Danh mục trường.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid gap-2">
            <Label htmlFor="g-name">Tên trường</Label>
            <Input id="g-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="g-level">Cấp</Label>
              <Select value={level} onValueChange={(v) => setLevel(v as Level)}>
                <SelectTrigger id="g-level">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEVELS.map((lv) => (
                    <SelectItem key={lv} value={lv}>
                      {VN_SCHOOL_LEVEL_LABELS[lv]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 pt-7">
              <Switch id="g-dtnt" checked={isDtnt} onCheckedChange={setIsDtnt} />
              <Label htmlFor="g-dtnt">Trường DTNT / bán trú</Label>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="g-prov-code">Tỉnh (mã MOET)</Label>
              <Select
                value={provinceCode}
                onValueChange={(v) => {
                  setProvinceCode(v)
                  const p = uniqueProvinces.find((x) => x.moet_province_code === v)
                  if (p && !province) setProvince(p.province)
                }}
              >
                <SelectTrigger id="g-prov-code">
                  <SelectValue placeholder="Chọn tỉnh" />
                </SelectTrigger>
                <SelectContent>
                  {uniqueProvinces.map((p) => (
                    <SelectItem key={p.moet_province_code} value={p.moet_province_code}>
                      {p.province} ({p.moet_province_code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="g-prov">Tên tỉnh</Label>
              <Input
                id="g-prov"
                value={province}
                onChange={(e) => setProvince(e.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="g-commune">Xã/phường nơi trường đặt (bắt buộc)</Label>
            <CommunePicker id="g-commune" value={commune} onChange={setCommune} />
            {commune?.area_code && (
              <p className="text-xs">
                KV gợi ý theo xã hiện tại:{" "}
                <span className="font-mono font-semibold">{commune.area_code}</span>
              </p>
            )}
          </div>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Hủy
          </Button>
          <Button onClick={handleSubmit} disabled={mutation.isPending}>
            Tạo trường và ghép
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
