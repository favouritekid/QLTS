"use client"

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
import {
  useCouncilDownloadLog,
  useCouncilSetDeletions,
} from "@/hooks/admin/useCouncilDocuments"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { formatSize, userLabel, shortSha, formatTime } from "./display"

const PAGE_SIZE = 100

function Pagination({
  offset,
  setOffset,
  day,
  loading,
  ten,
}: {
  offset: number
  setOffset: (f: (o: number) => number) => void
  day: boolean
  loading: boolean
  ten: string
}) {
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={offset === 0 || loading}
        onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
        data-testid={`${ten}-prev`}
      >
        Trang trước
      </Button>
      <span className="text-sm text-muted-foreground">Trang {Math.floor(offset / PAGE_SIZE) + 1}</span>
      <Button
        variant="outline"
        size="sm"
        disabled={!day || loading}
        onClick={() => setOffset((o) => o + PAGE_SIZE)}
        data-testid={`${ten}-next`}
      >
        Trang sau
      </Button>
    </div>
  )
}

/**
 * Nhật ký tải (CHỈ admin, cờ `xem_nhat_ky_tai`). Một dòng = máy chủ đã CẤP tệp
 * (không chứng minh người dùng đã nhận xong). `setId` ⇒ chỉ bộ ấy (bộ đã xoá vẫn lọc được).
 */
export function CouncilDownloadLogPanel({ setId }: { setId?: number }) {
  const [offset, setOffset] = useState(0)
  const q = useCouncilDownloadLog(
    setId === undefined ? { limit: PAGE_SIZE, offset } : { limit: PAGE_SIZE, offset, set_id: setId },
    true,
  )
  if (q.isPending) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải nhật ký tải tệp…
      </div>
    )
  }
  if (q.isError) return <CouncilErrorAlert error={q.error} testId="download-log-error" />
  return (
    <div className="space-y-3">
      {q.data.length === 0 ? (
        <p className="text-muted-foreground" data-testid="download-log-empty">
          Chưa có lượt tải nào.
        </p>
      ) : (
        <Table data-testid="download-log">
          <TableHeader>
            <TableRow>
              <TableHead>Lúc</TableHead>
              <TableHead>Người tải</TableHead>
              <TableHead>Bộ</TableHead>
              <TableHead>Tệp</TableHead>
              <TableHead>sha256</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data.map((d) => (
              <TableRow key={d.id} data-testid={`download-log-row-${d.id}`}>
                <TableCell>{formatTime(d.tai_luc)}</TableCell>
                <TableCell>{userLabel(d.nguoi_tai_ten, d.nguoi_tai_id)}</TableCell>
                <TableCell>#{d.set_id}</TableCell>
                <TableCell className="break-all">
                  {d.thu_tu}. {d.path}
                </TableCell>
                <TableCell className="font-mono text-xs" title={d.sha256}>
                  {shortSha(d.sha256)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination
        offset={offset}
        setOffset={setOffset}
        day={q.data.length === PAGE_SIZE}
        loading={q.isFetching}
        ten="download-log"
      />
    </div>
  )
}

/** Vết xoá bộ (CHỈ admin, cờ `xem_nhat_ky_xoa`) — không có danh sách CCCD. */
export function CouncilDeletionLogPanel() {
  const [offset, setOffset] = useState(0)
  const q = useCouncilSetDeletions({ limit: PAGE_SIZE, offset }, true)
  if (q.isPending) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải nhật ký xoá…
      </div>
    )
  }
  if (q.isError) return <CouncilErrorAlert error={q.error} testId="deletion-log-error" />
  return (
    <div className="space-y-3">
      {q.data.length === 0 ? (
        <p className="text-muted-foreground" data-testid="deletion-log-empty">
          Chưa có bộ nào bị xoá.
        </p>
      ) : (
        <Table data-testid="deletion-log">
          <TableHeader>
            <TableRow>
              <TableHead>Lúc xoá</TableHead>
              <TableHead>Người xoá</TableHead>
              <TableHead>Bộ</TableHead>
              <TableHead className="text-right">Số hồ sơ</TableHead>
              <TableHead>Tệp (thứ tự · đường dẫn · sha256 · kích thước)</TableHead>
              <TableHead>Lý do</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data.map((v) => (
              <TableRow key={v.id} data-testid={`deletion-row-${v.id}`}>
                <TableCell>{formatTime(v.xoa_luc)}</TableCell>
                <TableCell>{userLabel(v.nguoi_xoa_ten, v.nguoi_xoa_id)}</TableCell>
                <TableCell>#{v.set_id}</TableCell>
                <TableCell className="text-right">{v.so_ho_so}</TableCell>
                <TableCell>
                  <ul className="space-y-0.5 text-xs">
                    {v.danh_sach_tep.map((t, i) => (
                      <li key={i} className="break-all">
                        {String(t.thu_tu ?? "")}. {String(t.path ?? "")} ·{" "}
                        <span className="font-mono" title={String(t.sha256 ?? "")}>
                          {shortSha(String(t.sha256 ?? ""))}
                        </span>
                        {typeof t.kich_thuoc === "number" ? ` · ${formatSize(t.kich_thuoc)}` : ""}
                      </li>
                    ))}
                  </ul>
                </TableCell>
                <TableCell className="max-w-xs whitespace-pre-line">{v.ly_do}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination
        offset={offset}
        setOffset={setOffset}
        day={q.data.length === PAGE_SIZE}
        loading={q.isFetching}
        ten="deletion-log"
      />
    </div>
  )
}
