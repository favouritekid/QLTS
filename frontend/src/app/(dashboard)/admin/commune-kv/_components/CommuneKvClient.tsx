/**
 * CommuneKvClient — orchestrator trang Quản lý KV theo Xã.
 *
 * Sở hữu bộ lọc (tỉnh + search + active toggle) + pagination + nút Import CSV,
 * chạy `useCommunes` rồi truyền rows xuống `CommuneKvTable`. Mutations (trong
 * Table + Import dialog) invalidate `commune-kv` tree → query refetch.
 *
 * Lọc tỉnh dùng TÊN tỉnh (vn_commune_area_map.province là text) — KHÔNG mã.
 */

"use client"

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
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

import { administrativeApi } from "@/lib/api/administrative"
import { useCommunes } from "@/lib/hooks/useCommuneKvAdmin"

import { CommuneKvTable } from "./CommuneKvTable"
import { ImportCommuneCsvDialog } from "./ImportCommuneCsvDialog"

const PAGE_SIZE = 50
const ALL_PROVINCES = "__all__"

export function CommuneKvClient() {
  const [provinceName, setProvinceName] = useState<string>(ALL_PROVINCES)
  const [qInput, setQInput] = useState("")
  const [q, setQ] = useState("")
  const [activeOnly, setActiveOnly] = useState(true)
  const [page, setPage] = useState(1)
  const [importOpen, setImportOpen] = useState(false)

  // Debounce search → tránh refetch mỗi keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(qInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(t)
  }, [qInput])

  const params = {
    province: provinceName === ALL_PROVINCES ? null : provinceName,
    q: q || null,
    activeOnly,
    page,
    pageSize: PAGE_SIZE,
  }
  const { data, isLoading, isFetching } = useCommunes(params)

  const { data: provinces } = useQuery({
    queryKey: ["administrative", "provinces", "current"],
    queryFn: () => administrativeApi.getProvinces("current"),
    staleTime: 60 * 60 * 1000,
  })

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="container mx-auto space-y-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">KV theo Xã</h1>
          <p className="text-muted-foreground text-sm">
            Danh mục khu vực ưu tiên theo xã/phường (vn_commune_area_map). Đổi
            KV của một xã sẽ tạo bản ghi mới theo thời gian, giữ lịch sử cũ.
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
              <Label htmlFor="filter-province">Tỉnh</Label>
              <Select
                value={provinceName}
                onValueChange={(v) => {
                  setProvinceName(v)
                  setPage(1)
                }}
              >
                <SelectTrigger id="filter-province" className="w-[260px]">
                  <SelectValue placeholder="Tất cả tỉnh" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_PROVINCES}>Tất cả tỉnh</SelectItem>
                  {(provinces ?? []).map((p) => (
                    <SelectItem key={p.code} value={p.name}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="filter-q">Tìm (xã / mã xã)</Label>
              <Input
                id="filter-q"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                placeholder="VD: Đắk Mil / 24717"
                className="w-[240px]"
              />
            </div>

            <div className="flex items-center gap-2 pb-2">
              <Switch
                id="filter-active"
                checked={activeOnly}
                onCheckedChange={(v) => {
                  setActiveOnly(v)
                  setPage(1)
                }}
              />
              <Label htmlFor="filter-active">Chỉ dòng đang áp dụng</Label>
            </div>
          </div>
        </CardContent>
      </Card>

      <CommuneKvTable rows={data?.items ?? []} isLoading={isLoading} />

      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-sm">
          {total} dòng{isFetching ? " · đang tải…" : ""}
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

      <ImportCommuneCsvDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  )
}
