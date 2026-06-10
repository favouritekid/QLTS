/**
 * ImportCommuneCsvDialog — upload CSV BNV → endpoint sẵn có
 * POST /api/v2/admin/vn-locality/communes/import (idempotent).
 *
 * Cột CSV: commune_code,province,district,ward,area_code.
 */

"use client"

import { useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

import { useImportCommuneCsv } from "@/lib/hooks/useCommuneKvAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import type { CsvImportResponse } from "@/lib/zod/commune-kv"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImportCommuneCsvDialog({ open, onOpenChange }: Props) {
  const importMutation = useImportCommuneCsv()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<CsvImportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setFile(null)
    setResult(null)
    setError(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  const handleImport = async () => {
    if (!file) {
      setError("Chọn file CSV trước")
      return
    }
    setError(null)
    try {
      const res = await importMutation.mutateAsync(file)
      setResult(res)
      toast.success(
        `Import xong: +${res.inserted} mới, ${res.skipped_existing} bỏ qua`,
      )
    } catch (e) {
      setError(parseApiError(e, "Import thất bại"))
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import CSV — KV theo Xã</DialogTitle>
          <DialogDescription>
            Cột bắt buộc: <code>commune_code,province,district,ward,area_code</code>
            . Encode UTF-8. Idempotent — bỏ qua xã đã có dòng đang áp dụng.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid gap-2">
            <Label htmlFor="csv-file">File CSV</Label>
            <Input
              id="csv-file"
              ref={inputRef}
              type="file"
              accept=".csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setResult(null)
                setError(null)
              }}
            />
          </div>

          {result && (
            <div className="bg-muted/40 rounded-md border p-3 text-sm">
              <p>
                ✅ Thêm mới: <strong>{result.inserted}</strong> · Bỏ qua (đã có):{" "}
                <strong>{result.skipped_existing}</strong> · Lỗi dòng:{" "}
                <strong>{result.error_rows.length}</strong>
              </p>
              {result.error_rows.length > 0 && (
                <ul className="text-muted-foreground mt-2 max-h-32 list-disc overflow-auto pl-5 text-xs">
                  {result.error_rows.slice(0, 20).map((row, i) => (
                    <li key={i}>{JSON.stringify(row)}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              reset()
              onOpenChange(false)
            }}
            disabled={importMutation.isPending}
          >
            Đóng
          </Button>
          <Button
            onClick={handleImport}
            disabled={importMutation.isPending || !file}
          >
            {importMutation.isPending ? "Đang import…" : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
