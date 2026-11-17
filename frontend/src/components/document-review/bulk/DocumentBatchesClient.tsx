"use client"

/**
 * Trang "Lô duyệt giấy" (GĐ1b §5.6, §5.8, §5.9): sống qua tải lại trang (mã lô gần nhất trong sessionStorage, đọc SAU
 * khi mount), sống qua đóng tab (danh sách lô của tôi), tra theo mã lô. Không gửi `execute` trừ khi người dùng bấm
 * "Chạy lô này" (cờ `can_execute` của máy chủ).
 */
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useBatchList, useLastBatchId, type BulkEndpoint } from "@/hooks/document-review/useBulkVerify"
import { isBatchId } from "@/lib/document-review/batch-session"
import type { BatchListScope } from "@/lib/zod/document-review"

import { BatchListPanel } from "./BatchListPanel"
import { BatchStatusPanel } from "./BatchStatusPanel"

interface Props {
  endpoint: BulkEndpoint
}

export function DocumentBatchesClient({ endpoint }: Props) {
  const inputId = useId()
  const last = useLastBatchId()
  // cùng khoá với danh sách "của tôi" bên dưới (React Query gộp một lượt gọi) — chỉ để đọc cờ `can_view_all`
  const mine = useBatchList(endpoint, "mine")
  const canViewAll = mine.data?.pages[0]?.can_view_all === true
  const [selected, setSelected] = useState<string | null>(null)
  const [typed, setTyped] = useState("")
  const [typedError, setTypedError] = useState<string | null>(null)
  const [scope, setScope] = useState<BatchListScope>("mine")

  const lookup = () => {
    const v = typed.trim().toLowerCase()
    if (!isBatchId(v)) {
      setTypedError("Mã lô có dạng 8-4-4-4-12 ký tự (vd lấy từ thông báo kết quả lô)")
      return
    }
    setTypedError(null)
    setSelected(v)
  }

  return (
    <div className="space-y-6">
      {last.batchId && last.batchId !== selected && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm" data-testid="lo-gan-nhat">
          <span>
            Lô gần nhất trong phiên làm việc này: <code className="text-xs">{last.batchId}</code>
          </span>
          <Button size="sm" onClick={() => setSelected(last.batchId)}>
            Tra kết quả
          </Button>
          <Button size="sm" variant="ghost" onClick={last.forget}>
            Bỏ qua
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor={inputId}>Tra lô theo mã</Label>
          <Input
            id={inputId}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="vd 3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"
            autoComplete="off"
            className="w-[22rem] max-w-full"
          />
        </div>
        <Button variant="outline" onClick={lookup}>
          Tra
        </Button>
      </div>
      {typedError && (
        <p role="alert" className="text-sm text-destructive">
          {typedError}
        </p>
      )}

      {selected && (
        <section className="space-y-2 rounded-md border p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Kết quả lô</h2>
            <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
              Đóng
            </Button>
          </div>
          <BatchStatusPanel key={selected} endpoint={endpoint} batchId={selected} />
        </section>
      )}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Danh sách lô</h2>
          {canViewAll && (
            <>
              <Button size="sm" variant={scope === "mine" ? "default" : "outline"} onClick={() => setScope("mine")}>
                Lô của tôi
              </Button>
              <Button size="sm" variant={scope === "all" ? "default" : "outline"} onClick={() => setScope("all")}>
                Tất cả lô (Admin)
              </Button>
            </>
          )}
        </div>
        <BatchListPanel
          key={canViewAll ? scope : "mine"}
          endpoint={endpoint}
          scope={canViewAll ? scope : "mine"}
          onSelect={setSelected}
        />
      </section>
    </div>
  )
}
