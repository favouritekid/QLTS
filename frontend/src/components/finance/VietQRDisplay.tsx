"use client"

import * as React from "react"
import { Copy, QrCode } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { AmountDisplay } from "./AmountDisplay"
import type { VietQRResponse } from "@/types/finance.types"
import { toast } from "sonner"

interface VietQRDisplayProps {
  data?: VietQRResponse
  isLoading?: boolean
  error?: unknown
  onRetry?: () => void
}

export function VietQRDisplay({ data, isLoading, error, onRetry }: VietQRDisplayProps) {
  const copy = React.useCallback(async (value: string, label: string) => {
    await navigator.clipboard.writeText(value)
    toast.success(`Đã sao chép ${label}`)
  }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <QrCode className="h-5 w-5" />
          Chuyển khoản VietQR
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <>
            <Skeleton className="mx-auto h-44 w-44 rounded-md" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </>
        ) : error ? (
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>Chưa thể hiển thị mã QR.</p>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry}>
                Thử lại
              </Button>
            )}
          </div>
        ) : data ? (
          <>
            <div className="flex justify-center">
              <img
                src={`data:image/png;base64,${data.qr_image_base64}`}
                alt="VietQR"
                className="h-44 w-44 rounded-md border bg-white p-2"
              />
            </div>
            <div className="space-y-2 text-sm">
              <InfoRow
                label="Số tiền"
                value={<AmountDisplay amount={data.amount} showCurrency size="sm" />}
              />
              <CopyRow
                label="Số tài khoản"
                value={data.bank_account.account_number}
                onCopy={() => copy(data.bank_account.account_number, "số tài khoản")}
              />
              <InfoRow label="Tên tài khoản" value={data.bank_account.account_name} />
              <CopyRow
                label="Nội dung"
                value={data.content}
                mono
                onCopy={() => copy(data.content, "nội dung")}
              />
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function CopyRow({
  label,
  value,
  mono,
  onCopy,
}: {
  label: string
  value: string
  mono?: boolean
  onCopy: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-start gap-1">
        <span className={mono ? "break-words text-right font-mono text-xs" : "break-words text-right font-medium"}>
          {value}
        </span>
        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={onCopy}>
          <Copy className="h-3.5 w-3.5" />
          <span className="sr-only">Sao chép {label}</span>
        </Button>
      </div>
    </div>
  )
}
