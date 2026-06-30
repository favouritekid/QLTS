// src/components/sms/admin/SmsSummaryCard.tsx
"use client"

import { Card, CardContent } from "@/components/ui/card"

/** Thẻ số liệu tổng hợp dùng chung cho các panel báo cáo SMS. */
export function SmsSummaryCard({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-muted-foreground text-xs">{label}</p>
        <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  )
}
