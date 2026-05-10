/**
 * AggregateDrawer — drill-down 1 cell aggregate (ngành × đợt) trong Ma trận toàn cảnh.
 *
 * Phase 2 v8.2 PR-2D.1 v3.
 * Cell aggregate = N paths (1 path / method). Drawer = list paths + each path
 * → click open PathDetailDrawer (nested) cho edit deep.
 */
"use client"

import { ChevronRight, Loader2 } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { usePathMatrixByMajor } from "@/hooks/admissions/useQuotaMatrix"

import { PathDetailDrawer } from "./PathDetailDrawer"
import { pathStatusLabel } from "./labels"

interface Props {
  academicInfoId: number
  roundId: number
  programName: string
  roundCode: string
  onClose: () => void
}

export function AggregateDrawer({
  academicInfoId,
  roundId,
  programName,
  roundCode,
  onClose,
}: Props) {
  const { data, isLoading } = usePathMatrixByMajor(academicInfoId)
  const [openPathId, setOpenPathId] = useState<number | null>(null)

  // Filter cells thuộc round này
  const rowsInRound = data?.methods
    .map((m) => ({
      method: m,
      cell: m.cells_by_round_id[roundId],
    }))
    .filter((x) => x.cell !== null && x.cell !== undefined)

  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent className="sm:max-w-2xl w-full flex flex-col overflow-hidden">
        <SheetHeader className="pr-8">
          <SheetTitle className="text-pretty">{programName}</SheetTitle>
          <SheetDescription className="sr-only">
            Tổng hợp đường tuyển sinh theo phương thức cho ngành &amp; đợt đã chọn.
          </SheetDescription>
          <div className="text-xs text-muted-foreground">
            Đợt <span translate="no">{roundCode}</span>
            <span aria-hidden="true"> · </span>
            {rowsInRound?.length ?? 0} phương thức
          </div>
        </SheetHeader>

        <div className="flex-1 min-h-0 overflow-y-auto py-4">
          {isLoading && (
            <div className="flex items-center justify-center py-8" aria-live="polite">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
              <span className="sr-only">Đang tải tổng hợp đường tuyển sinh…</span>
            </div>
          )}

          {data && rowsInRound && rowsInRound.length === 0 && (
            <div className="text-sm text-muted-foreground py-4">
              Chưa có đường tuyển sinh nào cho ngành &amp; đợt này.
            </div>
          )}

          {data && rowsInRound && rowsInRound.length > 0 && (
            <>
              <div className="rounded-md border bg-muted/40 p-3 text-xs space-y-1 mb-4">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Cap năm:</span>
                  <span className="font-medium tabular-nums">
                    {data.annual_admission_quota ?? "∞"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Đã rải toàn ngành:</span>
                  <span className="font-medium tabular-nums">{data.sum_admit_allocated}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Còn lại:</span>
                  <span
                    className={
                      data.sum_remaining !== null && data.sum_remaining < 0
                        ? "font-semibold text-destructive tabular-nums"
                        : "font-medium text-emerald-600 tabular-nums"
                    }
                  >
                    {data.sum_remaining ?? "∞"}
                  </span>
                </div>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Phương thức</TableHead>
                    <TableHead className="text-right">Trần submit</TableHead>
                    <TableHead className="text-right">Trần admit</TableHead>
                    <TableHead className="text-right">Đã nộp</TableHead>
                    <TableHead className="text-center">Trạng thái</TableHead>
                    <TableHead>
                      <span className="sr-only">Mở chi tiết</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rowsInRound.map(({ method, cell }) => (
                    <TableRow key={method.admission_method_id}>
                      <TableCell>
                        <div className="font-medium">{method.method_name}</div>
                        <div className="text-xs text-muted-foreground" translate="no">
                          {method.method_code}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {cell!.round_quota ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {cell!.admit_quota ?? "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {cell!.submission_count}
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant={cell!.status === "active" ? "default" : "outline"}
                          className="text-xs"
                        >
                          {pathStatusLabel(cell!.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right p-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setOpenPathId(cell!.path_id)}
                          aria-label={`Mở chi tiết đường ${method.method_name}`}
                        >
                          <ChevronRight className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <p className="text-[11px] text-muted-foreground mt-3">
                Click → mở chi tiết path để chỉnh quota.
              </p>
            </>
          )}
        </div>

        <div className="flex justify-end border-t pt-3">
          <Button variant="outline" onClick={onClose}>
            Đóng
          </Button>
        </div>
      </SheetContent>

      {openPathId !== null && (
        <PathDetailDrawer
          pathId={openPathId}
          onClose={() => setOpenPathId(null)}
        />
      )}
    </Sheet>
  )
}
