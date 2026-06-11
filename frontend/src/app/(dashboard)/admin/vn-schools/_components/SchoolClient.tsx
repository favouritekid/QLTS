/**
 * SchoolClient — orchestrator trang Quản lý Trường THPT.
 *
 * Lọc tỉnh dùng **moet_province_code** (từ endpoint /provinces — administrative
 * getProvinces KHÔNG có mã MOET) + lọc cấp + search (tên/mã). Pagination +
 * Import CSV. KV assignment quản lý qua dialog trong SchoolTable.
 */

"use client"

import { useEffect, useMemo, useState } from "react"
import { Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

import { useSchoolProvinces, useSchools } from "@/lib/hooks/useVnSchoolAdmin"
import {
  VN_SCHOOL_LEVELS,
  VN_SCHOOL_LEVEL_LABELS,
} from "@/lib/zod/vn-school-admin"

import { ImportSchoolCsvDialog } from "./ImportSchoolCsvDialog"
import { SchoolTable } from "./SchoolTable"

const PAGE_SIZE = 50
const ALL = "__all__"

export function SchoolClient() {
  const [provinceCode, setProvinceCode] = useState<string>(ALL)
  const [level, setLevel] = useState<string>(ALL)
  const [qInput, setQInput] = useState("")
  const [q, setQ] = useState("")
  const [activeOnly, setActiveOnly] = useState(true)
  const [page, setPage] = useState(1)
  const [importOpen, setImportOpen] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      setQ(qInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(t)
  }, [qInput])

  const params = {
    moetProvinceCode: provinceCode === ALL ? null : provinceCode,
    level: level === ALL ? null : level,
    q: q || null,
    activeOnly,
    page,
    pageSize: PAGE_SIZE,
  }
  const { data, isLoading, isFetching } = useSchools(params)
  const { data: provinces } = useSchoolProvinces()

  // De-dupe theo mã tỉnh MOET — phòng data bẩn (1 mã map 2 tên province) gây
  // SelectItem trùng value + React key collision.
  const uniqueProvinces = useMemo(() => {
    const seen = new Set<string>()
    return (provinces ?? []).filter((p) => {
      if (seen.has(p.moet_province_code)) return false
      seen.add(p.moet_province_code)
      return true
    })
  }, [provinces])

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="container mx-auto space-y-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Trường THPT</h1>
          <p className="text-muted-foreground text-sm">
            Danh mục trường (vn_school) + phân loại KV theo năm. Ngừng trường =
            ẩn (không xoá), giữ lịch sử KV.
          </p>
        </div>
        <Button variant="outline" onClick={() => setImportOpen(true)}>
          <Upload className="mr-2 h-4 w-4" />
          Import CSV
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Bộ lọc</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="f-province">Tỉnh (MOET)</Label>
              <Select
                value={provinceCode}
                onValueChange={(v) => {
                  setProvinceCode(v)
                  setPage(1)
                }}
              >
                <SelectTrigger id="f-province" className="w-[240px]">
                  <SelectValue placeholder="Tất cả tỉnh" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Tất cả tỉnh</SelectItem>
                  {uniqueProvinces.map((p) => (
                    <SelectItem
                      key={p.moet_province_code}
                      value={p.moet_province_code}
                    >
                      {p.province} ({p.moet_province_code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="f-level">Cấp</Label>
              <Select
                value={level}
                onValueChange={(v) => {
                  setLevel(v)
                  setPage(1)
                }}
              >
                <SelectTrigger id="f-level" className="w-[180px]">
                  <SelectValue placeholder="Tất cả cấp" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Tất cả cấp</SelectItem>
                  {VN_SCHOOL_LEVELS.map((lv) => (
                    <SelectItem key={lv} value={lv}>
                      {VN_SCHOOL_LEVEL_LABELS[lv]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="f-q">Tìm (tên / mã trường)</Label>
              <Input
                id="f-q"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                placeholder="VD: Đắk Mil"
                className="w-[220px]"
              />
            </div>

            <div className="flex items-center gap-2 pb-2">
              <Switch
                id="f-active"
                checked={activeOnly}
                onCheckedChange={(v) => {
                  setActiveOnly(v)
                  setPage(1)
                }}
              />
              <Label htmlFor="f-active">Chỉ trường đang hoạt động</Label>
            </div>
          </div>
        </CardContent>
      </Card>

      <SchoolTable rows={data?.items ?? []} isLoading={isLoading} />

      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-sm">
          {total} trường{isFetching ? " · đang tải…" : ""}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Trước
          </Button>
          <span className="text-sm tabular-nums">
            Trang {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            Sau
          </Button>
        </div>
      </div>

      <ImportSchoolCsvDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  )
}
