"use client"

import Link from "next/link"
import { useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useCouncilSets } from "@/hooks/admin/useCouncilDocuments"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { kichThuoc, nguoi, thoiDiem } from "./hien-thi"

const CO_TRANG = 50

/**
 * Danh sách bộ văn bản — máy chủ LỌC theo phạm vi (admin: mọi bộ; quản lý: bộ
 * của đơn vị mình). Phân trang offset; "Trang sau" mở khi trang đang xem đầy.
 */
export function CouncilSetList({ canOpenDetail }: { canOpenDetail: boolean }) {
  const [offset, setOffset] = useState(0)
  const q = useCouncilSets({ limit: CO_TRANG, offset }, true)

  if (q.isPending) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground" data-testid="set-list-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách bộ văn bản…
      </div>
    )
  }
  if (q.isError) return <CouncilErrorAlert error={q.error} testId="set-list-error" />

  const ds = q.data
  return (
    <div className="space-y-3">
      {ds.length === 0 ? (
        <p className="text-muted-foreground" data-testid="set-list-empty">
          {offset === 0 ? "Chưa có bộ văn bản nào trong phạm vi của bạn." : "Hết danh sách."}
        </p>
      ) : (
        <Table data-testid="set-list">
          <TableHeader>
            <TableRow>
              <TableHead>Bộ</TableHead>
              <TableHead>Tạo lúc</TableHead>
              <TableHead>Năm học</TableHead>
              <TableHead>Trình độ</TableHead>
              <TableHead className="text-right">Số hồ sơ</TableHead>
              <TableHead className="text-right">Số tệp</TableHead>
              <TableHead className="text-right">Dung lượng</TableHead>
              <TableHead>Đơn vị</TableHead>
              <TableHead>Người tạo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ds.map((b) => (
              <TableRow key={b.id} data-testid={`set-row-${b.id}`}>
                <TableCell>
                  {canOpenDetail ? (
                    <Link
                      href={`/admin/council-documents/${b.id}`}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      #{b.id}
                    </Link>
                  ) : (
                    <span>#{b.id}</span>
                  )}
                </TableCell>
                <TableCell>{thoiDiem(b.tao_luc)}</TableCell>
                <TableCell>{b.nam_hoc ?? "—"}</TableCell>
                <TableCell>{b.trinh_do}</TableCell>
                <TableCell className="text-right">{b.so_ho_so}</TableCell>
                <TableCell className="text-right">{b.so_tep}</TableCell>
                <TableCell className="text-right">{kichThuoc(b.kich_thuoc_tong)}</TableCell>
                <TableCell>{b.unit_id === null ? "Nhiều / chưa gán" : `#${b.unit_id}`}</TableCell>
                <TableCell>{nguoi(b.nguoi_tao_id)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0 || q.isFetching}
          onClick={() => setOffset((o) => Math.max(0, o - CO_TRANG))}
          data-testid="set-list-prev"
        >
          Trang trước
        </Button>
        <span className="text-sm text-muted-foreground">
          Trang {Math.floor(offset / CO_TRANG) + 1}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={ds.length < CO_TRANG || q.isFetching}
          onClick={() => setOffset((o) => o + CO_TRANG)}
          data-testid="set-list-next"
        >
          Trang sau
        </Button>
      </div>
    </div>
  )
}
