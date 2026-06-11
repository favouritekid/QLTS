/**
 * ImportSchoolCsvDialog — upload CSV trường (school-only; KV qua dialog KV).
 * POST /api/v2/admin/vn-school/schools/import (idempotent).
 * Cột: moet_school_code,moet_province_code,name,province,level (+ tuỳ chọn).
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

import { useImportSchoolCsv } from "@/lib/hooks/useVnSchoolAdmin"
import { parseApiError } from "@/lib/utils/api-errors"
import type { CsvImportResponse } from "@/lib/zod/vn-school-admin"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ImportSchoolCsvDialog({ open, onOpenChange }: Props) {
  const importMutation = useImportSchoolCsv()
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
          <DialogTitle>Import CSV — Trường</DialogTitle>
          <DialogDescription>
            Cột bắt buộc:{" "}
            <code>moet_school_code,moet_province_code,name,province,level</code>
            {" "}(+ moet_district_code/district/ward/is_dtnt tuỳ chọn). UTF-8,
            idempotent. KV phân loại qua nút &quot;Quản lý KV&quot;.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid gap-2">
            <Label htmlFor="school-csv">File CSV</Label>
            <Input
              id="school-csv"
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
                  {result.error_rows.slice(0, 20).map((row, i) => {
                    const rn = row.row_num
                    const err = row.error
                    return (
                      <li key={i}>
                        {rn != null ? `Dòng ${rn}: ` : ""}
                        {typeof err === "string" ? err : JSON.stringify(row)}
                      </li>
                    )
                  })}
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
