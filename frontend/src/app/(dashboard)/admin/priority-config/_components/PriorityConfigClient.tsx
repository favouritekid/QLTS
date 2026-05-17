/**
 * PriorityConfigClient — orchestrator for /admin/priority-config.
 *
 * Layout:
 *   ┌────────────────────────────────────────────────────────┐
 *   │ Header: title + year selector + clone + seed-defaults  │
 *   ├────────────────────────────────────────────────────────┤
 *   │ AreaTable                  │ ObjectTable               │
 *   │ (KV)                       │ (UT)                      │
 *   └────────────────────────────────────────────────────────┘
 *
 * Year selector is client-side state — list 5 years centred on
 * current year (2024..2028 in 2026). Selecting a year reloads both
 * tables via React Query.
 */

"use client"

import { useState } from "react"

import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { AreaTable } from "./AreaTable"
import { CloneFromYearDialog } from "./CloneFromYearDialog"
import { ObjectTable } from "./ObjectTable"
import { SeedDefaultsButton } from "./SeedDefaultsButton"

// Range: 2 years back, current, 3 years forward. Keep the window
// small — admin rarely needs to edit rates more than a year out.
function buildYearOptions(): number[] {
  const current = new Date().getFullYear()
  const start = current - 2
  return Array.from({ length: 6 }, (_, i) => start + i)
}

export function PriorityConfigClient() {
  const yearOptions = buildYearOptions()
  const [academicYear, setAcademicYear] = useState<number>(
    new Date().getFullYear(),
  )

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Cấu hình Ưu tiên</h1>
          <p className="text-muted-foreground text-sm">
            Quản lý điểm cộng Khu vực (KV) + Đối tượng (UT) theo TT
            05/2021-BLĐTBXH. Hồ sơ đã snapshot không bị ảnh hưởng khi bạn sửa
            tỉ lệ — chỉ áp dụng cho hồ sơ mới.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label
              htmlFor="year-select"
              className="text-muted-foreground text-xs"
            >
              Năm học
            </label>
            <Select
              value={String(academicYear)}
              onValueChange={(v) => setAcademicYear(Number(v))}
            >
              <SelectTrigger
                id="year-select"
                className="w-[120px]"
                data-testid="year-select"
              >
                <SelectValue placeholder="Năm" />
              </SelectTrigger>
              <SelectContent>
                {yearOptions.map((y) => (
                  <SelectItem key={y} value={String(y)}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <SeedDefaultsButton academicYear={academicYear} />
          <CloneFromYearDialog defaultToYear={academicYear} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardContent className="pt-6">
            <AreaTable academicYear={academicYear} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <ObjectTable academicYear={academicYear} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
