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
import { useDebtReport } from "@/hooks/finance/useDebtReport"
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

  const exportCsv = () => {
    if (!data?.items?.length) return
    const header = [
      "profile_code",
      "profile_name",
      "unit_name",
      "academic_year",
      "admission_round_id",
      "fee_types",
      "invoice_count",
      "total_expected",
      "total_paid",
      "total_outstanding",
      "days_overdue",
      "aging_bucket",
    ]
    const rows = data.items.map((item) => [
      item.profile_code,
      item.profile_name,
      item.unit_name ?? "",
      item.academic_year,
      item.admission_round_id ?? "",
      item.fee_types.join("|"),
      item.invoice_count,
      item.total_expected,
      item.total_paid,
      item.total_outstanding,
      item.days_overdue,
      item.aging_bucket,
    ])
    const csv = [header, ...rows]
      .map((row) => row.map((cell) => `"${String(cell).replaceAll("\"", "\"\"")}"`).join(","))
      .join("\n")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "debt-report.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  if (error) {
    return (
      <div className="p-4 sm:p-6">
        <Card className="border-destructive">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-destructive" />
            <p className="font-medium text-destructive">Khong the tai bao cao cong no</p>
            <Button variant="outline" className="mt-4" onClick={() => refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Thu lai
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
          <h1 className="text-2xl font-bold tracking-tight">Bao cao cong no</h1>
          <p className="text-muted-foreground">Tong hop theo ho so tuyen sinh</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Lam moi
          </Button>
          <Button variant="outline" onClick={exportCsv} disabled={!data?.items?.length}>
            <Download className="mr-2 h-4 w-4" />
            CSV
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <SummaryCard title="Ho so no" value={data?.summary.debtor_count ?? 0} />
        <SummaryCard title="Du thu" amount={data?.summary.total_expected ?? "0"} />
        <SummaryCard title="Da thu" amount={data?.summary.total_paid ?? "0"} />
        <SummaryCard title="Con lai" amount={data?.summary.total_outstanding ?? "0"} emphasis />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Filter className="h-5 w-5" />
            Bo loc
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            inputMode="numeric"
            placeholder="Nam hoc"
            value={academicYear}
            onChange={(event) => setAcademicYear(event.target.value.replace(/\D/g, ""))}
          />
          <Input
            inputMode="numeric"
            placeholder="Dot tuyen sinh"
            value={roundId}
            onChange={(event) => setRoundId(event.target.value.replace(/\D/g, ""))}
          />
          <Select value={feeType} onValueChange={(value) => setFeeType(value as FeeType | "all")}>
            <SelectTrigger>
              <SelectValue placeholder="Loai phi" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tat ca phi</SelectItem>
              <SelectItem value="application">Xet tuyen</SelectItem>
              <SelectItem value="tuition">Hoc phi</SelectItem>
              <SelectItem value="enrollment">Nhap hoc</SelectItem>
              <SelectItem value="insurance">Bao hiem</SelectItem>
              <SelectItem value="dormitory">Ky tuc xa</SelectItem>
              <SelectItem value="other">Khac</SelectItem>
            </SelectContent>
          </Select>
          <Select value={aging} onValueChange={(value) => setAging(value as DebtAgingBucket | "all")}>
            <SelectTrigger>
              <SelectValue placeholder="Tuoi no" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tat ca tuoi no</SelectItem>
              <SelectItem value="0_30">0-30 ngay</SelectItem>
              <SelectItem value="31_60">31-60 ngay</SelectItem>
              <SelectItem value="over_60">Tren 60 ngay</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ho so</TableHead>
                <TableHead>Don vi</TableHead>
                <TableHead>Loai phi</TableHead>
                <TableHead className="text-right">Con lai</TableHead>
                <TableHead className="text-right">Ngay qua han</TableHead>
                <TableHead>Bucket</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                    Dang tai...
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
                    Khong co du lieu
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
