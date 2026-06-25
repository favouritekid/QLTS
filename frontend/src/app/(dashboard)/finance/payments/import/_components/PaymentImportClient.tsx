"use client"

import { useState } from "react"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { PaymentImportPreview } from "@/lib/zod/payment-import"

import { PaymentImportHistory } from "./PaymentImportHistory"
import { PaymentImportPreviewResult } from "./PaymentImportPreviewResult"
import { PaymentImportUploadCard } from "./PaymentImportUploadCard"

export function PaymentImportClient() {
  const [tab, setTab] = useState("new")
  const [preview, setPreview] = useState<PaymentImportPreview | null>(null)

  return (
    <div className="container mx-auto space-y-6 py-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Import thu học phí hàng loạt
        </h1>
        <p className="text-sm text-muted-foreground">
          Kế toán thu offline → import file tổng hợp → hệ thống tự xác minh và
          ghi nhận thanh toán.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="new">Import mới</TabsTrigger>
          <TabsTrigger value="history">Lịch sử lô</TabsTrigger>
        </TabsList>

        <TabsContent value="new" className="space-y-6">
          <PaymentImportUploadCard onPreview={setPreview} />
          {preview ? (
            <PaymentImportPreviewResult
              preview={preview}
              onCommitted={() => {
                setPreview(null)
                setTab("history")
              }}
              onDiscard={() => setPreview(null)}
            />
          ) : null}
        </TabsContent>

        <TabsContent value="history">
          <PaymentImportHistory />
        </TabsContent>
      </Tabs>
    </div>
  )
}
