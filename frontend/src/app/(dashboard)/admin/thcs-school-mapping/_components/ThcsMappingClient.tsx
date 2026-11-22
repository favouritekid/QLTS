/**
 * ThcsMappingClient — màn hình "Ghép trường THCS" (owner 22-11, đề xuất Phần B).
 *
 * Thin client: nhóm, số đếm, cờ "áp thật được không" đều do BE trả. FE chỉ hiển
 * thị + gửi đúng khoá nhóm BE đưa (không tự chuẩn hoá tên).
 */

"use client"

import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { useThcsGroups } from "@/lib/hooks/useThcsSchoolMapping"
import type { ThcsNameGroup } from "@/lib/zod/thcs-school-mapping"

import { ApplyMappingPanel } from "./ApplyMappingPanel"
import { CreateSchoolFromGroupDialog } from "./CreateSchoolFromGroupDialog"
import { MapGroupDialog } from "./MapGroupDialog"
import { UnmapGroupDialog } from "./UnmapGroupDialog"

const PAGE_SIZE = 50
type Filter = "all" | "unmapped" | "mapped"

const FILTER_LABELS: Record<Filter, string> = {
  all: "Tất cả nhóm",
  unmapped: "Chưa ghép",
  mapped: "Đã ghép",
}

export function ThcsMappingClient() {
  const [filter, setFilter] = useState<Filter>("unmapped")
  const [page, setPage] = useState(1)
  const [mapGroup, setMapGroup] = useState<ThcsNameGroup | null>(null)
  const [createGroup, setCreateGroup] = useState<ThcsNameGroup | null>(null)
  const [unmapGroup, setUnmapGroup] = useState<ThcsNameGroup | null>(null)

  const { data, isLoading, isFetching } = useThcsGroups({
    page,
    pageSize: PAGE_SIZE,
    mapped: filter === "all" ? undefined : filter === "mapped",
  })
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const s = data?.summary

  return (
    <div className="container mx-auto space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Ghép trường THCS</h1>
        <p className="text-muted-foreground text-sm">
          Tên trường THCS gõ tay trong lịch sử học (chưa chọn từ danh mục), gom
          theo tên đã chuẩn hoá. Ghép mỗi nhóm với một trường THCS trong danh mục,
          hoặc tạo trường mới (mã nội bộ NB). Ghép chưa sửa hồ sơ nào — hồ sơ chỉ
          đổi khi áp ghép.
        </p>
      </div>

      {s && (
        <p className="text-sm" data-testid="thcs-mapping-summary">
          {s.group_count} nhóm tên · {s.mapped_group_count} nhóm đã ghép ·{" "}
          {s.row_count} dòng THCS gõ tay · {s.profile_count} hồ sơ
          {s.blank_name_row_count > 0 &&
            ` · ${s.blank_name_row_count} dòng trống tên (sửa tay từng hồ sơ)`}
        </p>
      )}

      <ApplyMappingPanel />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base">Nhóm tên trường</CardTitle>
          <Select
            value={filter}
            onValueChange={(v) => {
              setFilter(v as Filter)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-[180px]" aria-label="Lọc nhóm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(FILTER_LABELS) as Filter[]).map((f) => (
                <SelectItem key={f} value={f}>
                  {FILTER_LABELS[f]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tên (đã chuẩn hoá) · cách viết gốc</TableHead>
                  <TableHead className="w-[110px] text-right">Hồ sơ</TableHead>
                  <TableHead className="w-[90px] text-right">Dòng y→y</TableHead>
                  <TableHead>Trường đã ghép</TableHead>
                  <TableHead className="w-[220px] text-right">Thao tác</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  [1, 2, 3, 4].map((i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={5}>
                        <Skeleton className="h-6 w-full" />
                      </TableCell>
                    </TableRow>
                  ))
                ) : !data || data.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-muted-foreground py-8 text-center text-sm"
                    >
                      Không có nhóm nào.
                    </TableCell>
                  </TableRow>
                ) : (
                  data.items.map((g) => (
                    <TableRow key={g.normalized_name}>
                      <TableCell>
                        <div className="font-medium">{g.normalized_name}</div>
                        <ul className="text-muted-foreground text-xs">
                          {g.variants.map((v) => (
                            <li key={v.text}>
                              “{v.text}” × {v.row_count}
                            </li>
                          ))}
                        </ul>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {g.profile_count}
                        <div className="text-muted-foreground text-xs">
                          trong phạm vi áp: {g.eligible_profile_count}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {g.same_year_row_count}
                      </TableCell>
                      <TableCell>
                        {g.mapping ? (
                          <div>
                            {g.mapping.school_name}
                            <span className="text-muted-foreground ml-1 font-mono text-xs">
                              {g.mapping.moet_school_code}
                            </span>
                            {!g.mapping.usable && (
                              <Badge variant="destructive" className="ml-2">
                                Không dùng được
                              </Badge>
                            )}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">Chưa ghép</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {g.mapping ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setUnmapGroup(g)}
                          >
                            Huỷ ghép
                          </Button>
                        ) : (
                          <div className="flex justify-end gap-1">
                            <Button size="sm" onClick={() => setMapGroup(g)}>
                              Ghép trường
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => setCreateGroup(g)}
                            >
                              Tạo trường mới
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          <div className="mt-3 flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              {total} nhóm{isFetching ? " · đang tải…" : ""}
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
        </CardContent>
      </Card>

      <MapGroupDialog
        key={`map-${mapGroup?.normalized_name ?? "none"}`}
        group={mapGroup}
        onOpenChange={(o) => !o && setMapGroup(null)}
      />
      <CreateSchoolFromGroupDialog
        key={`create-${createGroup?.normalized_name ?? "none"}`}
        group={createGroup}
        onOpenChange={(o) => !o && setCreateGroup(null)}
      />
      <UnmapGroupDialog
        group={unmapGroup}
        onOpenChange={(o) => !o && setUnmapGroup(null)}
      />
    </div>
  )
}
