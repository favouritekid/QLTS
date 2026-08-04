"use client"

import * as React from "react"
import { AlertTriangle, Download, Filter, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { AmountDisplay } from "@/components/finance"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useDebtReport, useDebtReportExport } from "@/hooks/finance/useDebtReport"
import type { DebtAgingBucket, DebtReportFilters, FeeType } from "@/types/finance.types"

const AGING_LABELS: Record<DebtAgingBucket, string> = {
  "0_30": "0-30",
  "31_60": "31-60",
  over_60: ">60",
}

export function DebtReportClient() {
  const [academicYear, setAcademicYear] = React.useState("")
  const [roundId, setRoundId] = React.useState("")
  const [feeType, setFeeType] = React.useState<FeeType | "all">("all")
  const [aging, setAging] = React.useState<DebtAgingBucket | "all">("all")

  const filters = React.useMemo<DebtReportFilters>(() => ({
    academic_year: academicYear ? Number(academicYear) : undefined,
    round_id: roundId ? Number(roundId) : undefined,
    fee_type: feeType === "all" ? undefined : feeType,
    aging: aging === "all" ? undefined : aging,
  }), [academicYear, aging, feeType, roundId])

  const { data, isLoading, error, refetch } = useDebtReport(filters)

  // Xuất từ MÁY CHỦ (không dựng CSV ở trình duyệt nữa): server đặt tiêu đề
  // tiếng Việt, thêm BOM cho Excel, ghi ô tiền kiểu số và gắn mốc thời gian
  // vào tên tệp.
  const exportMutation = useDebtReportExport()
  const handleExport = (format: "xlsx" | "csv") => {
    exportMutation.mutate({ format, filters })
  }

  if (error) {
    return (
      <div className="p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-destructive" />
            <p className="font-medium text-destructive">Không thể tải báo cáo công nợ</p>
            <Button variant="outline" className="mt-4" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Thử lại
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Báo cáo công nợ</h1>
          <p className="text-muted-foreground">Tổng hợp theo hồ sơ tuyển sinh</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Làm mới
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                disabled={exportMutation.isPending || !data?.items?.length}
              >
                <Download className="mr-2 h-4 w-4" />
                {exportMutation.isPending ? "Đang xuất…" : "Xuất"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => handleExport("xlsx")}>
                Excel (.xlsx)
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleExport("csv")}>
                CSV (.csv)
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/*
          Hai ô giữa ghi rõ "(đợt còn nợ)": truy vấn CHỈ lấy hoá đơn còn dư nợ,
          nên tiền của các đợt ĐÃ TRẢ XONG không nằm trong đây. Nhãn cũ ("Dự
          thu" / "Đã thu") khiến người đọc tưởng là tổng của cả hồ sơ — hồ sơ
          trả xong đợt 1 và còn nợ đợt 2 sẽ thấy "Đã thu" thiếu hẳn tiền đợt 1.
        */}
        <SummaryCard title="Hồ sơ nợ" value={data?.summary.debtor_count ?? 0} />
        <SummaryCard title="Phải thu (đợt còn nợ)" amount={data?.summary.total_expected ?? "0"} />
        <SummaryCard title="Đã thu (đợt còn nợ)" amount={data?.summary.total_paid ?? "0"} />
        <SummaryCard title="Còn nợ" amount={data?.summary.total_outstanding ?? "0"} emphasis />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Filter className="h-5 w-5" />
            Bộ lọc
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            inputMode="numeric"
            placeholder="Năm học"
            value={academicYear}
            onChange={(event) => setAcademicYear(event.target.value.replace(/\D/g, ""))}
          />
          <Input
            inputMode="numeric"
            placeholder="Đợt tuyển sinh"
            value={roundId}
            onChange={(event) => setRoundId(event.target.value.replace(/\D/g, ""))}
          />
          <Select value={feeType} onValueChange={(value) => setFeeType(value as FeeType | "all")}>
            <SelectTrigger>
              <SelectValue placeholder="Loại phí" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả phí</SelectItem>
              <SelectItem value="application">Xét tuyển</SelectItem>
              <SelectItem value="tuition">Học phí</SelectItem>
              <SelectItem value="enrollment">Nhập học</SelectItem>
              <SelectItem value="insurance">Bảo hiểm</SelectItem>
              <SelectItem value="dormitory">Ký túc xá</SelectItem>
              <SelectItem value="other">Khác</SelectItem>
            </SelectContent>
          </Select>
          <Select value={aging} onValueChange={(value) => setAging(value as DebtAgingBucket | "all")}>
            <SelectTrigger>
              <SelectValue placeholder="Tuổi nợ" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả tuổi nợ</SelectItem>
              <SelectItem value="0_30">0-30 ngày</SelectItem>
              <SelectItem value="31_60">31-60 ngày</SelectItem>
              <SelectItem value="over_60">Trên 60 ngày</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Hồ sơ</TableHead>
                <TableHead>Đơn vị</TableHead>
                <TableHead>Loại phí</TableHead>
                <TableHead className="text-right">Còn lại</TableHead>
                <TableHead className="text-right">Ngày quá hạn</TableHead>
                <TableHead>Nhóm tuổi nợ</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Đang tải...
                  </TableCell>
                </TableRow>
              ) : data?.items.length ? (
                data.items.map((item) => (
                  <TableRow key={item.admission_profile_id}>
                    <TableCell>
                      <div className="font-medium">{item.profile_name}</div>
                      <div className="font-mono text-xs text-muted-foreground">{item.profile_code}</div>
                    </TableCell>
                    <TableCell>{item.unit_name ?? "-"}</TableCell>
                    <TableCell>{item.fee_types.join(", ")}</TableCell>
                    <TableCell className="text-right">
                      <AmountDisplay amount={item.total_outstanding} showCurrency={false} size="sm" />
                    </TableCell>
                    <TableCell className="text-right">{item.days_overdue}</TableCell>
                    <TableCell>
                      <Badge variant={item.aging_bucket === "over_60" ? "destructive" : "outline"}>
                        {AGING_LABELS[item.aging_bucket]}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Không có dữ liệu
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function SummaryCard({
  title,
  value,
  amount,
  emphasis,
}: {
  title: string
  value?: number
  amount?: string
  emphasis?: boolean
}) {
  return (
    <Card className={emphasis ? "border-warning-500/50" : undefined}>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{title}</p>
        <div className="mt-2 text-xl font-semibold">
          {amount !== undefined ? (
            <AmountDisplay amount={amount} showCurrency={false} size="lg" />
          ) : (
            value
          )}
        </div>
      </CardContent>
    </Card>
  )
}
